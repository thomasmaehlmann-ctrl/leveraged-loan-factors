#!/usr/bin/env python3
"""
dl_robustness.py

Robustness checks and desmoothing for the direct lending index (uses the functions of dl_index.py).

Robustness: each variant changes one choice of the main specification and reports, for the main index
(EW managers) and the value-weighted index (VW all): return p.a. with income and price components,
volatility, comparison with the CDLI (correlation, mean difference per quarter, calendar-year differences)
and the Dimson beta on the leveraged loan market.

    base                 min. 10 positions per manager, repayment threshold 95, default-like below 80,
                         recovery estimated from the data
    min positions 5/20   managers in the EW index
    repayment 97/90      threshold for assumed repayment at par
    distress 70/90       mark below which an exit counts as default-like
    recovery 60/50       fixed recovery instead of the data-based estimate
    interval funds only  positions of interval funds (Form N-CEN)
    start 2022-12        index from 2023 (later start, broader manager base)

Desmoothing: fair values react to market changes gradually. Following Geltner (1993), the observed price
return is treated as r_obs(t) = (1 - a) r(t) + a r_obs(t-1), so that r(t) = (r_obs(t) - a r_obs(t-1)) / (1 - a),
with a estimated as the first-order autocorrelation of the price return. Only the price component is
desmoothed; the income return is an accrual and is added back unchanged. The output compares volatility,
worst quarter and beta on the leveraged loan market before and after desmoothing.

Usage
    python dl_robustness.py --cdli cdli_quarterly_clean.csv --cdli-annual cdli_annual_returns_components.csv
                            --ll-release releases/loanfactors_v2026.12
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

import dl_index as di


def run(pos: pd.DataFrame, start: str, min_pos: int, repay: float, distress: float, recovery: float | None,
        max_abs: float = 0.5) -> dict[str, pd.DataFrame]:
    di.REPAY_MIN_PRICE = repay
    rec = recovery if recovery is not None else di.estimate_recovery(pos)
    ret = di.position_returns(pos, 0.0, rec, distress)
    ret = ret[ret["exit"] | ret["distress"] | (ret["total"].abs() <= max_abs)]
    ret = ret[ret["month_end"] > pd.Timestamp(start)]
    largest = ret.groupby("manager")["v0"].sum().idxmax()
    return di.build_indices(ret, min_pos, largest)


def stats(ix: pd.DataFrame, cdli: pd.Series | None, cdli_y: pd.Series | None, llq: pd.Series | None) -> dict:
    t = ix["total"]
    out = {"total p.a.": ((1 + t).prod() ** (4 / len(t)) - 1) * 100, "income p.a.": ix["income"].mean() * 400,
           "price p.a.": ix["price_ret"].mean() * 400, "vol p.a.": t.std() * 200}
    if cdli is not None:
        j = pd.concat([t * 100, cdli], axis=1, sort=True).dropna()
        out["corr CDLI"] = j.iloc[:, 0].corr(j.iloc[:, 1])
        out["diff CDLI pp/q"] = (j.iloc[:, 0] - j.iloc[:, 1]).mean()
    if cdli_y is not None:
        full = t.groupby(t.index.year).filter(lambda x: len(x) == 4)
        yr = ((1 + full).groupby(full.index.year).prod() - 1) * 100
        d = (yr - cdli_y.reindex(yr.index)).dropna()
        out["mean |diff| CDLI p.a."] = d.abs().mean()
    if llq is not None:
        dm = di.dimson(t, llq)
        out["Dimson beta LL"] = dm.get("dimson_beta", np.nan)
    return out


def desmooth(ix: pd.DataFrame) -> tuple[pd.Series, float]:
    p = ix["price_ret"]
    a = p.autocorr(1)
    a = float(np.clip(a, 0, 0.9)) if a == a else 0.0
    p_true = (p - a * p.shift(1)) / (1 - a)
    p_true.iloc[0] = p.iloc[0]
    return ix["income"] + p_true, a


def main() -> None:
    ap = argparse.ArgumentParser(description="Robustness and desmoothing of the direct lending index")
    ap.add_argument("--dir", default="dl_out")
    ap.add_argument("--start", default="2021-12-31")
    ap.add_argument("--cdli", default=None)
    ap.add_argument("--cdli-annual", default=None)
    ap.add_argument("--ll-release", default=None)
    args = ap.parse_args()
    pd.set_option("display.width", 220)

    pos = pd.read_parquet(Path(args.dir) / "dl_positions.parquet")
    pos["month_end"] = pd.to_datetime(pos["month_end"])
    pos = pos[pos["price"].between(1, 150)]

    cdli = cdli_y = llq = None
    if args.cdli:
        c = pd.read_csv(args.cdli, parse_dates=["quarter"]).set_index("quarter").sort_index()
        c.index = c.index + pd.offsets.QuarterEnd(0)
        cdli = c["total"]
    if args.cdli_annual:
        cdli_y = pd.read_csv(args.cdli_annual).set_index("year")["total"]
    if args.ll_release:
        fr = pd.read_csv(Path(args.ll_release) / "factor_returns.csv", parse_dates=["date"])
        mkt = fr.query("portfolio == 'MKT' and weighting == 'ew' and holding == 1 and lag == 0 "
                       "and return_type == 'total'").drop_duplicates("date").set_index("date")["ret"].sort_index()
        llq = (1 + mkt).groupby(mkt.index + pd.offsets.QuarterEnd(0)).prod() - 1

    rec_hat = di.estimate_recovery(pos)
    variants = {
        "base": dict(), "min positions 5": dict(min_pos=5), "min positions 20": dict(min_pos=20),
        "repayment 97": dict(repay=97.0), "repayment 90": dict(repay=90.0),
        "distress 70": dict(distress=70.0), "distress 90": dict(distress=90.0),
        "recovery 60": dict(recovery=60.0), "recovery 50": dict(recovery=50.0),
        "interval funds only": dict(interval=True), "start 2022-12": dict(start="2022-12-31"),
    }
    rows, base_ix = [], None
    for name, v in variants.items():
        p = pos
        if v.get("interval"):
            if "interval_fund" not in pos.columns:
                print("Note: no interval_fund column; rerun dl_panel.py with ncen_advisers.csv")
                continue
            p = pos[pos["interval_fund"].astype(str).str.upper().isin(["TRUE", "Y", "1"])]
        print(f"\n--- {name} ---")
        ix = run(p, v.get("start", args.start), v.get("min_pos", 10), v.get("repay", 95.0),
                 v.get("distress", 80.0), v.get("recovery", rec_hat))
        if name == "base":
            base_ix = ix
        for idx in ["EW managers", "VW all"]:
            if idx in ix and len(ix[idx]) >= 8:
                rows.append({"variant": name, "index": idx, **stats(ix[idx], cdli, cdli_y, llq)})
    res = pd.DataFrame(rows).set_index(["variant", "index"])
    res.to_csv(Path(args.dir) / "robustness.csv")
    print("\n=== Robustness (returns and differences in %) ===")
    print(res.round(2).to_string())

    # desmoothing of the base specification
    print("\n=== Desmoothing (Geltner, price component only), base specification ===")
    rows = {}
    for idx in ["EW managers", "VW all"]:
        d = base_ix[idx]
        obs = d["total"]
        true, a = desmooth(d)
        r = {"smoothing a": a, "vol obs p.a.": obs.std() * 200, "vol desmoothed p.a.": true.std() * 200,
             "worst q obs": obs.min() * 100, "worst q desmoothed": true.min() * 100}
        if llq is not None:
            for lab, s in [("obs", obs), ("desmoothed", true)]:
                j = pd.concat([s, llq], axis=1, sort=True).dropna()
                b = np.polyfit(j.iloc[:, 1], j.iloc[:, 0], 1)[0]
                r[f"beta LL {lab}"] = b
                r[f"corr LL {lab}"] = j.iloc[:, 0].corr(j.iloc[:, 1])
            r["vol LL p.a."] = llq.loc[obs.index.min():obs.index.max()].std() * 200
        rows[idx] = r
        out = pd.DataFrame({"observed": obs * 100, "desmoothed": true * 100})
        out.to_csv(Path(args.dir) / f"desmoothed_{idx.replace(' ', '_').lower()}.csv")
    print(pd.DataFrame(rows).T.round(3).to_string())
    print(f"\nSaved: {Path(args.dir) / 'robustness.csv'}, {Path(args.dir)}/desmoothed_*.csv")


if __name__ == "__main__":
    main()
