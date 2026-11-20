#!/usr/bin/env python3
"""
eu_loanlevel.py

Loan-level validation of OpenDL Europe.

Part A  Same loan, different managers (BDC data): pairs of BDCs of different managers that hold the same borrower
        in the same currency at the same quarter-end (matched by the distinctive words of the position keys).
        Agreement of valuations by price bucket, agreement of quarterly changes, and the deviation of each manager
        from the other managers holding the same loans (as dl_crossmanager.py for the US index).

Part B  Same loan, two data sources: European direct loans of US registered funds (Form N-PORT, nport_loans.py
        --europe) matched to the same borrowers in BDC filings (XBRL) at the same quarter-end and currency. This is
        an independent check of the data processing (currencies, exchange rates, keys) and of the valuations,
        separately for the same manager (registered fund and BDC of one adviser) and different managers.

Inputs
    bdc_out/bdc_positions.parquet                       (BDC panel, bdc_panel.py + bdc_link.py)
    <nport-dir>/holdings_v2                             (nport_loans.py --europe)
    <ncen-dir>/ncen_advisers.csv, ncen_advisers_by_cik.csv   (optional, managers of the registered funds)
Output
    eu_out/loanlevel_pairs_bdc.csv, eu_out/loanlevel_pairs_nport_bdc.csv

Usage
    python eu_loanlevel.py --nport-dir "..\\Loan Fund Data\\nport_out_eu" --ncen-dir "..\\Loan Fund Data\\dl_out"
"""

import argparse
import re
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

import bdc_link as bl
import bdc_panel as bpanel

EU_CCY = bpanel.EU_CCY
BUCKETS = [0, 80, 90, 95, 98, 200]
LABELS = ["< 80", "80-90", "90-95", "95-98", ">= 98"]


def name_tokens(s: str) -> frozenset:
    s = re.sub(r"[^A-Za-z0-9 ]", " ", str(s).upper())
    return frozenset(t for t in s.split() if len(t) > 1 and t not in bl.STOP and not t.isdigit())


def overlap(a: frozenset, b: frozenset) -> float:
    return len(a & b) / min(len(a), len(b)) if a and b else 0.0


def agreement(df: pd.DataFrame, p1: str, p2: str) -> pd.DataFrame:
    df = df.assign(absdiff=(df[p1] - df[p2]).abs(),
                   bucket=pd.cut(df[[p1, p2]].mean(axis=1), BUCKETS, labels=LABELS, right=False))
    f = lambda g: pd.Series({"pairs": len(g), "mean_abs_diff": g["absdiff"].mean(),
                             "median_abs_diff": g["absdiff"].median(), "within_1pt": (g["absdiff"] <= 1).mean(),
                             "within_2pt": (g["absdiff"] <= 2).mean()})
    allrow = f(df).to_frame("all").T
    by = df.groupby("bucket", observed=True)[["absdiff"]].apply(f)
    return pd.concat([allrow, by])


def main() -> None:
    ap = argparse.ArgumentParser(description="Loan-level validation of OpenDL Europe")
    ap.add_argument("--dir", default="bdc_out")
    ap.add_argument("--out-dir", default="eu_out")
    ap.add_argument("--nport-dir", default=None)
    ap.add_argument("--ncen-dir", default=None)
    ap.add_argument("--max-diff", type=float, default=20.0, help="pairs differing by more are treated as different instruments")
    args = ap.parse_args()
    out = Path(args.out_dir)
    out.mkdir(exist_ok=True)
    pd.set_option("display.width", 200)

    p = pd.read_parquet(Path(args.dir) / "bdc_positions.parquet")
    p = p[p["dl_bdc"] & p["eu_ccy"] & p["month_end"].dt.month.isin([3, 6, 9, 12]) & p["price"].between(1, 150)
          & ~p["instrument"].isin(["bond", "equipment", "revolver", "delayed_draw"])].copy()
    p = p[p["month_end"] >= "2023-03-31"].reset_index(drop=True)
    p["cik"] = p["cik"].astype(str)
    p["dist"] = bl.distinctive(p[["cik", "month_end", "key"]]).to_numpy()
    p["ntok"] = p["ident"].map(name_tokens)

    # ================= Part A: different managers, BDC data
    rows = []
    for (q, c), g in p.groupby(["month_end", "ccy"]):
        recs = g[["cik", "manager", "key", "price", "dist"]].to_numpy()
        for i in range(len(recs)):
            for j in range(i + 1, len(recs)):
                a, b = recs[i], recs[j]
                if a[1] == b[1] or not a[4] or not b[4]:
                    continue
                if overlap(a[4], b[4]) >= 0.75:
                    rows.append({"month_end": q, "ccy": c, "cik1": a[0], "m1": a[1], "key1": a[2], "p1": a[3],
                                 "cik2": b[0], "m2": b[1], "key2": b[2], "p2": b[3]})
    pa = pd.DataFrame(rows)
    if pa.empty:
        print("Part A: no pairs found")
    else:
        pa["absdiff"] = (pa["p1"] - pa["p2"]).abs()
        big = pa["absdiff"] > args.max_diff
        print(f"=== A. Same borrower, different managers (BDC data): {len(pa):,} pairs, "
              f"{pa[['m1', 'm2']].stack().nunique()} managers; {big.sum()} pairs differing by > {args.max_diff:g} points excluded ===")
        pa = pa[~big]
        print(agreement(pa, "p1", "p2").round(3).to_string())
        # changes: the same pair in consecutive quarters
        pa = pa.sort_values("month_end")
        k = ["cik1", "key1", "cik2", "key2"]
        pa["prev_q"] = pa["month_end"] - pd.offsets.QuarterEnd(1)
        prev = pa[k + ["month_end", "p1", "p2"]].rename(columns={"month_end": "prev_q", "p1": "p1_prev", "p2": "p2_prev"})
        ch = pa.merge(prev, on=k + ["prev_q"])
        ch["d1"], ch["d2"] = ch["p1"] - ch["p1_prev"], ch["p2"] - ch["p2_prev"]
        if len(ch) >= 10:
            dn = ch[(ch["d1"] <= -2) | (ch["d2"] <= -2)]
            print(f"\nQuarterly changes: correlation {ch['d1'].corr(ch['d2']):.2f} (n = {len(ch):,}); "
                  f"when one manager marks down by 2+ points, the other marks down by 1+ point in the same quarter "
                  f"in {((dn['d1'] <= -1) & (dn['d2'] <= -1)).mean():.0%} of cases (n = {len(dn)})")
        # deviation of each manager from the others on the same borrower
        long = pd.concat([pd.DataFrame({"month_end": pa["month_end"], "m": pa["m1"], "p": pa["p1"], "o": pa["p2"],
                                        "key1": pa["key1"]}),
                          pd.DataFrame({"month_end": pa["month_end"], "m": pa["m2"], "p": pa["p2"], "o": pa["p1"],
                                        "key1": pa["key2"]})], ignore_index=True)
        long["dev"] = long["p"] - long["o"]
        dev = long.groupby("m").agg(pairs=("dev", "size"), borrowers=("key1", "nunique"), mean_dev=("dev", "mean"),
                                    median_dev=("dev", "median"),
                                    share_higher=("dev", lambda x: (x > 0.25).mean()),
                                    share_lower=("dev", lambda x: (x < -0.25).mean()))
        bb = long.groupby(["m", "key1"])["dev"].mean().groupby("m")
        dev["t (borrower-clustered)"] = bb.mean() / (bb.std() / np.sqrt(bb.size()))
        print("\nDeviation of each manager from other managers on the same borrower (points; >= 20 pairs):")
        print(dev[dev["pairs"] >= 20].sort_values("mean_dev").round(2).to_string())
        pa.to_csv(out / "loanlevel_pairs_bdc.csv", index=False)

    # ================= Part B: N-PORT (registered funds) vs. BDC data
    if not args.nport_dir:
        print("\nPart B skipped (--nport-dir not given)")
        return
    src = f"read_parquet('{(Path(args.nport_dir) / 'holdings_v2').as_posix()}/**/*.parquet', union_by_name = true)"
    n = duckdb.connect().execute(f"""
        WITH h AS (SELECT * FROM {src}),
             latest AS (SELECT ACCESSION_NUMBER FROM (
                 SELECT ACCESSION_NUMBER, row_number() OVER (PARTITION BY FUND_KEY, REPORT_DATE
                        ORDER BY FILING_DATE DESC, ACCESSION_NUMBER DESC) AS rn
                 FROM (SELECT DISTINCT FUND_KEY, REPORT_DATE, ACCESSION_NUMBER, FILING_DATE FROM h)) WHERE rn = 1)
        SELECT FUND_KEY, SERIES_NAME, CAST(MONTH_END AS DATE) AS month_end, ISSUER_NAME, ISSUER_TITLE, KEY_TYPE, LOAN_KEY,
               upper(CURRENCY_CODE) AS ccy, EXCHANGE_RATE AS rate, CURRENCY_VALUE AS value_usd, BALANCE AS par,
               FAIR_VALUE_LEVEL AS fvl, IS_UNFUNDED_OR_REVOLVER AS unfunded
        FROM h WHERE ACCESSION_NUMBER IN (SELECT ACCESSION_NUMBER FROM latest)""").df()
    n["month_end"] = pd.to_datetime(n["month_end"])
    lk = n["LOAN_KEY"].fillna("").astype(str)
    placeholder = lk.map(lambda k: k.startswith("CUSIP:") and len(set(k[6:])) == 1)
    n = n[(n["KEY_TYPE"].eq("NM") | placeholder) & n["fvl"].astype(str).eq("3") & n["ccy"].isin(EU_CCY)
          & n["par"].ge(250_000) & ~n["unfunded"].fillna(False).astype(bool)
          & n["month_end"].dt.month.isin([3, 6, 9, 12]) & (n["month_end"] >= "2023-03-31")].copy()
    n["price"] = n["value_usd"] * n["rate"] / n["par"] * 100            # rate = currency units per USD
    n = n[n["price"].between(1, 150)]
    n["ntok"] = (n["ISSUER_NAME"].fillna("") + " " + n["ISSUER_TITLE"].fillna("")).map(name_tokens)
    # managers of the registered funds (N-CEN), else first word of the fund name
    n["manager"] = n["SERIES_NAME"].fillna("").str.upper().str.split().str[0]
    if args.ncen_dir and (Path(args.ncen_dir) / "ncen_advisers.csv").exists():
        a1 = pd.read_csv(Path(args.ncen_dir) / "ncen_advisers.csv", dtype=str).set_index("SERIES_ID")["ADVISER"]
        adv = n["FUND_KEY"].map(a1)
        a2p = Path(args.ncen_dir) / "ncen_advisers_by_cik.csv"
        if a2p.exists():
            a2 = pd.read_csv(a2p, dtype=str).set_index("CIK")["ADVISER"]
            cik = n["FUND_KEY"].str.extract(r"^CIK0*(\d+)_", expand=False)
            adv = adv.fillna(cik.map(a2))
        n["manager"] = adv.fillna(n["manager"]).map(lambda x: bpanel.manager(str(x)))
    n = n.groupby(["FUND_KEY", "manager", "month_end", "ccy", "ISSUER_NAME"], as_index=False).agg(
        par=("par", "sum"), value_usd=("value_usd", "sum"), rate=("rate", "first"), ntok=("ntok", "first"))
    n["price"] = n["value_usd"] * n["rate"] / n["par"] * 100
    print(f"\n=== B. Registered funds (N-PORT) vs. BDCs: {len(n):,} N-PORT positions, "
          f"{n['ISSUER_NAME'].nunique():,} borrowers ===")

    rows = []
    bq = {k: g[["cik", "manager", "key", "price", "ntok", "dist"]].to_numpy() for k, g in p.groupby(["month_end", "ccy"])}
    for _, r in n.iterrows():
        for cik, mb, key, pb, nt, dt in bq.get((r["month_end"], r["ccy"]), []):
            toks = nt if nt else dt
            if overlap(r["ntok"], toks) >= 0.75 or overlap(r["ntok"], dt) >= 0.75:
                rows.append({"month_end": r["month_end"], "ccy": r["ccy"], "nport_fund": r["FUND_KEY"],
                             "m_nport": r["manager"], "issuer": r["ISSUER_NAME"], "p_nport": r["price"],
                             "cik": cik, "m_bdc": mb, "key": key, "p_bdc": pb})
    pb_ = pd.DataFrame(rows)
    if pb_.empty:
        print("No matches between N-PORT and BDC positions")
        return
    pb_["absdiff"] = (pb_["p_nport"] - pb_["p_bdc"]).abs()
    big = pb_["absdiff"] > args.max_diff
    pb_ = pb_[~big]
    pb_["same_manager"] = pb_["m_nport"] == pb_["m_bdc"]
    print(f"Matched pairs: {len(pb_):,} ({pb_['issuer'].nunique()} borrowers); {big.sum()} pairs differing by "
          f"> {args.max_diff:g} points excluded")
    for lab, g in [("same manager", pb_[pb_["same_manager"]]), ("different managers", pb_[~pb_["same_manager"]])]:
        if len(g):
            print(f"\n{lab}: {len(g):,} pairs, {g['issuer'].nunique()} borrowers, managers {sorted(g['m_nport'].unique())[:8]}")
            print(agreement(g, "p_nport", "p_bdc").round(3).to_string())
    pb_.to_csv(out / "loanlevel_pairs_nport_bdc.csv", index=False)
    print(f"\nSaved: {out}/loanlevel_pairs_bdc.csv, {out}/loanlevel_pairs_nport_bdc.csv")


if __name__ == "__main__":
    main()
