#!/usr/bin/env python3
"""
momentum_by_price.py

Tests whether momentum depends on the upside of a loan: momentum sorted separately among loans
trading below par and loans trading near or above par (dependent sort at formation).

Hypothesis (Section 5.5): loans near par can be repriced or refinanced when their credit quality
improves, so winners have little upside. Momentum should therefore remain profitable among loans
below par, also in 2023 to 2026, when most loans traded at par.

For each price group (threshold 99 and, as robustness, 100), holding period (1 and 6 months),
implementation lag (0 and 1) and period (full sample, 2019-2022, 2023-2026):
    Dimson alpha of the momentum winner quintile against the group benchmark, long-short return,
    number of months and median number of loans in the group

Requirement: factor_portfolios.py in the same folder (or in ../pipeline).

Usage
    python momentum_by_price.py
"""

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from factor_portfolios import nw, portfolio_returns, stats

PERIODS = {"Full sample": (None, None), "2019–2022": (None, "2022-12"), "2023–2026": ("2023-01", None)}


def main() -> None:
    ap = argparse.ArgumentParser(description="Momentum among loans below and near par")
    ap.add_argument("--dir", default="nport_out")
    ap.add_argument("--out-dir", default="paper_results/momentum_by_price")
    ap.add_argument("--thresholds", default="99,100")
    args = ap.parse_args()

    df = pd.read_parquet(Path(args.dir) / "loan_characteristics_M.parquet")
    df["MONTH_END"] = pd.to_datetime(df["MONTH_END"])
    df = df.sort_values(["LOAN_KEY", "MONTH_END"]).reset_index(drop=True)
    uni = df["universe"].fillna(False).astype(bool)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    rows = []
    for thr in [float(t) for t in args.thresholds.split(",")]:
        groups = {f"below {thr:g}": df["price"] < thr, f"{thr:g} and above": df["price"] >= thr}
        for gname, mask in groups.items():
            d = df.copy()
            d["universe"] = uni & mask
            n_loans = d[d["universe"] & d["mom_3m_skip"].notna()].groupby("MONTH_END").size()
            for hold in (1, 6):
                for lag in (0, 1):
                    pr = portfolio_returns(d, "mom_3m_skip", 5, 1, hold, "ret", lag, "ew")
                    if pr.empty or 5 not in pr or 1 not in pr:
                        continue
                    for pname, (start, end) in PERIODS.items():
                        p = pr
                        if start:
                            p = p[p.index >= pd.Timestamp(start) + pd.offsets.MonthEnd(0)]
                        if end:
                            p = p[p.index <= pd.Timestamp(end) + pd.offsets.MonthEnd(0)]
                        p = p.dropna(subset=[5, 1, "BM"])
                        if len(p) < 18:
                            continue
                        s = stats(p[5], p["BM"], 12, 3)
                        ls = p[5] - p[1]
                        rows.append({
                            "threshold": thr, "group": gname, "holding": hold, "lag": lag, "period": pname,
                            "months": len(p), "median_loans": n_loans.reindex(p.index - pd.offsets.MonthEnd(1)).median(),
                            "dimson_alpha_bp": s["Dimson alpha p.a. (bp)"], "t_dimson": s["t Dimson alpha"],
                            "ls_bp": ls.mean() * 1.2e5, "t_ls": nw(ls, None, 3).tvalues[0],
                        })
    res = pd.DataFrame(rows)
    res.to_csv(out / "momentum_by_price.csv", index=False)

    pd.set_option("display.width", 200)
    res["cell"] = [f"{a:.0f} ({t:.2f})" for a, t in zip(res["dimson_alpha_bp"], res["t_dimson"])]
    res["ls_cell"] = [f"{a:.0f} ({t:.2f})" for a, t in zip(res["ls_bp"], res["t_ls"])]
    for thr, g in res.groupby("threshold"):
        print(f"\n=== Threshold {thr:g}: Dimson alpha of the winner quintile, bp p.a. (t) ===")
        tab = g.pivot_table(index=["group", "holding", "lag"], columns="period", values="cell", aggfunc="first")
        print(tab[[c for c in PERIODS if c in tab.columns]].to_string())
        print(f"\n=== Threshold {thr:g}: long-short (winners minus losers), bp p.a. (t) ===")
        tab = g.pivot_table(index=["group", "holding", "lag"], columns="period", values="ls_cell", aggfunc="first")
        print(tab[[c for c in PERIODS if c in tab.columns]].to_string())
        print("\nMedian loans per month in each group (holding 1, lag 0):")
        print(g[(g["holding"] == 1) & (g["lag"] == 0)].pivot_table(index="group", columns="period",
                                                                   values="median_loans").round(0).to_string())

    # share of universe loans below each threshold by year
    u = df[uni]
    share = pd.DataFrame({f"share below {t}": (u["price"] < float(t)).groupby(u["MONTH_END"].dt.year).mean()
                          for t in args.thresholds.split(",")})
    print("\nShare of universe loans below the threshold, by year:")
    print(share.map("{:.0%}".format).to_string())
    share.to_csv(out / "share_below_par.csv")
    print(f"\nSaved in: {out}")


if __name__ == "__main__":
    main()
