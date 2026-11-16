#!/usr/bin/env python3
"""
dl_index.py

Phases 3 and 4 of the direct lending project: quarterly position returns and direct lending indices.

Input
    dl_out/dl_positions.parquet   fund x borrower x calendar quarter-end (from dl_panel.py)
    optional --cdli FILE          CSV with columns quarter (e.g. 2024-03-31), total, income, price (in %)
    optional --ll-release DIR     a loanfactors release (factor_returns.csv) for the leveraged loan market index

Position returns (fund x borrower, from quarter-end t-1 to t, same fund)
    income  = average coupon of t-1 and t / 4 / P(t-1); zero if the loan is in default at t or its coupon is zero
    price   = (P(t) - P(t-1)) / P(t-1)
    total   = income + price
    Exit (fund reports at t, position gone): if P(t-1) >= 95 and not in default, repayment at par with half a
    quarter's coupon is assumed. Distressed exits (default flag, zero coupon or mark below --distress-price)
    are realized at a recovery rate estimated from the data (median mark in the first quarter of default or
    non-accrual), capped at the last mark; other exits below 95 are realized at the last mark. Alternatively,
    --distressed haircut applies a fixed haircut to all exits below 95.
    Prices refer to par (market value / principal), so PIK interest increases the principal but not the price;
    the full coupon (cash and PIK) is therefore part of the income return.

Components: the price return is split as in BDC accounting (cost = par) into realized gains and losses
(exits below par) and unrealized changes (marks of continuing positions and the reversal on exit).

Cost basis: N-PORT reports no cost. A running average cost per position is estimated (first mark for new
positions, par for positions held before the data begin; add-ons at the average mark), see add_cost_basis.

Credit health barometer (par- and cost-weighted): non-accrual share (coupon zero), share marked below 90, PIK share,
amended PIK (PIK newly flagged while marked below 96 and still paying), trailing four-quarter realized and
unrealized returns of the value-weighted index.

Indices (quarterly, from --start)
    EW managers (main)   equal-weighted average of manager returns; within a manager, positions are weighted
                         by their market value at t-1; managers with at least --min-positions positions
    VW all               value-weighted over all positions
    VW ex largest        value-weighted without the largest manager (Cliffwater)
    Largest manager      value-weighted, largest manager only
    EW positions         equal-weighted over all positions

Usage
    python dl_index.py
    python dl_index.py --cdli cdli.csv --ll-release releases/loanfactors_v2026.12
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm

REPAY_MIN_PRICE = 95.0


def as_bool(x: pd.Series) -> pd.Series:
    return x.map(lambda v: bool(v) if v is not None and v == v else False).astype(bool)


def estimate_recovery(pos: pd.DataFrame) -> float:
    """Recovery rate from the data: median mark (per 100 of par) of direct lending positions in the first
    quarter in which they are flagged in default or stop paying interest (coupon zero)."""
    p = pos.sort_values(["FUND_KEY", "borrower", "month_end"]).copy()
    p["non_accrual"] = p["coupon"].fillna(0).le(0.01)
    p["flag"] = as_bool(p["default"])
    for col, lab in [("flag", "default flag"), ("non_accrual", "non-accrual (coupon zero)")]:
        f = p[p[col]].groupby(["FUND_KEY", "borrower"]).head(1)
        if len(f):
            print(f"  first quarter with {lab}: n = {len(f):,}, median mark {f['price'].median():.1f}, "
                  f"p25 {f['price'].quantile(.25):.1f}, p75 {f['price'].quantile(.75):.1f}")
    # non-accrual is the economically relevant event; the default flag alone often marks technical defaults
    base = p[p["non_accrual"]] if p["non_accrual"].sum() >= 30 else p[p["non_accrual"] | p["flag"]]
    first = base.groupby(["FUND_KEY", "borrower"]).head(1)
    r = first["price"].median()
    print(f"Recovery estimate: median mark in the first non-accrual quarter = {r:.1f} (n = {len(first):,})")
    return r


def add_cost_basis(pos: pd.DataFrame) -> pd.DataFrame:
    """Running average cost per 100 of par for each fund x borrower position.

    First observation: the mark at that date (a new purchase), except for positions that already exist in the
    fund's first reported quarter (held before the data begin), which start at par. Increases in par are added
    at the average mark of the two quarter-ends; decreases (repayments, partial sales) leave the cost per unit
    unchanged. Discounts are not accreted to par over time."""
    pos = pos.sort_values(["FUND_KEY", "borrower", "month_end"]).copy()
    fund_first = pos.groupby("FUND_KEY")["month_end"].transform("min")
    cost = np.empty(len(pos))
    keys = (pos["FUND_KEY"] + "|" + pos["borrower"]).to_numpy()
    par, price, me, ff = (pos["par"].to_numpy(), pos["price"].to_numpy(), pos["month_end"].to_numpy(),
                          fund_first.to_numpy())
    for i in range(len(pos)):
        if i == 0 or keys[i] != keys[i - 1]:
            cost[i] = 100.0 if me[i] == ff[i] else price[i]
        else:
            add = par[i] - par[i - 1]
            if add > 0:
                cost[i] = (par[i - 1] * cost[i - 1] + add * (price[i - 1] + price[i]) / 2) / par[i]
            else:
                cost[i] = cost[i - 1]
    pos["cost_unit"] = cost
    pos["cost"] = pos["par"] * cost / 100
    legacy = (pos["month_end"] == fund_first).groupby([pos["FUND_KEY"], pos["borrower"]]).first()
    print(f"Cost basis: {len(legacy):,} positions, of which held before the data begin (cost = par): "
          f"{legacy.mean():.0%}; median cost of new positions {pos.loc[~(pos['month_end'] == fund_first), 'cost_unit'].median():.2f}")
    return pos


def position_returns(pos: pd.DataFrame, haircut: float | None = 0.0, recovery: float | None = None,
                     distress_price: float = 80.0) -> pd.DataFrame:
    pos = pos.sort_values(["FUND_KEY", "borrower", "month_end"]).copy()
    q = pos["month_end"]
    prev = pos.groupby(["FUND_KEY", "borrower"]).shift(1)
    consecutive = prev["month_end"].eq(q - pd.offsets.QuarterEnd(1))
    r = pos[consecutive].copy()
    p = prev[consecutive]
    in_default = as_bool(r["default"]) | r["coupon"].fillna(0).le(0)
    cpn = pd.concat([p["coupon"], r["coupon"]], axis=1).mean(axis=1)
    r["p0"], r["v0"], r["manager0"] = p["price"], p["value"], p["manager"]
    r["c0"] = p["cost_unit"] if "cost_unit" in p else 100.0
    r["income"] = np.where(in_default, 0.0, cpn / 4 / p["price"])
    r["price_ret"] = (r["price"] - p["price"]) / p["price"]
    r["exit"] = False
    r["distress"] = in_default | as_bool(p["default"]) | p["coupon"].fillna(0).le(0.01)

    # exits: position at t-1, fund reports at t, position missing at t
    reports = pos[["FUND_KEY", "month_end"]].drop_duplicates()
    nxt = pos[["FUND_KEY", "borrower", "month_end"]].copy()
    nxt["month_end"] = nxt["month_end"] - pd.offsets.QuarterEnd(1)
    last = pos.merge(nxt.assign(seen=True), on=["FUND_KEY", "borrower", "month_end"], how="left")
    last = last[last["seen"].isna()].copy()
    last["t"] = last["month_end"] + pd.offsets.QuarterEnd(1)
    last = last.merge(reports.rename(columns={"month_end": "t"}).assign(fund_reports=True), on=["FUND_KEY", "t"], how="inner")
    dflt = as_bool(last["default"]) | last["coupon"].fillna(0).le(0)
    ok = (last["price"] >= REPAY_MIN_PRICE) & ~dflt
    rep = last[ok].copy()
    rep["p0"], rep["v0"], rep["manager0"] = rep["price"], rep["value"], rep["manager"]
    rep["c0"] = rep["cost_unit"] if "cost_unit" in rep else 100.0
    rep["income"] = rep["coupon"] / 8 / rep["price"]
    rep["price_ret"] = (100 - rep["price"]) / rep["price"]
    rep["month_end"] = rep["t"]
    rep["exit"] = True
    # distressed exits (price < threshold or default): realized at the last mark less a haircut, no income;
    # haircut None leaves them out (survivorship bias: their losses would be missing)
    dis = last[~ok].copy()
    dis["p0"], dis["v0"], dis["manager0"] = dis["price"], dis["value"], dis["manager"]
    dis["c0"] = dis["cost_unit"] if "cost_unit" in dis else 100.0
    dis["income"] = 0.0
    dis["month_end"] = dis["t"]
    dis["exit"] = True
    if recovery is not None:
        # default-like exits (default flag, zero coupon or mark below distress_price): recovery, capped at the
        # last mark; other exits below the repayment threshold: realized at the last mark (treated as sales)
        deflike = dflt[~ok] | (dis["price"] < distress_price)
        exit_price = np.where(deflike, np.minimum(dis["price"], recovery), dis["price"])
        dis["price_ret"] = (exit_price - dis["price"]) / dis["price"]
        print(f"  distressed exits: {int(deflike.sum()):,} default-like -> recovery {recovery:.1f} (capped at the last mark); "
              f"{int((~deflike).sum()):,} others -> last mark")
        rep = pd.concat([rep, dis], ignore_index=True)
    elif haircut is not None:
        dis["price_ret"] = -haircut
        rep = pd.concat([rep, dis], ignore_index=True)
    print(f"Exits: {len(last):,}, of which assumed repaid at par: {ok.sum():,} ({ok.mean():.0%}); "
          f"distressed (price < {REPAY_MIN_PRICE:g} or default): {(~ok).sum():,} -> "
          + ("recovery rule" if recovery is not None else
             ("left out" if haircut is None else f"realized at the last mark less {haircut:.0%}")))
    rep["distress"] = True
    cols = ["FUND_KEY", "borrower", "month_end", "manager0", "v0", "p0", "c0", "income", "price_ret", "exit", "distress"]
    out = pd.concat([r[cols], rep[cols]], ignore_index=True).rename(columns={"manager0": "manager"})
    out["total"] = out["income"] + out["price_ret"]
    # split of the price return as in BDC accounting (cost = par): an exit realizes (exit price - 100) and
    # reverses the unrealized gain or loss (100 - P(t-1)); continuing positions have unrealized changes only
    exit_price = out["p0"] * (1 + out["price_ret"])
    out["realized"] = np.where(out["exit"], (exit_price - 100).clip(upper=0) / out["p0"], 0.0)
    out["unrealized"] = out["price_ret"] - out["realized"]
    # with the estimated cost basis: realized = exit price - average cost (gains possible, e.g. a loan bought
    # at a discount and repaid at par)
    # BDCs accrete purchase discounts (OID) to par through interest income, so a repayment at par realizes
    # no gain; the gain over our (unaccreted) cost is therefore shown separately as "accretion", which is
    # comparable to the fee and OID part of the CDLI income return
    gain = np.where(out["exit"], (exit_price - out["c0"]) / out["p0"], 0.0)
    out["realized_cost"] = np.minimum(gain, 0.0)
    out["accretion"] = np.maximum(gain, 0.0)
    out["unrealized_cost"] = out["price_ret"] - out["realized_cost"] - out["accretion"]
    return out


def wavg(df: pd.DataFrame, cols: list[str], w: str | None) -> pd.Series:
    if w is None:
        return df[cols].mean()
    ww = df[w] / df[w].sum()
    return (df[cols].mul(ww, axis=0)).sum()


def build_indices(ret: pd.DataFrame, min_pos: int, largest: str) -> dict[str, pd.DataFrame]:
    cols = ["total", "income", "price_ret", "realized", "unrealized", "realized_cost", "accretion", "unrealized_cost"]
    out = {}
    g = ret.groupby("month_end")
    mgr = ret.groupby(["month_end", "manager"]).apply(lambda x: pd.concat(
        [wavg(x, cols, "v0"), pd.Series({"n": len(x)})]), include_groups=False).reset_index()
    big = mgr[mgr["n"] >= min_pos]
    ew = big.groupby("month_end")[cols].mean()
    ew["managers"] = big.groupby("month_end").size()
    out["EW managers"] = ew
    out["VW all"] = g.apply(lambda x: wavg(x, cols, "v0"), include_groups=False)
    ex = ret[ret["manager"] != largest]
    out["VW ex largest"] = ex.groupby("month_end").apply(lambda x: wavg(x, cols, "v0"), include_groups=False)
    lg = ret[ret["manager"] == largest]
    out["Largest manager"] = lg.groupby("month_end").apply(lambda x: wavg(x, cols, "v0"), include_groups=False)
    out["EW positions"] = g[cols].mean()
    for k in out:
        out[k]["positions"] = (ret if k not in ("VW ex largest", "Largest manager")
                               else (ex if k == "VW ex largest" else lg)).groupby("month_end").size()
    return out


def summary(ix: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = {}
    for k, d in ix.items():
        t = d["total"]
        rows[k] = {"quarters": len(t), "total p.a. %": ((1 + t).prod() ** (4 / len(t)) - 1) * 100,
                   "income p.a. %": d["income"].mean() * 400, "price p.a. %": d["price_ret"].mean() * 400,
                   # the realized/unrealized split is meaningful only with value weights (as in the CDLI):
                   # with equal weights, write-offs of loans marked far below par dominate both components
                   "realized p.a. %": d["realized"].mean() * 400 if k.startswith("VW") or k == "Largest manager" else np.nan,
                   "unrealized p.a. %": d["unrealized"].mean() * 400 if k.startswith("VW") or k == "Largest manager" else np.nan,
                   "realized (cost) p.a. %": d["realized_cost"].mean() * 400 if k.startswith("VW") or k == "Largest manager" else np.nan,
                   "accretion p.a. %": d["accretion"].mean() * 400 if k.startswith("VW") or k == "Largest manager" else np.nan,
                   "vol p.a. %": t.std() * 200, "worst quarter %": t.min() * 100,
                   "autocorr(1)": t.autocorr(1)}
    return pd.DataFrame(rows).T


def credit_barometer(pos: pd.DataFrame, ix: dict[str, pd.DataFrame], largest: str, start: str) -> pd.DataFrame:
    """Credit health barometer per quarter-end: non-accrual share (coupon zero), share marked below 90, PIK share,
    amended PIK (PIK newly flagged while marked below 96 and still paying), weighted by par and by estimated cost,
    for all positions and without the largest manager; trailing four-quarter realized and unrealized returns of
    the value-weighted index."""
    pp = pos.sort_values(["FUND_KEY", "borrower", "month_end"]).copy()
    pp["pik_b"] = as_bool(pp["pik"]) if pp["pik"].dtype == object else pp["pik"].fillna(0).astype(float) > 0
    prev_pik = pp.groupby(["FUND_KEY", "borrower"])["pik_b"].shift(1)
    prev_q = pp.groupby(["FUND_KEY", "borrower"])["month_end"].shift(1)
    pp["amended_pik"] = (pp["pik_b"] & prev_pik.eq(False) & prev_q.eq(pp["month_end"] - pd.offsets.QuarterEnd(1))
                         & (pp["price"] < 96) & (pp["coupon"].fillna(0) > 0.01))
    pp["non_accrual"] = pp["coupon"].fillna(0).le(0.01)
    pp["below90"] = pp["price"] < 90

    def barometer(df: pd.DataFrame, w: str = "par") -> pd.DataFrame:
        tot = df.groupby("month_end")[w].sum()
        share = lambda m: df[m].groupby("month_end")[w].sum().reindex(tot.index, fill_value=0) / tot * 100
        return pd.DataFrame({f"non-accrual % {w}": share(df["non_accrual"]), f"marked < 90 % {w}": share(df["below90"]),
                             f"PIK % {w}": share(df["pik_b"]), f"amended PIK % {w}": share(df["amended_pik"])})

    sel = pp["month_end"] > pd.Timestamp(start) - pd.offsets.QuarterEnd(1)
    bar = barometer(pp[sel])
    vw = ix["VW all"]
    bar["T4Q realized % (VW)"] = vw["realized"].rolling(4).sum() * 100
    bar["T4Q unrealized % (VW)"] = vw["unrealized"].rolling(4).sum() * 100
    bc = barometer(pp[sel], "cost")
    bar["non-accrual % cost"], bar["marked < 90 % cost"] = bc["non-accrual % cost"], bc["marked < 90 % cost"]
    bar["T4Q realized (cost) % (VW)"] = vw["realized_cost"].rolling(4).sum() * 100
    bar_ex = barometer(pp[sel & (pp["manager"] != largest)], "cost")
    bar["non-accrual % cost (ex largest)"] = bar_ex["non-accrual % cost"]
    bar["marked < 90 % cost (ex largest)"] = bar_ex["marked < 90 % cost"]
    return bar


def dimson(y: pd.Series, x: pd.Series, lags: int = 2) -> dict:
    df = pd.concat([y.rename("y")] + [x.shift(k).rename(f"x{k}") for k in range(lags + 1)], axis=1, sort=True).dropna()
    if len(df) < 8:
        return {}
    m = sm.OLS(df["y"], sm.add_constant(df.drop(columns="y"))).fit()
    out = {f"beta_t-{k}": m.params[f"x{k}"] for k in range(lags + 1)}
    out["dimson_beta"] = sum(out.values())
    out["corr_t"] = df["y"].corr(df["x0"])
    out["n"] = len(df)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Direct lending returns and indices")
    ap.add_argument("--dir", default="dl_out")
    ap.add_argument("--start", default="2021-12-31", help="first quarter-end of the index (first return: next quarter)")
    ap.add_argument("--min-positions", type=int, default=10)
    ap.add_argument("--max-abs-return", type=float, default=0.5, help="drop position returns beyond this (data errors)")
    ap.add_argument("--distressed", default="recovery", choices=["recovery", "haircut"],
                    help="recovery: data-based recovery for default-like exits (default); haircut: fixed haircut")
    ap.add_argument("--recovery", type=float, default=None,
                    help="recovery in %% of par (default: estimated from the data)")
    ap.add_argument("--distress-price", type=float, default=80.0,
                    help="exits with a last mark below this count as default-like")
    ap.add_argument("--distressed-haircut", default="0",
                    help="with --distressed haircut: loss relative to the last mark (e.g. 0, 0.3); 'drop' leaves them out")
    ap.add_argument("--cdli", default=None)
    ap.add_argument("--cdli-annual", default=None,
                    help="CSV with columns year, total and optionally income, realized_loss (in %)")
    ap.add_argument("--ll-release", default=None)
    args = ap.parse_args()
    d = Path(args.dir)
    pd.set_option("display.width", 220)

    pos = pd.read_parquet(d / "dl_positions.parquet")
    pos["month_end"] = pd.to_datetime(pos["month_end"])
    pos = pos[pos["price"].between(1, 150)]
    pos = add_cost_basis(pos)
    hc = None if str(args.distressed_haircut).lower() == "drop" else float(args.distressed_haircut)
    rec = None
    if args.distressed == "recovery":
        rec = args.recovery if args.recovery is not None else estimate_recovery(pos)
    ret = position_returns(pos, hc, rec, args.distress_price)
    n0 = len(ret)
    # exits and loans in default or non-accrual keep their (loss) returns; other extreme returns are data errors
    ret = ret[ret["exit"] | ret["distress"] | (ret["total"].abs() <= args.max_abs_return)]
    print(f"Position returns: {n0:,}; dropped as |return| > {args.max_abs_return:.0%} "
          f"(not exits, not in default or non-accrual): {n0 - len(ret):,}")
    ret = ret[ret["month_end"] > pd.Timestamp(args.start)]
    largest = ret.groupby("manager")["v0"].sum().idxmax()
    print(f"Largest manager: {largest}")

    ix = build_indices(ret, args.min_positions, largest)
    for k, v in ix.items():
        v.to_csv(d / f"index_{k.replace(' ', '_').lower()}.csv")
    ret.to_parquet(d / "dl_position_returns.parquet", index=False)

    print("\n=== Index summary ===")
    print(summary(ix).round(2).to_string())
    print("\n=== Quarterly total returns (%) ===")
    tab = pd.DataFrame({k: v["total"] * 100 for k, v in ix.items()})
    tab["managers (EW)"] = ix["EW managers"]["managers"]
    tab["positions"] = ix["VW all"]["positions"]
    print(tab.round(2).to_string())
    print("\n=== Correlation of quarterly total returns ===")
    print(tab.drop(columns=["managers (EW)", "positions"]).corr().round(2).to_string())

    if args.cdli:
        c = pd.read_csv(args.cdli, parse_dates=["quarter"]).set_index("quarter").sort_index()
        c.index = c.index + pd.offsets.QuarterEnd(0)
        print("\n=== Comparison with the Cliffwater Direct Lending Index (CDLI) ===")
        rows = {}
        for k, v in ix.items():
            j = pd.concat([v[["total", "income", "price_ret"]] * 100, c[["total", "income", "price"]].add_prefix("cdli_")],
                          axis=1, sort=True)
            r = {}
            for mine, theirs, lab in [("total", "cdli_total", "total"), ("income", "cdli_income", "income"),
                                      ("price_ret", "cdli_price", "price")]:
                jj = j[[mine, theirs]].dropna()
                r[f"n {lab}"] = len(jj)
                r[f"corr {lab}"] = jj[mine].corr(jj[theirs]) if len(jj) >= 4 else np.nan
                r[f"diff {lab} (pp/q)"] = (jj[mine] - jj[theirs]).mean() if len(jj) else np.nan
            rows[k] = r
        print(pd.DataFrame(rows).T.round(2).to_string())
        tq = pd.concat([ix["EW managers"]["total"].rename("EW managers") * 100, ix["VW all"]["total"].rename("VW all") * 100,
                        c["total"].rename("CDLI")], axis=1, sort=True).dropna()
        print("\nQuarterly total returns (%), common quarters:")
        print(tq.round(2).to_string())
    if args.cdli_annual:
        ca = pd.read_csv(args.cdli_annual).set_index("year")
        rows = {}
        for k in ["EW managers", "VW all", "VW ex largest", "Largest manager"]:
            t = ix[k]["total"]
            full = t.groupby(t.index.year).filter(lambda x: len(x) == 4)
            rows[k] = ((1 + full).groupby(full.index.year).prod() - 1) * 100
        an = pd.DataFrame(rows).join(ca["total"].rename("CDLI"), how="inner")
        print("\n=== Calendar-year total returns (%) vs. CDLI ===")
        print(an.round(2).to_string())
        comp = []
        for k in ["VW all", "VW ex largest"]:
            dd = ix[k]
            full = dd[dd.groupby(dd.index.year)["total"].transform("size") == 4]
            y = full.groupby(full.index.year)[["income", "accretion", "realized", "realized_cost", "unrealized_cost"]].sum() * 100
            y.columns = [f"{c} ({k})" for c in y.columns]
            comp.append(y)
        cmp_ = pd.concat(comp, axis=1)
        for c in ["income", "realized_loss"]:
            if c in ca.columns:
                cmp_[f"CDLI {c}"] = ca[c].reindex(cmp_.index) * (-1 if c == "realized_loss" else 1)
        print("\n=== Calendar-year components (%, sums of quarters) vs. CDLI (realized loss shown negative) ===")
        print(cmp_.dropna(how="all").round(2).T.to_string())

    bar = credit_barometer(pos, ix, largest, args.start)
    bar.to_csv(d / "credit_health_barometer.csv")
    print("\n=== Credit health barometer (registered direct lending funds) ===")
    print(bar.round(2).to_string())

    if args.ll_release:
        fr = pd.read_csv(Path(args.ll_release) / "factor_returns.csv", parse_dates=["date"])
        mkt = fr.query("portfolio == 'MKT' and weighting == 'ew' and holding == 1 and lag == 0 "
                       "and return_type == 'total'").drop_duplicates("date").set_index("date")["ret"].sort_index()
        llq = (1 + mkt).groupby(mkt.index + pd.offsets.QuarterEnd(0)).prod() - 1
        print("\n=== Delayed valuation: regression on the leveraged loan market (quarterly, t, t-1, t-2) ===")
        print(pd.DataFrame({k: dimson(v["total"], llq) for k, v in ix.items()}).T.round(3).to_string())
    print(f"\nSaved: {d}/index_*.csv, {d / 'dl_position_returns.parquet'}")


if __name__ == "__main__":
    main()
