#!/usr/bin/env python3
"""
bdc_samples.py

Sample of position identifiers from BDC schedules of investments, as material for developing the parser
(borrower, instrument, currency, country, subtotals).

For the largest BDCs (by number of tagged holdings) the script draws random holdings from the latest filing in
the data set, always including the BDC's European holdings and the holdings without a principal amount (where
subtotals are most likely), and writes them with fair value, cost, principal and its unit.

Usage
    python bdc_samples.py --zip 2025q2_notes.zip --top 40 --per-bdc 25
Output
    bdc_samples.csv
"""

import argparse

import numpy as np
import pandas as pd

import bdc_pilot as bp


def main() -> None:
    ap = argparse.ArgumentParser(description="Sample of BDC position identifiers")
    ap.add_argument("--zip", nargs="+", required=True)
    ap.add_argument("--top", type=int, default=40, help="number of BDCs (largest by number of holdings)")
    ap.add_argument("--per-bdc", type=int, default=25, help="random holdings per BDC")
    ap.add_argument("--out", default="bdc_samples.csv")
    args = ap.parse_args()

    d = pd.concat([bp.read_zip(bp.Path(z)) for z in args.zip])
    d["value"] = pd.to_numeric(d["value"], errors="coerce")
    d = d[d["ddate"] == d.groupby("adsh")["ddate"].transform("max")]
    key = ["adsh", "cik", "name", "segments"]
    w = d.pivot_table(index=key, columns="tag", values="value", aggfunc="first").rename(columns=bp.TAGS).reset_index()
    for c in bp.TAGS.values():
        if c not in w:
            w[c] = np.nan
    unit = d[d["tag"] == "InvestmentOwnedBalancePrincipalAmount"].groupby(key)["uom"].first().rename("principal_unit")
    w = w.merge(unit, left_on=key, right_index=True, how="left")
    w = w[w["adsh"] == w.groupby("cik")["adsh"].transform("max")]
    w["ident"] = w["segments"].str.extract(bp.IDENT_RE, expand=False).fillna("")
    w["other_dims"] = w["segments"].str.replace(bp.IDENT_RE, "", regex=True).str.strip(";")
    u = w["principal_unit"].fillna("").str.upper()
    w["european"] = (u.isin(bp.EUR_CCY) | w["segments"].str.contains(bp.CTRY_RE) | w["ident"].str.contains(bp.CCY_RE)) \
        & ~(~u.isin(bp.EUR_CCY | {"USD", ""}))

    big = w.groupby("name").size().sort_values(ascending=False).head(args.top).index
    out = []
    for n in big:
        g = w[w["name"] == n]
        pick = pd.concat([g[g["european"]].head(10), g[g["principal"].isna()].head(5),
                          g.sample(min(args.per_bdc, len(g)), random_state=7)]).drop_duplicates("segments")
        out.append(pick)
    s = pd.concat(out)[["name", "ident", "other_dims", "principal_unit", "principal", "fv", "cost", "rate", "european"]]
    s.to_csv(args.out, index=False)
    print(f"Saved {len(s):,} identifiers from {len(big)} BDCs to {args.out}")


if __name__ == "__main__":
    main()
