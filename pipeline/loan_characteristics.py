#!/usr/bin/env python3
"""
loan_characteristics.py

Computes the factor characteristics for every loan and period (month or quarter), used for
the factor analysis and the public factor database.

Inputs (from the existing pipeline)
    nport_out/loan_monthly_stm_cer.parquet     or loan_quarterly_stm_cer.parquet
    nport_out/loan_price_panel_v2.parquet      (valuation dispersion, notional, fair value level)

Repayment assumption
    If a loan permanently leaves the panel (last observation at least EXIT_BUFFER_M months before
    the end of the data), with a last price between EXIT_MIN_PRICE and EXIT_MAX_PRICE, last held by
    at least EXIT_MIN_FUNDS funds and without a default flag, repayment at par in the following
    period is assumed and appended as an additional row (exit_row = True):
        ret       = (100 - P)/P + coupon/12 - base rate/12            (per month, quarter accordingly)
        tr        = (100 - P)/P + coupon/12
        ret_paper = STM/12 + log(100/P)
    All other exits (distressed, defaulted) keep no final return.

Weights
    mv12 = market value of fund holdings (value_total), average over the last 12 months per loan

Returns (decimal, period t-1 -> t)
    ret        = total return minus base rate (main measure, exact from price and coupon)
    tr         = total return without base rate deduction
    ret_paper  = STM_{t-1}/12*k + log(P_t / P_{t-1})   (CER as in FAJ 2022, robustness)
    ret_next, ret_paper_next = return of the following period (only for consecutive periods)

Factor characteristics at time t (sign: + = high value preferred)
    mom_3m       (+)  ret_{t-2} + ret_{t-1} + ret_t             cumulative over 3 periods
    mom_skip1    (+)  ret_{t-1}                                 one period skipped (FAJ: MOM t-2,t-1)
    mom_3m_skip  (+)  ret_{t-3} + ret_{t-2} + ret_{t-1}         3 periods, skipping one (FAJ: MOM t-4,t-1)
    value_vol    (+)  STM_t / std. dev. of price returns        12 months (min. 6) or 8 quarters (min. 4)
    value_resid  (+)  residual of log(STM) ~ log(margin), remaining maturity, PIK, log(funds),
                      log(notional), fair value level 3
    carry        (+)  STM_t                                     as in JPM 2024
    low_risk     (-)  spread duration_t                         as in JPM 2024
    illiq_funds  (+)  fewer holding funds = more illiquid (ties broken by held notional)
    illiq_size   (+)  -log(notional held by funds)              smaller positions = more illiquid
    ivol         (-)  idiosyncratic volatility: std. dev. of residuals of ret_i ~ market_t + market_{t-1}
                      over the last 12 months (min. 8 returns); monthly data only
    bab_beta     (-)  Dimson beta (sum of betas on market_t and market_{t-1}) from the same regression,
                      betting against beta following Frazzini/Pedersen (2014); monthly data only
                      market = equal-weighted return of all loans in the universe in the prior month
                      (alternatively an own series via --market-csv, e.g. Morningstar LSTA)
    value_el     (+)  excess spread: STM_t - PD_t * LGD * 100 (all in % p.a.)
                      PD_t: 12-month default probability from a logit model with L2 penalty on price,
                      margin, PIK, log(funds), fair value level 3, remaining maturity; estimated at each
                      quarter-end with an expanding window using only observations whose 12-month
                      outcome was known at that time (t <= estimation date - 12 months), on all loans
                      (including distressed ones); only once PD_MIN_EVENTS defaults are in the window
                      LGD: 1 - median price in the default month (within the estimation window)
                      default: default flag of a fund, event = first reported default after t
    value_pd     (+)  STM_t / PD_t as in the JPM paper (STM/PD), with the model PD instead of the Merton PD
    value_vol_s  (+)  value_vol restricted to loans with IVOL (same sample as value_vol_adj)
    value_vol_adj(+)  monthly residual of log(value_vol) ~ log(ivol): value signal without the part
                      explained by idiosyncratic volatility; monthly data only
    combi_jpm    (+)  average of signed z-scores of the six JPM factors value_pd, mom_3m_skip,
                      illiq_funds, pd_hat (-), low_risk (-), carry plus ivol (-) and bab_beta (-);
                      at least 6 of 8 available
    combi        (+)  average of signed z-scores of COMBI_MOMENTUM, VALUE_MAIN, carry, low_risk
                      (at least 3 available)

Investable universe at time t (as in the JPM paper)
    price_t >= min(20% quantile of prices in the month, 80) and price_t <= 105,
    remaining maturity > 120 days, plausible margin, identified loans only (see --keys)

Usage
    python loan_characteristics.py --freq M
    python loan_characteristics.py --freq Q
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm

VALUE_MAIN = "value_vol"     # value variant in the (legacy) combi factor
COMBI_MOMENTUM = "mom_3m_skip"  # momentum variant in the combi factor (no shared price with the next return)
VOL_FLOOR = 0.0001           # lower bound for volatility (1 bp), avoids division by zero
# Legacy combi only from factors with a direct counterpart in FAJ 2022 / JPM 2024
# (quality and illiquidity are measured in N-PORT only via proxies of different constructs)
FACTOR_SIGNS = {COMBI_MOMENTUM: 1, VALUE_MAIN: 1, "carry": 1, "low_risk": -1}
MIN_COMBI = 3

# Repayment assumption for loans that leave the panel
EXIT_MIN_PRICE = 95          # last price at least 95 and no default flag -> repayment at par
EXIT_MAX_PRICE = 105         # prices above 105 are mostly data errors -> no repayment assumption
EXIT_MIN_FUNDS = 2           # only loans last held by at least 2 funds: if a loan disappears from
                             # several funds at once, repayment is likely; with only one fund it
                             # may just as well be a sale
EXIT_BUFFER_M = 6            # only loans whose last observation is at least 6 months before the data end
# Combi: equal-weighted z-scores of the six JPM factors (N-PORT versions) plus IVOL and BAB
JPM_SIGNS = {"value_pd": 1, "mom_3m_skip": 1, "illiq_funds": 1, "pd_hat": -1, "low_risk": -1, "carry": 1,
             "ivol": -1, "bab_beta": -1}
MIN_COMBI_JPM = 6            # at least 6 of the 8 signals available

# Default model for Value (EL) / Value (PD) / Quality (PD)
PD_HORIZON_M = 12            # forecast horizon in months
PD_MIN_EVENTS = 100          # minimum number of defaults in the estimation window
PD_RIDGE = 1e-4              # L2 penalty (on standardized variables)
EXT_LGD = 0.40               # LGD used with an external PD (--pd-file)


def month_end(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s).dt.normalize() + pd.offsets.MonthEnd(0)


def shifted(df: pd.DataFrame, col: str, k: int, step: int) -> pd.Series:
    """Value of col k periods before (k>0) or after (k<0), only for consecutive periods."""
    g = df.groupby("LOAN_KEY")
    ok = g["MONTH_END"].shift(k) == df["MONTH_END"] - pd.offsets.MonthEnd(step * k)
    return g[col].shift(k).where(ok)


def zscore(df: pd.DataFrame, col: str) -> pd.Series:
    g = df.groupby("MONTH_END")[col]
    return (df[col] - g.transform("mean")) / g.transform("std")


def residual_value(df: pd.DataFrame) -> pd.Series:
    """Relative spread: residual per period of log(STM) on risk and liquidity characteristics."""
    x = pd.DataFrame({
        "log_margin": np.log(df["margin"].where(df["margin"] > 0)),
        "years_left": (df["maturity"] - df["MONTH_END"]).dt.days / 365.25,
        "pik": df["any_pik"].fillna(False).astype(float),
        "log_funds": np.log(df["n_funds"].clip(lower=1)),
        "log_par": np.log(df["par_total"].where(df["par_total"] > 0)),
        "fv3": (df["fv_level_mode"].astype(str) == "3").astype(float),
    }, index=df.index)
    y = np.log(df["stm"].where(df["stm"] > 0))
    out = pd.Series(np.nan, index=df.index)
    for _, idx in df.groupby("MONTH_END").groups.items():
        d = pd.concat([y.loc[idx].rename("y"), x.loc[idx]], axis=1).dropna()
        cols = [c for c in x.columns if d[c].std() > 0]
        if len(d) < len(cols) + 20:
            continue
        fit = sm.OLS(d["y"], sm.add_constant(d[cols])).fit()
        out.loc[d.index] = fit.resid
    return out


def pd_features(df: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({
        "price": df["price"] / 100,
        "margin": df["margin"],
        "pik": df["any_pik"].fillna(False).astype(float),
        "log_funds": np.log(df["n_funds"].clip(lower=1)),
        "fv3": (df["fv_level_mode"].astype(str) == "3").astype(float),
        "years_left": ((df["maturity"] - df["MONTH_END"]).dt.days / 365.25).clip(0, 10),
    }, index=df.index)


def auc(y: np.ndarray, p: np.ndarray) -> float:
    """Area under the ROC curve (Mann-Whitney), without sklearn."""
    r = pd.Series(p).rank().to_numpy()
    n1 = y.sum()
    n0 = len(y) - n1
    return (r[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0) if n1 and n0 else np.nan


def expected_loss_value(df: pd.DataFrame) -> pd.DataFrame:
    """Logit default model with expanding window, re-estimated quarterly; returns pd_hat, lgd_hat."""
    d = df.sort_values(["LOAN_KEY", "MONTH_END"]).copy()
    d["dflt"] = d["any_default"].fillna(False).astype(bool)
    # next reported default after t (strictly later)
    s = d["MONTH_END"].where(d["dflt"])
    nxt = s.groupby(d["LOAN_KEY"]).shift(-1)
    d["next_dflt"] = nxt.groupby(d["LOAN_KEY"]).bfill()
    horizon = d["MONTH_END"] + pd.DateOffset(months=PD_HORIZON_M)
    d["y"] = ((d["next_dflt"] <= horizon) & ~d["dflt"]).astype(float)
    # event months (transition into default) for LGD and counting
    prev = d.groupby("LOAN_KEY")["dflt"].shift(1)
    d["event"] = d["dflt"] & (prev == False)

    X_all = pd_features(d)
    feats = list(X_all.columns)
    usable = X_all.notna().all(axis=1) & ~d["dflt"]
    d["pd_hat"], d["lgd_hat"] = np.nan, np.nan

    est_dates = sorted(m for m in d["MONTH_END"].unique() if pd.Timestamp(m).month in (3, 6, 9, 12))
    log = []
    for i, T in enumerate(est_dates):
        T = pd.Timestamp(T)
        cutoff = T - pd.DateOffset(months=PD_HORIZON_M)
        train = usable & (d["MONTH_END"] <= cutoff)
        n_ev = int(d.loc[train & (d["y"] == 1), "LOAN_KEY"].nunique())   # defaulted loans, not loan-months
        if n_ev < PD_MIN_EVENTS:
            continue
        Xt = X_all.loc[train, feats]
        mu, sd = Xt.mean(), Xt.std().replace(0, 1)
        Z = sm.add_constant(((Xt - mu) / sd).to_numpy())
        fit = sm.GLM(d.loc[train, "y"].to_numpy(), Z, family=sm.families.Binomial()).fit_regularized(
            alpha=PD_RIDGE, L1_wt=0.0)
        ev_px = d.loc[d["event"] & (d["MONTH_END"] <= T), "price"]
        lgd = float(np.clip(1 - ev_px.median() / 100, 0.1, 0.9)) if len(ev_px) >= 20 else 0.3
        # apply to the months until the next estimation
        T_next = pd.Timestamp(est_dates[i + 1]) if i + 1 < len(est_dates) else d["MONTH_END"].max()
        start_ok = (d["MONTH_END"] >= T) if not log else (d["MONTH_END"] > T)
        app = usable & start_ok & (d["MONTH_END"] <= T_next)
        if app.any():
            Za = sm.add_constant(((X_all.loc[app, feats] - mu) / sd).to_numpy(), has_constant="add")
            d.loc[app, "pd_hat"] = 1 / (1 + np.exp(-(Za @ fit.params)))
            d.loc[app, "lgd_hat"] = lgd
        log.append((T.date(), int(train.sum()), n_ev, round(lgd, 2)))

    if log:
        print(f"\nDefault model: first estimation {log[0][0]} ({log[0][2]} defaults), last {log[-1][0]} "
              f"({log[-1][2]} defaulted loans, {log[-1][1]:,} observations), latest LGD {log[-1][3]:.0%}")
        # out-of-sample quality: only observations with known 12-month outcome
        known = d["pd_hat"].notna() & (d["MONTH_END"] + pd.DateOffset(months=PD_HORIZON_M) <= d["MONTH_END"].max())
        if known.any():
            k = d.loc[known]
            print(f"Out-of-sample: AUC {auc(k['y'].to_numpy(), k['pd_hat'].to_numpy()):.3f} | "
                  f"mean PD {k['pd_hat'].mean():.2%} vs. realized default rate {k['y'].mean():.2%}")
            cal = k.groupby(k["MONTH_END"].dt.year).agg(PD=("pd_hat", "mean"), realized=("y", "mean"))
            print((cal * 100).round(2).rename(columns=lambda c: c + " (%)").to_string())
    else:
        print("\nDefault model: too few defaults for an estimation")
    return d[["LOAN_KEY", "MONTH_END", "pd_hat", "lgd_hat"]]


def rolling_market_model(df: pd.DataFrame, mkt: pd.Series, window: int = 12, min_obs: int = 8):
    """Rolling market model per loan: ret_i,t = a + b0*market_t + b1*market_{t-1} + e.

    Returns (Dimson beta b0+b1, std. dev. of residuals) per LOAN_KEY and MONTH_END.
    Vectorized over all loans: per month a window of `window` calendar months.
    """
    Y = df.pivot_table(index="MONTH_END", columns="LOAN_KEY", values="ret", aggfunc="first")
    months = pd.date_range(Y.index.min(), Y.index.max(), freq="ME")
    Y = Y.reindex(months)
    m = mkt.reindex(months)
    X = np.column_stack([np.ones(len(months)), m.values, m.shift(1).values])
    Yv = Y.to_numpy(float)
    out_beta = np.full(Yv.shape, np.nan)
    out_ivol = np.full(Yv.shape, np.nan)
    for t in range(window - 1, len(months)):
        rows = slice(t - window + 1, t + 1)
        x = X[rows]
        y = Yv[rows]
        mask = np.isfinite(y) & np.isfinite(x).all(axis=1)[:, None]
        n = mask.sum(axis=0)
        ok = n >= min_obs
        if not ok.any():
            continue
        xz = np.nan_to_num(x)
        M = mask[:, ok].astype(float)
        yv = np.nan_to_num(y[:, ok])
        XtX = np.einsum("rn,ri,rj->nij", M, xz, xz)
        Xty = np.einsum("rn,ri->ni", M * yv, xz)
        good = np.abs(np.linalg.det(XtX)) > 1e-14
        b = np.full((ok.sum(), 3), np.nan)
        b[good] = np.linalg.solve(XtX[good], Xty[good][..., None])[..., 0]
        resid = (yv - xz @ b.T) * M
        dof = (n[ok] - 3).clip(min=1)
        idx = np.where(ok)[0]
        out_beta[t, idx] = b[:, 1] + b[:, 2]
        out_ivol[t, idx] = np.sqrt((resid ** 2).sum(axis=0) / dof)
    res = pd.DataFrame({
        "MONTH_END": np.repeat(months, Yv.shape[1]),
        "LOAN_KEY": np.tile(Y.columns.values, len(months)),
        "bab_beta": out_beta.ravel(),
        "ivol": out_ivol.ravel(),
    }).dropna(subset=["bab_beta", "ivol"], how="all")
    return res


def main() -> None:
    ap = argparse.ArgumentParser(description="Factor characteristics per loan and period")
    ap.add_argument("--freq", choices=["M", "Q"], default="M")
    ap.add_argument("--dir", default="nport_out")
    ap.add_argument("--cer-stm-file", default=None,
                    help="optional: external spread-to-maturity for the CER only (Parquet with LOAN_KEY, MONTH_END, "
                         "stm_cer in %% p.a.), e.g. Markit's STM; signals keep the pipeline's own STM")
    ap.add_argument("--pd-file", default=None,
                    help="optional: external 12-month PD (Parquet with LOAN_KEY, MONTH_END, pd in decimals), "
                         "e.g. the Markit PD; replaces the logit default model")
    ap.add_argument("--market-csv", default=None,
                    help="optional: own market return (columns date, monthly excess return in decimals)")
    ap.add_argument("--keys", choices=["identified", "lx", "all"], default="identified",
                    help="identified = LX/CUSIP/ISIN/FIGI (without name keys)")
    args = ap.parse_args()

    base = Path(args.dir)
    step = 1 if args.freq == "M" else 3
    src = base / ("loan_monthly_stm_cer.parquet" if args.freq == "M" else "loan_quarterly_stm_cer.parquet")
    df = pd.read_parquet(src)
    df["MONTH_END"] = month_end(df["MONTH_END"])
    df["maturity"] = pd.to_datetime(df["maturity"], errors="coerce")

    panel = pd.read_parquet(base / "loan_price_panel_v2.parquet",
                            columns=["LOAN_KEY", "MONTH_END", "par_total", "value_total", "fv_level_mode"])
    panel["MONTH_END"] = month_end(panel["MONTH_END"])
    df = df.merge(panel, on=["LOAN_KEY", "MONTH_END"], how="left")

    if args.keys == "identified":
        df = df[df["key_type"] != "NM"]
    elif args.keys == "lx":
        df = df[df["key_type"] == "LX"]
    df = df.sort_values(["LOAN_KEY", "MONTH_END"]).reset_index(drop=True)
    print(f"{src.name}: {len(df):,} observations, {df['LOAN_KEY'].nunique():,} loans (keys: {args.keys})")

    # --- Returns
    df["price_ret"] = np.log(df["price"] / shifted(df, "price", 1, step))
    df["ret"] = df["cer"].where(~df["return_outlier"].fillna(False))
    df["tr"] = df["total_return"].where(~df["return_outlier"].fillna(False))   # total return without base rate deduction
    stm_src = "stm"
    if args.cer_stm_file:                      # e.g. Markit's own spread-to-maturity, used only for ret_paper
        ext = pd.read_parquet(args.cer_stm_file, columns=["LOAN_KEY", "MONTH_END", "stm_cer"])
        ext["MONTH_END"] = month_end(ext["MONTH_END"])
        df = df.merge(ext.drop_duplicates(["LOAN_KEY", "MONTH_END"]), on=["LOAN_KEY", "MONTH_END"], how="left")
        stm_src = "stm_cer"
        print(f"CER (ret_paper) with external STM from {args.cer_stm_file}")
    stm_lag = shifted(df, stm_src, 1, step)
    df["ret_paper"] = (stm_lag / 100 * step / 12 + df["price_ret"]).where(df["ret"].notna())
    # --- Repayment assumption: additional return row for loans that were probably repaid
    df["exit_row"] = False
    last = df.groupby("LOAN_KEY")["MONTH_END"].transform("max")
    end = df["MONTH_END"].max()
    cand = (df["MONTH_END"].eq(last) & (df["MONTH_END"] <= end - pd.DateOffset(months=EXIT_BUFFER_M))
            & df["price"].between(EXIT_MIN_PRICE, EXIT_MAX_PRICE) & (df["n_funds"] >= EXIT_MIN_FUNDS)
            & ~df["any_default"].fillna(False).astype(bool)
            & df["coupon"].notna())
    ex = df.loc[cand, ["LOAN_KEY", "MONTH_END", "key_type", "price", "coupon", "base", "stm"]].copy()
    ex_rows = pd.DataFrame({
        "LOAN_KEY": ex["LOAN_KEY"].values,
        "MONTH_END": (ex["MONTH_END"] + pd.offsets.MonthEnd(step)).values,
        "key_type": ex["key_type"].values,
        "ret": ((100 - ex["price"]) / ex["price"] + ex["coupon"] / 100 * step / 12
                - ex["base"].fillna(0) / 100 * step / 12).values,
        "ret_paper": (ex["stm"] / 100 * step / 12 + np.log(100 / ex["price"])).values,
        "tr": ((100 - ex["price"]) / ex["price"] + ex["coupon"] / 100 * step / 12).values,
        "exit_row": True,
    })
    n_exit_all = df.loc[df["MONTH_END"].eq(last) & (df["MONTH_END"] <= end - pd.DateOffset(months=EXIT_BUFFER_M)),
                        "LOAN_KEY"].nunique()
    print(f"Exits from the panel: {n_exit_all:,} loans, of which {len(ex_rows):,} with assumed "
          f"repayment at par ({len(ex_rows) / max(n_exit_all, 1):.0%})")
    df = pd.concat([df, ex_rows], ignore_index=True).sort_values(["LOAN_KEY", "MONTH_END"]).reset_index(drop=True)

    df["ret_next"] = shifted(df, "ret", -1, step)
    df["ret_paper_next"] = shifted(df, "ret_paper", -1, step)

    # --- Volatility of price returns (time-based window, gaps are respected)
    window, min_obs = ("366D", 6) if args.freq == "M" else ("731D", 4)
    mv = (df.set_index("MONTH_END").groupby("LOAN_KEY")["value_total"]
            .rolling("366D", min_periods=1).mean().reset_index().rename(columns={"value_total": "mv12"}))
    df = df.merge(mv, on=["LOAN_KEY", "MONTH_END"], how="left")
    vol = (df.set_index("MONTH_END").groupby("LOAN_KEY")["price_ret"]
             .rolling(window, min_periods=min_obs).std()
             .reset_index().rename(columns={"price_ret": "vol"}))
    df = df.merge(vol, on=["LOAN_KEY", "MONTH_END"], how="left")

    # --- Factor characteristics
    r1, r2, r3 = (shifted(df, "ret", k, step) for k in (1, 2, 3))
    df["mom_3m"] = df["ret"] + r1 + r2
    df["mom_skip1"] = r1
    df["mom_3m_skip"] = r1 + r2 + r3
    df["value_vol"] = df["stm"] / df["vol"].clip(lower=VOL_FLOOR)
    df["carry"] = df["stm"]
    df["low_risk"] = df["spread_duration"]
    par_pct = df.groupby("MONTH_END")["par_total"].rank(pct=True)
    df["illiq_funds"] = -(df["n_funds"] + 0.99 * par_pct)
    df["illiq_size"] = -np.log(df["par_total"].where(df["par_total"] > 0))

    # --- Investable universe at time t
    lower = df.groupby("MONTH_END")["price"].transform(lambda s: s.quantile(0.20)).clip(upper=80)
    days_left = (df["maturity"] - df["MONTH_END"]).dt.days
    df["universe"] = (df["price"].between(lower, 105) & (days_left > 120)
                      & df["margin_plausible"].fillna(False) & df["stm"].notna())

    # --- Value (EL): excess spread over the expected loss
    if args.pd_file:
        el = pd.read_parquet(args.pd_file, columns=["LOAN_KEY", "MONTH_END", "pd"]).rename(columns={"pd": "pd_hat"})
        el["MONTH_END"] = month_end(el["MONTH_END"])
        el["lgd_hat"] = EXT_LGD
        print(f"PD: external file {args.pd_file} ({el['pd_hat'].notna().sum():,} observations), LGD {EXT_LGD:.0%}")
    else:
        el = expected_loss_value(df)
    df = df.merge(el, on=["LOAN_KEY", "MONTH_END"], how="left")
    df["value_el"] = df["stm"] - df["pd_hat"] * df["lgd_hat"] * 100
    df["value_pd"] = df["stm"] / df["pd_hat"].clip(lower=1e-4)

    # --- IVOL and BAB (monthly data only)
    df["ivol"], df["bab_beta"] = np.nan, np.nan
    if args.freq == "M":
        if args.market_csv:
            mk = pd.read_csv(args.market_csv, sep=None, engine="python", dtype=str).iloc[:, :2]
            mk.columns = ["date", "mkt"]
            mk["date"] = month_end(pd.to_datetime(mk["date"], errors="coerce", dayfirst=True))
            mkt = pd.to_numeric(mk["mkt"].str.replace(",", ".", regex=False), errors="coerce")
            mkt = pd.Series(mkt.values, index=mk["date"]).groupby(level=0).last()
            print("Market proxy: own series from", args.market_csv)
        else:
            prev_uni = shifted(df, "universe", 1, step).fillna(False).astype(bool)
            mkt = df.loc[prev_uni].groupby("MONTH_END")["ret"].mean()
            print("Market proxy: equal-weighted return of the universe (prior month)")
        mm = rolling_market_model(df, mkt)
        df = df.drop(columns=["ivol", "bab_beta"]).merge(mm, on=["LOAN_KEY", "MONTH_END"], how="left")

    # --- Value (Vol) adjusted for IVOL (cross-sectional regression per month within the universe)
    df["value_vol_s"] = df["value_vol"].where(df["ivol"].notna())
    df["value_vol_adj"] = np.nan
    lv = np.log(df["value_vol"].where(df["value_vol"] > 0))
    li = np.log(df["ivol"].where(df["ivol"] > 0))
    ok = df["universe"] & lv.notna() & li.notna()
    for _, idx in df.index[ok].groupby(df.loc[ok, "MONTH_END"]).items():
        if len(idx) < 30:
            continue
        slope, icept = np.polyfit(li.loc[idx], lv.loc[idx], 1)
        df.loc[idx, "value_vol_adj"] = lv.loc[idx] - (icept + slope * li.loc[idx])

    # residual value and z-scores only within the universe
    u = df["universe"]
    df["value_resid"] = np.nan
    df.loc[u, "value_resid"] = residual_value(df.loc[u])
    for f, sign in FACTOR_SIGNS.items():
        df[f"z_{f}"] = np.nan
        df.loc[u, f"z_{f}"] = sign * zscore(df.loc[u], f).clip(-3, 3)
    zcols = [f"z_{f}" for f in FACTOR_SIGNS]
    df["combi"] = df[zcols].mean(axis=1).where(df[zcols].notna().sum(axis=1) >= MIN_COMBI)
    # Combi: six JPM factors plus IVOL and BAB
    jcols = []
    for f, sign in JPM_SIGNS.items():
        c = f"zj_{f}"
        df[c] = np.nan
        df.loc[u, c] = sign * zscore(df.loc[u], f).clip(-3, 3)
        jcols.append(c)
    df["combi_jpm"] = df[jcols].mean(axis=1).where(df[jcols].notna().sum(axis=1) >= MIN_COMBI_JPM)

    keep = ["LOAN_KEY", "MONTH_END", "key_type", "issuer_name", "loanx_id", "n_funds", "price",
            "stm", "margin", "spread_duration", "par_total", "value_total", "mv12", "exit_row", "universe",
            "ret", "tr", "ret_paper", "ret_next", "ret_paper_next", "price_ret", "vol",
            "mom_3m", "mom_skip1", "mom_3m_skip", "value_vol", "value_resid", "carry",
            "low_risk", "illiq_funds", "illiq_size", "ivol", "bab_beta", "value_vol_s",
            "value_vol_adj", "pd_hat", "lgd_hat", "value_el", "value_pd", "combi", "combi_jpm"]
    out = base / f"loan_characteristics_{args.freq}.parquet"
    df[keep].to_parquet(out, index=False)

    # --- Overview
    uu = df[df["universe"]]
    print(f"\nUniverse: {len(uu):,} observations, {uu['LOAN_KEY'].nunique():,} loans, "
          f"median {uu.groupby('MONTH_END').size().median():.0f} loans per period")
    print(f"Share with next-period return: {uu['ret_next'].notna().mean():.1%}")
    cov = uu[["mom_3m", "mom_skip1", "mom_3m_skip", "value_vol", "value_resid", "carry",
              "low_risk", "illiq_funds", "illiq_size", "ivol", "bab_beta", "value_pd", "pd_hat",
              "combi", "combi_jpm"]].notna().mean()
    print("\nSignal coverage in the universe:")
    print(cov.round(3).to_string())
    print("\nRank correlations of the signals (Spearman):")
    print(uu[["mom_3m_skip", "value_vol", "value_vol_adj", "value_el", "value_pd", "pd_hat", "carry", "low_risk",
              "illiq_funds", "ivol", "bab_beta", "vol"]].corr(method="spearman").round(2).to_string())
    print(f"\nSaved: {out}")


if __name__ == "__main__":
    main()
