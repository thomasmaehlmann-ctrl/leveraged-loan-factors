#!/usr/bin/env python3
"""
bdc_tracking.py

Diagnostics: which BDCs lose track of their European positions from one quarter-end to the next, and how do the
identifiers change?

For every BDC and pair of consecutive calendar quarter-ends, the script reports the share of European-currency
positions found again (same position key and currency). For positions not found again, it looks for the most
similar key of the same BDC and currency in the next quarter (string similarity) and prints examples, so that the
normalization of the identifiers can be improved.

Input   bdc_out/bdc_positions.parquet (bdc_panel.py)
Output  bdc_out/tracking_by_bdc.csv, bdc_out/unmatched_examples.csv

Usage
    python bdc_tracking.py
"""

import argparse
import difflib
from pathlib import Path

import pandas as pd


def main() -> None:
    ap = argparse.ArgumentParser(description="Tracking diagnostics for BDC positions")
    ap.add_argument("--dir", default="bdc_out")
    ap.add_argument("--all-currencies", action="store_true", help="all debt positions, not only European currencies")
    args = ap.parse_args()
    d = Path(args.dir)
    pd.set_option("display.width", 220)
    pd.set_option("display.max_colwidth", 90)

    p = pd.read_parquet(d / "bdc_positions.parquet")
    p = p[p["dl_bdc"] & p["month_end"].dt.month.isin([3, 6, 9, 12])]
    if not args.all_currencies:
        p = p[p["eu_ccy"]]
    qs = sorted(p["month_end"].unique())
    rows, ex = [], []
    for a, b in zip(qs[:-1], qs[1:]):
        A, B = p[p["month_end"] == a], p[p["month_end"] == b]
        for (cik, name), g in A.groupby(["cik", "name"]):
            nb = B[B["cik"] == cik]
            if nb.empty:
                continue
            keys_b = set(zip(nb["key"], nb["ccy"]))
            found = [(k, c) in keys_b for k, c in zip(g["key"], g["ccy"])]
            rows.append({"quarter": pd.Timestamp(a).date(), "name": name, "positions": len(g),
                         "found_next": sum(found), "share": sum(found) / len(g), "fv_usd_mn": g["fv_usd"].sum() / 1e6})
            for (k, c, fv, ident), f in zip(g[["key", "ccy", "fv_usd", "ident"]].itertuples(index=False, name=None), found):
                if f:
                    continue
                cand = nb.loc[nb["ccy"] == c, "key"].tolist()
                best = difflib.get_close_matches(k, cand, n=1, cutoff=0.0)
                ratio = difflib.SequenceMatcher(None, k, best[0]).ratio() if best else 0.0
                ex.append({"quarter": pd.Timestamp(a).date(), "name": name, "ccy": c, "fv_usd_mn": fv / 1e6,
                           "key": k, "best_next_key": best[0] if best else "", "similarity": round(ratio, 2),
                           "ident": ident})
    t = pd.DataFrame(rows)
    e = pd.DataFrame(ex)
    t.to_csv(d / "tracking_by_bdc.csv", index=False)
    e.to_csv(d / "unmatched_examples.csv", index=False)

    tot = t.groupby("quarter")[["positions", "found_next"]].sum()
    tot["share"] = tot["found_next"] / tot["positions"]
    print("=== Tracking by quarter ===")
    print(tot.round(3).to_string())
    print("\n=== BDC-quarters with the most positions not found again ===")
    t["lost"] = t["positions"] - t["found_next"]
    print(t.sort_values("lost", ascending=False).head(25).round(3).to_string(index=False))
    if len(e):
        print("\n=== Lost positions with a similar key in the next quarter (similarity >= 0.8): "
              f"{(e['similarity'] >= 0.8).mean():.0%} of {len(e):,} ===")
        print("\nExamples from the BDCs with the most lost positions:")
        top = t.sort_values("lost", ascending=False).head(6)
        for _, r in top.iterrows():
            ee = e[(e["name"] == r["name"]) & (e["quarter"] == r["quarter"])].head(4)
            print(f"\n{r['name']} {r['quarter']}  (lost {int(r['lost'])} of {int(r['positions'])})")
            for _, x in ee.iterrows():
                print(f"   now : {x['key'][:110]}")
                print(f"   next: {x['best_next_key'][:110]}   [{x['similarity']}]")
    print(f"\nSaved: {d}/tracking_by_bdc.csv, {d}/unmatched_examples.csv")


if __name__ == "__main__":
    main()
