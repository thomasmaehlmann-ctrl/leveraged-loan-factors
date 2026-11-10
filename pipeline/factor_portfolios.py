#!/usr/bin/env python3
"""
factor_portfolios.py

Factor analysis based on loan_characteristics_{M|Q}.parquet, following
Maehlmann/Sukonnik (FAJ 2022) and Maehlmann/Reck (JPM 2024):

  * Sorting per period into quintiles by the signal at t, investable universe at t
  * Benchmark: all sorted loans of the respective factor, same weighting
  * Statistics (annualized): return, volatility, Sharpe ratio, outperformance,
    tracking error, information ratio, CAPM alpha and beta against the benchmark,
    Newey-West t-statistics (lag 3, no prewhitening), plus long-short (preferred - opposite)
  * Dimson alpha and beta (benchmark at t, t-1, t-2) against smoothed valuations
  * Holding period of 1 period and overlapping portfolios following Jegadeesh/Titman
    (default 6 months or 2 quarters, via --hold-months), benchmark with the same holding period
  * Options: weighting (ew, vw, vw_cap), implementation lag, treatment of exits, sample period
  * Panel regression of the next-period return on standardized factors with loan and
    time fixed effects, standard errors double-clustered (loan, period)

Outputs in --out-dir (default nport_out/factor_results_{freq})
  summary_hold1.csv / summary_holdK.csv    statistics of the preferred portfolio per factor
  quintiles_hold1.csv / quintiles_holdK.csv mean returns Q1..Q5 and long-short per factor
  panel_regression.csv                      fixed effects regressions (bp per standard deviation)
  factor_returns.parquet                    time series of all portfolios
  cumulative_hold1.png                      cumulative returns of the preferred portfolios

Usage
  python factor_portfolios.py --freq M
  python factor_portfolios.py --freq M --lag 1 --weighting vw_cap
  python factor_portfolios.py --freq M --ret ret_paper      (robustness with CER as in the FAJ paper)
"""

import argparse
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm

warnings.filterwarnings("ignore", message="invalid value encountered in sqrt")

# factor -> (column, direction): +1 = high quintile preferred, -1 = low quintile preferred
FACTORS = {                                  # JPM 2024 factors (N-PORT versions) plus IVOL and BAB
    "Value (PD)":     ("value_pd", 1),           # STM / model PD
    "Momentum":       ("mom_3m_skip", 1),        # cumulative t-3 ... t-1 (one month skipped)
    "Illiquidity":    ("illiq_funds", 1),        # fewer holding funds = more illiquid
    "Quality (PD)":   ("pd_hat", -1),            # low model PD preferred
    "Low Risk":       ("low_risk", -1),          # low spread duration preferred
    "Carry":          ("carry", 1),              # STM
    "IVOL":           ("ivol", -1),              # low idiosyncratic volatility preferred
    "BAB":            ("bab_beta", -1),          # low Dimson beta preferred
    "Combi":          ("combi_jpm", 1),          # equal-weighted z-scores of the eight factors
}
REG_VARS = ["value_pd", "mom_3m_skip", "illiq_funds", "pd_hat", "low_risk", "carry", "ivol", "bab_beta"]
UNI_VARS = REG_VARS
EXTRA_SPECS = {}


# --------------------------------------------------------------------------- #
# Helper functions
# --------------------------------------------------------------------------- #
def nw(y: pd.Series, x: pd.Series | None, lags: int):
    """OLS with Newey-West standard errors (as coeftest(..., NeweyWest(lag, prewhite=F)) in R)."""
    X = np.ones((len(y), 1)) if x is None else sm.add_constant(x.values)
    return sm.OLS(y.values, X).fit(cov_type="HAC", cov_kwds={"maxlags": lags})


def assign_portfolios(d: pd.DataFrame, col: str, q: int) -> pd.Series:
    pct = d.groupby("MONTH_END")[col].rank(pct=True, method="first")
    return np.ceil(pct * q).clip(1, q).astype(int)


def portfolio_returns(df: pd.DataFrame, col: str, q: int, step: int, hold: int, ret: str,
                      lag: int = 0, weighting: str = "ew") -> pd.DataFrame:
    """Time series of quintile and benchmark returns (columns 1..q, BM), index = return date.

    Formation at t (universe at t, signal at t), cohort held from t+1+lag to t+hold+lag.
    Strategy return = equal-weighted average of the active cohorts (Jegadeesh/Titman).
    Within a cohort: weights fixed at formation (ew, vw = mv12, vw_cap = mv12 capped at the
    monthly 80th percentile), renormalized proportionally if a return is missing.
    Benchmark = all sorted loans with the same weighting.
    """
    d = df[df["universe"] & df[col].notna()].copy()
    d["port"] = assign_portfolios(d, col, q)
    if weighting == "ew":
        d["w"] = 1.0
    else:
        d["w"] = d["mv12"]
        if weighting == "vw_cap":
            cap = d.groupby("MONTH_END")["w"].transform(lambda x: x.quantile(0.80))
            d["w"] = d["w"].clip(upper=cap)
        d = d[d["w"] > 0]
    bm = d.copy()
    bm["port"] = 0
    forms = pd.concat([d[["LOAN_KEY", "MONTH_END", "port", "w"]], bm[["LOAN_KEY", "MONTH_END", "port", "w"]]])
    rets = df[["LOAN_KEY", "MONTH_END", ret]].rename(columns={"MONTH_END": "date", ret: "r"}).dropna()

    cohorts = []
    for k in range(1 + lag, hold + lag + 1):
        f = forms.copy()
        f["date"] = f["MONTH_END"] + pd.offsets.MonthEnd(step * k)
        m = f.merge(rets, on=["LOAN_KEY", "date"], how="inner")
        m["wr"] = m["w"] * m["r"]
        g = m.groupby(["date", "port"])
        cohorts.append((g["wr"].sum() / g["w"].sum()).rename(k))
    c = pd.concat(cohorts, axis=1)
    out = c.mean(axis=1).unstack("port")
    if hold > 1:
        out = out.iloc[hold - 1:]                             # only once all cohorts are built
    out = out.rename(columns={0: "BM"})
    return out.dropna(subset=["BM"]) if "BM" in out else out


def next_return(df: pd.DataFrame, ret: str, step: int) -> pd.Series:
    """Next-period return of the same loan (only for consecutive periods)."""
    g = df.groupby("LOAN_KEY")
    ok = g["MONTH_END"].shift(-1) == df["MONTH_END"] + pd.offsets.MonthEnd(step)
    return g[ret].shift(-1).where(ok)


def stats(p: pd.Series, bm: pd.Series, ppy: int, lags: int) -> dict:
    d = pd.concat([p.rename("p"), bm.rename("b")], axis=1).dropna()
    op = d["p"] - d["b"]
    mean, vol = d["p"].mean() * ppy, d["p"].std() * np.sqrt(ppy)
    te = op.std() * np.sqrt(ppy)
    t_op = nw(op, None, lags)
    capm = nw(d["p"], d["b"], lags)
    # Dimson (1979): contemporaneous and two lagged benchmark returns against smoothed prices
    dl = pd.concat([d["p"], d["b"], d["b"].shift(1).rename("b1"), d["b"].shift(2).rename("b2")],
                   axis=1).dropna()
    dim = sm.OLS(dl["p"].values, sm.add_constant(dl[["b", "b1", "b2"]].values)).fit(
        cov_type="HAC", cov_kwds={"maxlags": lags})
    return {
        "Return p.a. (bp)": mean * 1e4,
        "Volatility p.a. (bp)": vol * 1e4,
        "Sharpe ratio": mean / vol if vol > 0 else np.nan,
        "Outperformance p.a. (bp)": op.mean() * ppy * 1e4,
        "Tracking error p.a. (bp)": te * 1e4,
        "Information ratio": op.mean() * ppy / te if te > 0 else np.nan,
        "t outperformance": t_op.tvalues[0],
        "Alpha p.a. (bp)": capm.params[0] * ppy * 1e4,
        "t alpha": capm.tvalues[0],
        "Beta": capm.params[1],
        "Dimson alpha p.a. (bp)": dim.params[0] * ppy * 1e4,
        "t Dimson alpha": dim.tvalues[0],
        "Dimson beta (sum)": dim.params[1:].sum(),
        "Periods": len(d),
    }


def demean(df: pd.DataFrame, cols: list, ids: list, tol=1e-10, maxit=500) -> np.ndarray:
    """Within transformation for one or two fixed effects (alternating projections)."""
    X = df[cols].to_numpy(float).copy()
    gs = [pd.factorize(df[i])[0] for i in ids]
    ns = [np.bincount(g) for g in gs]
    for _ in range(maxit if len(ids) > 1 else 1):
        old = X.copy()
        for g, n in zip(gs, ns):
            for j in range(X.shape[1]):
                X[:, j] -= (np.bincount(g, weights=X[:, j]) / n)[g]
        if np.max(np.abs(X - old)) < tol:
            break
    return X


def panel_fe(df: pd.DataFrame, xs: list, ret: str, loan_fe: bool = True) -> dict:
    d = df.dropna(subset=xs + [ret]).copy()
    d["y"] = d[ret] * 1e4                                     # in basis points as in the paper
    xs = [x for x in xs if d[x].std() > 1e-8]                 # drop variables without variation
    if not xs:
        return {"N": len(d)}
    for x in xs:
        d[x] = (d[x] - d[x].mean()) / d[x].std()
    ids = ["LOAN_KEY", "MONTH_END"] if loan_fe else ["MONTH_END"]
    Z = demean(d, ["y"] + xs, ids)
    # variables that vary (almost) only between loans are not identified with loan fixed effects
    within = Z[:, 1:].std(axis=0) / d[xs].std().to_numpy()
    keep = within > 0.01
    if not keep.any():
        return {"N": len(d)}
    xs = [x for x, k in zip(xs, keep) if k]
    Z = np.column_stack([Z[:, 0], Z[:, 1:][:, keep]])
    groups = np.column_stack([pd.factorize(d["LOAN_KEY"])[0], pd.factorize(d["MONTH_END"])[0]])
    res = sm.OLS(Z[:, 0], Z[:, 1:]).fit(cov_type="cluster", cov_kwds={"groups": groups})
    out = {"N": len(d), "Loans": d["LOAN_KEY"].nunique(), "Periods": d["MONTH_END"].nunique()}
    for i, x in enumerate(xs):
        out[x] = f"{res.params[i]:.2f} ({res.tvalues[i]:.2f})"
    return out


# --------------------------------------------------------------------------- #
def main() -> None:
    ap = argparse.ArgumentParser(description="Factor portfolios and panel regressions")
    ap.add_argument("--freq", choices=["M", "Q"], default="M")
    ap.add_argument("--dir", default="nport_out")
    ap.add_argument("--ret", choices=["ret", "ret_paper"], default="ret",
                    help="ret = total return minus base rate (main), ret_paper = CER as in the FAJ paper")
    ap.add_argument("--quantiles", type=int, default=5)
    ap.add_argument("--hold-months", type=int, default=6,
                    help="holding period of the overlapping portfolios in months (default 6)")
    ap.add_argument("--weighting", choices=["ew", "vw", "vw_cap"], default="ew",
                    help="ew = equal-weighted, vw = market value of fund holdings (12-month average), "
                         "vw_cap = vw capped at the 80th percentile")
    ap.add_argument("--lag", type=int, default=0,
                    help="implementation lag in periods (1 = signal from t applies from t+2)")
    ap.add_argument("--exit", choices=["impute", "none"], default="impute",
                    help="impute = repayment assumption for loans that leave the sample, none = without")
    ap.add_argument("--start", default=None,
                    help="first return month of the evaluation, e.g. 2020-06 (common period for comparisons)")
    ap.add_argument("--end", default=None, help="last return month, e.g. 2026-04")
    ap.add_argument("--out-dir", default=None)
    args = ap.parse_args()

    step, ppy = (1, 12) if args.freq == "M" else (3, 4)
    hold_k = max(args.hold_months // step, 2)                 # holding period in periods
    lags = 3 if args.freq == "M" else 2
    q = args.quantiles

    base = Path(args.dir)
    df = pd.read_parquet(base / f"loan_characteristics_{args.freq}.parquet")
    df["MONTH_END"] = pd.to_datetime(df["MONTH_END"])
    if "exit_row" in df and args.exit == "none":
        df = df[~df["exit_row"].fillna(False).astype(bool)]
    df = df.sort_values(["LOAN_KEY", "MONTH_END"]).reset_index(drop=True)
    ret_next = "r_next"
    df[ret_next] = next_return(df, args.ret, step)
    out_dir = Path(args.out_dir) if args.out_dir else base / f"factor_results_{args.freq}"
    out_dir.mkdir(parents=True, exist_ok=True)
    pd.set_option("display.width", 200)
    print(f"Frequency: {args.freq} | Return: {args.ret} | Weighting: {args.weighting} | "
          f"Implementation lag: {args.lag} | Exits: {args.exit} | Quantiles: {q} | "
          f"Holding: 1 and {hold_k} periods | Newey-West lags: {lags} | "
          f"Period: {args.start or 'start'} to {args.end or 'end'}")

    all_series, results = [], {}
    for hold in (1, hold_k):
        summary, quint = {}, {}
        for name, (col, direction) in FACTORS.items():
            if col not in df or not df.loc[df["universe"], col].notna().any():
                continue                                      # e.g. IVOL/BAB on quarterly data
            pr = portfolio_returns(df, col, q, step, hold, args.ret, args.lag, args.weighting)
            if args.start:
                pr = pr[pr.index >= pd.Timestamp(args.start) + pd.offsets.MonthEnd(0)]
            if args.end:
                pr = pr[pr.index <= pd.Timestamp(args.end) + pd.offsets.MonthEnd(0)]
            if pr.empty or q not in pr.columns:
                continue
            best, worst = (q, 1) if direction == 1 else (1, q)
            pr["LS"] = pr[best] - pr[worst]
            s = stats(pr[best], pr["BM"], ppy, lags)
            b = stats(pr["BM"], pr["BM"], ppy, lags)
            s["Benchmark return p.a. (bp)"] = b["Return p.a. (bp)"]
            s["Benchmark Sharpe ratio"] = b["Sharpe ratio"]
            ls = nw(pr["LS"].dropna(), None, lags)
            s["Long-short p.a. (bp)"] = pr["LS"].mean() * ppy * 1e4
            s["t long-short"] = ls.tvalues[0]
            summary[name] = s
            row = {f"Q{c}": pr[c].mean() * ppy * 1e4 for c in range(1, q + 1)}
            row["BM"] = pr["BM"].mean() * ppy * 1e4
            row["LS (preferred - opposite)"] = s["Long-short p.a. (bp)"]
            row["t LS"] = s["t long-short"]
            row["preferred"] = f"Q{best}"
            quint[name] = row
            long = pr.reset_index().melt(id_vars="date", var_name="portfolio", value_name="return")
            long["factor"], long["hold"], long["freq"], long["ret_measure"] = name, hold, args.freq, args.ret
            long["weighting"], long["lag"], long["exit"] = args.weighting, args.lag, args.exit
            all_series.append(long)
        summary = pd.DataFrame(summary)
        quint = pd.DataFrame(quint).T
        tag = "hold1" if hold == 1 else "holdK"
        summary.to_csv(out_dir / f"summary_{tag}.csv")
        quint.to_csv(out_dir / f"quintiles_{tag}.csv")
        results[hold] = (summary, quint)
        print(f"\n=== Preferred portfolio per factor, holding period {hold} period(s); "
              "benchmark = all sorted loans of the respective factor ===")
        print(summary.round(2).to_string())
        print(f"\n=== Mean returns per quintile (bp p.a.), holding period {hold} ===")
        print(quint.to_string(float_format=lambda v: f"{v:.1f}"))

    series = pd.concat(all_series, ignore_index=True)
    series["portfolio"] = series["portfolio"].astype(str)
    series.to_parquet(out_dir / "factor_returns.parquet", index=False)

    # --- Panel regressions with loan and time fixed effects
    uni = df[df["universe"]].copy()
    uni["log_par"] = np.log(uni["par_total"].where(uni["par_total"] > 0))
    for loan_fe, label, fname in [(True, "loan and time FE", "panel_regression.csv"),
                                  (False, "time FE only", "panel_regression_timeFE.csv")]:
        rows = {}
        avail = [x for x in UNI_VARS if uni[x].notna().any()]
        for x in avail:
            rows[x] = panel_fe(uni, [x], ret_next, loan_fe)
        rows["multivariate"] = panel_fe(uni, [x for x in REG_VARS if x in avail], ret_next, loan_fe)
        for spec, xs in EXTRA_SPECS.items():
            if all(x in avail for x in xs):
                rows[spec] = panel_fe(uni, xs, ret_next, loan_fe)
        reg = pd.DataFrame(rows).T
        reg.to_csv(out_dir / fname)
        print(f"\n=== Panel regression: return t+1 (bp) on standardized factors, {label}, "
              "double-clustered (loan, period); coefficient (t-stat); empty = not identified ===")
        print(reg.to_string(na_rep=""))

    # --- Chart: cumulative returns, holding period 1
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        s1 = series[(series["hold"] == 1)]
        fig, ax = plt.subplots(figsize=(10, 5))
        bm = s1[(s1["factor"] == "Carry") & (s1["portfolio"] == "BM")].set_index("date")["return"]
        ax.plot(bm.index, ((1 + bm).cumprod() - 1) * 100, color="black", lw=2, label="Benchmark")
        for name, (col, direction) in FACTORS.items():
            best = str(q if direction == 1 else 1)
            r = s1[(s1["factor"] == name) & (s1["portfolio"] == best)].set_index("date")["return"]
            if len(r):
                ax.plot(r.index, ((1 + r).cumprod() - 1) * 100, lw=1.1, label=name)
        ax.set_ylabel("Cumulative return (%)")
        ax.set_title(f"Preferred factor portfolios vs. benchmark ({args.freq}, holding period 1)")
        ax.legend(fontsize=8, ncol=2)
        fig.tight_layout()
        fig.savefig(out_dir / "cumulative_hold1.png", dpi=150)
    except ImportError:
        pass
    print(f"\nResults saved in: {out_dir}")


if __name__ == "__main__":
    main()
