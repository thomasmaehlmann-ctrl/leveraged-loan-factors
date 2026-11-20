#!/usr/bin/env python3
"""
eu_exits.py

Are low last valuations before an exit genuine? A cross-check with other BDCs.

For every exit of the European index whose last valuation lies between --low and --high (default 80 and 95) and
that is not in default, the script looks for the same borrower in other BDCs at the same quarter-end (matching
the distinctive words of the position keys, as in bdc_link.py) and compares the valuations. Only BDCs of other
managers count, because BDCs of the same manager are valued by the same team (--same-manager to include them):

    artifact   other BDCs value the borrower at least 3 points higher and at 97 or more: the low value is
               most likely a reporting artifact (e.g. a partially drawn tranche), not a markdown
    genuine    other BDCs value the borrower within 3 points of the exiting BDC: a real markdown
    other      other BDCs value it lower, or between the two cases
    unmatched  no other BDC holds the borrower

The same check is applied to exits valued at 95 or more (control group) and to positions that continue
(valued between --low and --high, not exiting), to see whether exits differ from continuing positions.

Input   bdc_out/bdc_positions.parquet, eu_out/eu_position_returns.parquet
Output  eu_out/exit_crosscheck.csv

Usage
    python eu_exits.py
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

import bdc_link as bl


def classify(p0: float, others: list[float]) -> str:
    if not others:
        return "unmatched"
    med = float(np.median(others))
    if med >= 97 and med - p0 >= 3:
        return "artifact"
    if abs(med - p0) < 3:
        return "genuine"
    return "other"


def main() -> None:
    ap = argparse.ArgumentParser(description="Cross-check of low valuations before exits")
    ap.add_argument("--dir", default="bdc_out")
    ap.add_argument("--eu-dir", default="eu_out")
    ap.add_argument("--low", type=float, default=80.0)
    ap.add_argument("--high", type=float, default=95.0)
    ap.add_argument("--same-manager", action="store_true",
                    help="also compare with other BDCs of the same manager (not independent valuations)")
    args = ap.parse_args()
    pd.set_option("display.width", 200)

    p = pd.read_parquet(Path(args.dir) / "bdc_positions.parquet")
    p = p[p["dl_bdc"] & p["eu_ccy"] & p["month_end"].dt.month.isin([3, 6, 9, 12]) & p["price"].between(1, 150)]
    p = p[~p["instrument"].isin(["bond", "equipment", "revolver", "delayed_draw"])].copy()
    p["dist"] = bl.distinctive(p[["cik", "month_end", "key"]].reset_index(drop=True)).to_numpy()
    p["cik"] = p["cik"].astype(str)
    by_q = {q: g[["cik", "key", "ccy", "price", "dist", "manager"]].to_numpy() for q, g in p.groupby("month_end")}
    mgr_of = dict(zip(p["cik"], p["manager"]))
    look = {(c, q, k, y): d for c, q, k, y, d in zip(p["cik"], p["month_end"], p["key"], p["ccy"], p["dist"])}

    r = pd.read_parquet(Path(args.eu_dir) / "eu_position_returns.parquet")
    r["prev_q"] = r["month_end"] - pd.offsets.QuarterEnd(1)
    r["key"] = r["borrower"].str.rsplit("|", n=1).str[0]
    r["ccy"] = r["borrower"].str.rsplit("|", n=1).str[1]

    def others_marks(row) -> list[float]:
        d0 = look.get((str(row["FUND_KEY"]), row["prev_q"], row["key"], row["ccy"]))
        if not d0:
            return []
        out = []
        own = mgr_of.get(str(row["FUND_KEY"]))
        for c, k, y, price, d1, m in by_q.get(row["prev_q"], []):
            if c == str(row["FUND_KEY"]) or not d1 or (not args.same_manager and m == own):
                continue
            if len(d0 & d1) / min(len(d0), len(d1)) >= 0.75:
                out.append(price)
        return out

    groups = {
        f"exits, last valuation {args.low:g}-{args.high:g}": r["exit"] & r["p0"].between(args.low, args.high, inclusive="left"),
        f"exits, last valuation >= {args.high:g}": r["exit"] & r["p0"].ge(args.high),
        f"continuing, valuation {args.low:g}-{args.high:g}": ~r["exit"] & r["p0"].between(args.low, args.high, inclusive="left"),
    }
    rows, detail = [], []
    for name, m in groups.items():
        sub = r[m].copy()
        sub["others"] = sub.apply(others_marks, axis=1)
        sub["class"] = [classify(a, b) for a, b in zip(sub["p0"], sub["others"])]
        sub["others_median"] = sub["others"].map(lambda x: float(np.median(x)) if x else np.nan)
        sub["group"] = name
        shares = sub["class"].value_counts(normalize=True)
        matched = sub[sub["class"] != "unmatched"]
        rows.append({"group": name, "n": len(sub), "matched": len(matched),
                     **{f"{c} (of matched)": (matched["class"] == c).mean() if len(matched) else np.nan
                        for c in ["artifact", "genuine", "other"]},
                     "median last value": sub["p0"].median(),
                     "median value at other BDCs": matched["others_median"].median()})
        detail.append(sub)
    t = pd.DataFrame(rows).set_index("group")
    print("=== Valuations of the same borrower at other BDCs, same quarter-end ===")
    print(t.round(2).to_string())

    d = pd.concat(detail)
    d.drop(columns=["others"]).to_csv(Path(args.eu_dir) / "exit_crosscheck.csv", index=False)
    ex = d[d["group"].str.startswith("exits, last valuation") & ~d["group"].str.contains(">=")]
    print("\n=== Exits with low last valuation: classification by manager ===")
    print(pd.crosstab(ex["manager"], ex["class"], margins=True).to_string())
    print("\nExamples (artifact):")
    print(ex[ex["class"] == "artifact"][["month_end", "manager", "key", "p0", "others_median"]].head(12)
          .assign(key=lambda x: x["key"].str[:60]).round({"p0": 2, "others_median": 2}).to_string(index=False))
    print("\nExamples (genuine):")
    print(ex[ex["class"] == "genuine"][["month_end", "manager", "key", "p0", "others_median"]].head(8)
          .assign(key=lambda x: x["key"].str[:60]).round({"p0": 2, "others_median": 2}).to_string(index=False))
    print(f"\nSaved: {args.eu_dir}/exit_crosscheck.csv")


if __name__ == "__main__":
    main()
