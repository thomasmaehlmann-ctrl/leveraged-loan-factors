#!/usr/bin/env python3
"""
us_vehicles.py

Same US direct loans in two vehicles: registered closed-end funds (Form N-PORT, OpenDL US) and business
development companies (BDC schedules of investments, XBRL).

Positions of registered funds (dl_panel.py) are matched to BDC positions of the same borrower at the same
quarter-end by the words of the borrower names (issuer name in N-PORT; identifier in XBRL), using an inverted
index. Pairs whose valuations differ by more than --max-diff points are treated as different instruments.

    1. Agreement of valuations by price bucket, separately for the same manager in both vehicles and for
       different managers
    2. Average difference (registered fund minus BDC) by quarter-end: do registered funds value the same loans
       higher, and since when?
    3. The first quarter of 2026: changes of valuations of the same loans from Q4 2025 to Q1 2026 in both
       vehicles; how often a markdown of 2+ points in one vehicle is matched by the other (both directions)
    4. Decomposition of the difference in valuation changes of all continuing loans in Q1 2026 into the part
       due to valuing the shared loans differently and the part due to the other loans (composition)
    5. The same by manager of the registered fund: the largest manager (Cliffwater) vs. the others (pair level)
    6. Position level (main measure): each registered fund loan compared with the median valuation of the same
       borrower by BDCs of other managers, so that borrowers held by many BDCs do not dominate; by price bucket and
       manager group, Q1 2026 markdowns, and the value effect of marking shared loans at the BDC median

Inputs
    <dl-dir>/dl_positions.parquet   (registered funds, dl_panel.py)
    bdc_out/bdc_positions.parquet   (BDCs, bdc_panel.py + bdc_link.py --all-currencies)
Output
    us_vehicles/pairs.csv, us_vehicles/difference_by_quarter.csv

Usage
    python us_vehicles.py --dl-dir "..\\Loan Fund Data\\dl_out"
"""

import argparse
import re
from pathlib import Path

import numpy as np
import pandas as pd

import bdc_link as bl
import bdc_panel as bpanel

BUCKETS = [0, 80, 90, 95, 98, 200]
LABELS = ["< 80", "80-90", "90-95", "95-98", ">= 98"]
GENERIC = bl.STOP | {"INVESTMENTS", "INVESTMENT", "DEBT", "NON", "AFFILIATED", "CONTROLLED", "ISSUER", "TERM",
                     "LOAN", "LOANS", "REVOLVER", "DELAYED", "DRAW", "FIRST", "SECOND", "LIEN", "SENIOR", "SECURED",
                     "UNITRANCHE", "SOFTWARE", "SERVICES", "HEALTH", "CARE", "INDUSTRY", "DBA", "LLC", "INC", "LP",
                     "PARENT", "BUYER", "PURCHASER", "ACQUISITION", "INTERMEDIATE", "FINANCE", "CAPITAL", "COMPANY"}


def tokens(s: str) -> frozenset:
    s = re.sub(r"[^A-Za-z0-9 ]", " ", str(s).upper())
    return frozenset(t for t in s.split() if len(t) > 2 and t not in GENERIC and not t.isdigit())


def agreement(df: pd.DataFrame) -> pd.DataFrame:
    df = df.assign(bucket=pd.cut(df[["p_rf", "p_bdc"]].mean(axis=1), BUCKETS, labels=LABELS, right=False))
    f = lambda g: pd.Series({"pairs": len(g), "borrowers": g["borrower"].nunique(),
                             "mean_diff (rf - bdc)": g["diff"].mean(), "mean_abs_diff": g["absdiff"].mean(),
                             "median_abs_diff": g["absdiff"].median(), "within_1pt": (g["absdiff"] <= 1).mean()})
    return pd.concat([f(df).to_frame("all").T, df.groupby("bucket", observed=True)[df.columns].apply(f)])


def main() -> None:
    ap = argparse.ArgumentParser(description="Same US direct loans in registered funds and BDCs")
    ap.add_argument("--dl-dir", required=True)
    ap.add_argument("--bdc-dir", default="bdc_out")
    ap.add_argument("--out-dir", default="us_vehicles")
    ap.add_argument("--max-diff", type=float, default=20.0)
    ap.add_argument("--start", default="2022-09-30")
    ap.add_argument("--single-facility", action="store_true",
                    help="stricter matching: only BDC positions with a single tranche, and only borrowers matched to one "
                         "position per BDC (reduces the risk of comparing different tranches)")
    ap.add_argument("--bdc-first-lien", action="store_true",
                    help="only BDC positions identified as first lien (control for the seniority of the tranche)")
    args = ap.parse_args()
    out = Path(args.out_dir)
    out.mkdir(exist_ok=True)
    pd.set_option("display.width", 200)

    # ---- registered funds
    rf = pd.read_parquet(Path(args.dl_dir) / "dl_positions.parquet")
    rf["month_end"] = pd.to_datetime(rf["month_end"])
    rf = rf[rf["month_end"].dt.month.isin([3, 6, 9, 12]) & (rf["month_end"] >= args.start) & rf["price"].between(1, 150)]
    rf["mgr"] = rf["manager"].fillna("").map(lambda x: bpanel.manager(str(x)))
    rf["tok"] = rf["issuer_name"].fillna(rf["borrower"]).map(tokens)
    rf = rf[rf["tok"].map(len) > 0]

    # ---- BDCs (USD loans of direct lending BDCs)
    b = pd.read_parquet(Path(args.bdc_dir) / "bdc_positions.parquet")
    b = b[b["dl_bdc"] & b["ccy"].eq("USD") & b["month_end"].dt.month.isin([3, 6, 9, 12]) & (b["month_end"] >= args.start)
          & b["price"].between(1, 150) & ~b["instrument"].isin(["bond", "equipment", "revolver", "delayed_draw"])].copy()
    if args.bdc_first_lien:
        b = b[b["instrument"].eq("first_lien")]
        print("BDC side restricted to positions identified as first lien")
    b["tok"] = b["ident"].map(tokens)
    print(f"Registered fund positions: {len(rf):,}; BDC positions: {len(b):,}")

    # ---- matching by quarter with an inverted index on BDC name words
    rows = []
    for q, gb in b.groupby("month_end"):
        gr = rf[rf["month_end"] == q]
        if gr.empty:
            continue
        brec = gb[["cik", "name", "manager", "key", "price", "tok"]].to_numpy()
        inv: dict[str, list[int]] = {}
        for j, r in enumerate(brec):
            for t in r[5]:
                inv.setdefault(t, []).append(j)
        for r in gr[["FUND_KEY", "mgr", "borrower", "issuer_name", "price", "tok", "default"]].itertuples(index=False):
            a = r.tok
            if len(a) == 1 and len(next(iter(a))) < 5:          # a single short word is too ambiguous
                continue
            cand = {j for t in a for j in inv.get(t, ())}
            for j in cand:
                bt = brec[j][5]
                if len(a & bt) / len(a) >= 0.99 or (len(a) > 2 and len(a & bt) / len(a) >= 0.75):
                    rows.append((q, r.FUND_KEY, r.mgr, r.borrower, r.issuer_name, r.price, bool(r.default),
                                 brec[j][0], brec[j][1], brec[j][2], brec[j][3], brec[j][4]))
    p = pd.DataFrame(rows, columns=["month_end", "rf_fund", "m_rf", "borrower", "issuer", "p_rf", "rf_default",
                                    "cik", "bdc", "m_bdc", "key", "p_bdc"])
    if p.empty:
        raise SystemExit("No matches")
    if args.single_facility:
        one = b.set_index(["cik", "key"])["n_tranches"].groupby(level=[0, 1]).max()
        p = p[[one.get((c, k), 2) == 1 for c, k in zip(p["cik"], p["key"])]]
        cnt = p.groupby(["month_end", "rf_fund", "borrower", "cik"])["key"].transform("nunique")
        p = p[cnt == 1].copy()
        print("Stricter matching: single-tranche BDC positions, one position per BDC and borrower")
    p["diff"] = p["p_rf"] - p["p_bdc"]
    p["absdiff"] = p["diff"].abs()
    big = p["absdiff"] > args.max_diff
    p = p[~big].copy()
    p["same_manager"] = p["m_rf"] == p["m_bdc"]
    p.to_csv(out / "pairs.csv", index=False)
    print(f"Matched pairs: {len(p):,} ({p['borrower'].nunique():,} borrowers); {big.sum()} pairs differing by more "
          f"than {args.max_diff:g} points excluded")

    # 1. agreement
    for lab, g in [("same manager", p[p["same_manager"]]), ("different managers", p[~p["same_manager"]])]:
        if len(g):
            print(f"\n=== 1. Agreement, {lab}: managers {sorted(g['m_rf'].unique())[:10]} ===")
            print(agreement(g).round(3).to_string())

    # 2. average difference by quarter (borrower-level means, so that large borrowers with many BDCs do not dominate)
    bq = p.groupby(["month_end", "same_manager", "borrower"])["diff"].mean().reset_index()
    t = bq.groupby(["month_end", "same_manager"])["diff"].agg(["mean", "median", "size"]).unstack("same_manager")
    t.columns = [f"{a} ({'same' if s else 'different'} manager)" for a, s in t.columns]
    t.to_csv(out / "difference_by_quarter.csv")
    print("\n=== 2. Valuation of the same loans: registered fund minus BDC (points, borrower means) ===")
    print(t.round(2).to_string())

    # 3. Q4 2025 -> Q1 2026
    q0, q1 = pd.Timestamp("2025-12-31"), pd.Timestamp("2026-03-31")
    k = ["rf_fund", "borrower", "cik", "key"]
    a = p[p["month_end"] == q0][k + ["p_rf", "p_bdc", "same_manager"]]
    c = p[p["month_end"] == q1][k + ["p_rf", "p_bdc"]]
    m = a.merge(c, on=k, suffixes=("_0", "_1"))
    if len(m):
        m["d_rf"], m["d_bdc"] = m["p_rf_1"] - m["p_rf_0"], m["p_bdc_1"] - m["p_bdc_0"]
        print(f"\n=== 3. Changes from Q4 2025 to Q1 2026, same pairs (n = {len(m):,}, {m['borrower'].nunique()} borrowers) ===")
        for lab, g in [("all", m), ("same manager", m[m["same_manager"]]), ("different managers", m[~m["same_manager"]])]:
            if len(g) == 0:
                continue
            dn = g[g["d_bdc"] <= -2]
            print(f"{lab:>20}: mean change registered fund {g['d_rf'].mean():+.2f}, BDC {g['d_bdc'].mean():+.2f}; "
                  f"BDC marks down 2+ points in {len(dn)} pairs, registered fund marks down 1+ point in "
                  f"{(dn['d_rf'] <= -1).mean():.0%} of them (mean change {dn['d_rf'].mean():+.2f} vs {dn['d_bdc'].mean():+.2f})")
        print("\nSymmetric test: when one vehicle marks down by 2+ points, how often does the other mark down by 1+ point?")
        for lab, g in [("all", m), ("same manager", m[m["same_manager"]]), ("different managers", m[~m["same_manager"]])]:
            if len(g) == 0:
                continue
            db, dr = g[g["d_bdc"] <= -2], g[g["d_rf"] <= -2]
            print(f"{lab:>20}: BDC down 2+ -> registered fund follows in {(db['d_rf'] <= -1).mean():.0%} (n = {len(db)}); "
                  f"registered fund down 2+ -> BDC follows in {(dr['d_bdc'] <= -1).mean():.0%} (n = {len(dr)})")

    # 4. decomposition of the valuation change Q4 2025 -> Q1 2026 (value-weighted price changes of continuing loans)
    def cont(df, keys, price, value):
        x0 = df[df["month_end"] == q0][keys + [price, value]]
        x1 = df[df["month_end"] == q1][keys + [price]]
        x = x0.merge(x1, on=keys, suffixes=("_0", "_1"))
        x["chg"] = x[f"{price}_1"] / x[f"{price}_0"] - 1
        x["w"] = x[value]
        return x
    rf_c = cont(rf, ["FUND_KEY", "borrower"], "price", "value")
    b_c = cont(b, ["cik", "key"], "price", "fv_usd")
    shared_q = p[p["month_end"].isin([q0, q1])]
    rf_sh = set(zip(shared_q["rf_fund"], shared_q["borrower"]))
    b_sh = set(zip(shared_q["cik"], shared_q["key"]))
    rf_c["shared"] = [k in rf_sh for k in zip(rf_c["FUND_KEY"], rf_c["borrower"])]
    b_c["shared"] = [k in b_sh for k in zip(b_c["cik"], b_c["key"])]
    if len(rf_c) and len(b_c):
        def summ(x):
            w = x["w"].sum()
            sh = x.loc[x["shared"], "w"].sum() / w if w else np.nan
            a_sh = np.average(x.loc[x["shared"], "chg"], weights=x.loc[x["shared"], "w"]) if x["shared"].any() else np.nan
            a_ot = np.average(x.loc[~x["shared"], "chg"], weights=x.loc[~x["shared"], "w"]) if (~x["shared"]).any() else np.nan
            return sh, a_sh * 100, a_ot * 100, np.average(x["chg"], weights=x["w"]) * 100
        s_r, r_sh, r_ot, r_all = summ(rf_c)
        s_b, b_sh_, b_ot, b_all = summ(b_c)
        print("\n=== 4. Valuation change of continuing loans, Q4 2025 -> Q1 2026 (value-weighted price change, %) ===")
        print(f"{'':>26}{'share of value':>16}{'shared loans':>14}{'other loans':>13}{'all loans':>11}")
        print(f"{'registered funds':>26}{s_r:>16.0%}{r_sh:>14.2f}{r_ot:>13.2f}{r_all:>11.2f}")
        print(f"{'BDCs':>26}{s_b:>16.0%}{b_sh_:>14.2f}{b_ot:>13.2f}{b_all:>11.2f}")
        same = s_b * (r_sh - b_sh_)
        print(f"\nDifference registered funds minus BDCs: {r_all - b_all:+.2f} points of price change, of which "
              f"{same:+.2f} from valuing the shared loans differently (BDC weights) and {r_all - b_all - same:+.2f} "
              f"from the other loans and the different mix (composition).")
    # 6. position level: each registered fund loan vs. the median BDC valuation of other managers (main measure)
    top_ = rf.groupby("mgr")["value"].sum().idxmax()
    d_ = p[~p["same_manager"]]
    g = d_.groupby(["month_end", "rf_fund", "borrower", "m_rf"]).agg(p_rf=("p_rf", "first"), p_b=("p_bdc", "median"),
                                                                     n_bdc=("p_bdc", "size")).reset_index()
    g["diff"] = g["p_rf"] - g["p_b"]
    g["bucket"] = pd.cut((g["p_rf"] + g["p_b"]) / 2, BUCKETS, labels=LABELS, right=False)
    g["grp"] = np.where(g["m_rf"] == top_, top_, "OTHER REGISTERED")
    print(f"\n=== 6. Position level: registered fund loan vs. median BDC of other managers "
          f"({len(g):,} position-quarters, median {g['n_bdc'].median():.0f} BDCs per loan) ===")
    tb = g.groupby("bucket", observed=True)["diff"].agg(["mean", "median", "size"])
    tb.loc["all"] = [g["diff"].mean(), g["diff"].median(), len(g)]
    print(tb.round(2).to_string())
    tr = g[(g["p_rf"] + g["p_b"]) / 2 < 95]
    print("Troubled loans (average below 95) by manager group:")
    print(tr.groupby("grp")["diff"].agg(["mean", "median", "size"]).round(2).to_string())
    g.to_csv(out / "positions_vs_bdc_median.csv", index=False)
    if len(m):
        mp = p[~p["same_manager"]]
        a0 = mp[mp["month_end"] == q0][k + ["p_rf", "p_bdc", "m_rf"]]
        a1 = mp[mp["month_end"] == q1][k + ["p_rf", "p_bdc"]]
        mm2 = a0.merge(a1, on=k, suffixes=("_0", "_1"))
        mm2["d_rf"], mm2["d_b"] = mm2["p_rf_1"] - mm2["p_rf_0"], mm2["p_bdc_1"] - mm2["p_bdc_0"]
        gp = mm2.groupby(["rf_fund", "borrower", "m_rf"]).agg(d_rf=("d_rf", "first"), d_b=("d_b", "median")).reset_index()
        gp["grp"] = np.where(gp["m_rf"] == top_, top_, "OTHER REGISTERED")
        print("\nQ4 2025 -> Q1 2026, position level (median BDC of other managers):")
        for lab, x in [("all", gp)] + list(gp.groupby("grp")):
            db, dr = x[x["d_b"] <= -2], x[x["d_rf"] <= -2]
            print(f"{lab:>18}: loans {len(x):,}; mean change fund {x['d_rf'].mean():+.2f}, BDC median {x['d_b'].mean():+.2f}; "
                  f"BDC down 2+ -> fund follows {(db['d_rf'] <= -1).mean():.0%} (n = {len(db)}); "
                  f"fund down 2+ -> BDC follows {(dr['d_b'] <= -1).mean():.0%} (n = {len(dr)})")
        q = g[g["month_end"] == q1]
        if len(q):
            eff = -(q["p_rf"] - q["p_b"]).sum() / q["p_rf"].sum() * 100
            print(f"\nValue of the shared loans of registered funds at the median BDC valuation, March 2026: {eff:+.2f}% "
                  f"(equal principal); share of troubled loans {((q['p_rf'] + q['p_b']) / 2 < 95).mean():.0%}")

    # 5. by manager of the registered fund: the largest manager (Cliffwater) vs. the other managers
    top = rf.groupby("mgr")["value"].sum().idxmax()
    print(f"\n=== 5. By manager of the registered fund: {top} vs. other managers (different managers only) ===")
    pd_ = p[~p["same_manager"]].assign(grp=lambda x: np.where(x["m_rf"] == top, top, "OTHER REGISTERED"))
    lev = pd_[pd_[["p_rf", "p_bdc"]].mean(axis=1).between(80, 95)]
    print("Valuation of troubled loans (average of both marks 80-95): registered fund minus BDC, points")
    print(lev.groupby("grp")["diff"].agg(["mean", "median", "size"]).round(2).to_string())
    if len(m):
        mm = m[~m["same_manager"]].merge(p[["rf_fund", "m_rf"]].drop_duplicates("rf_fund"), on="rf_fund", how="left")
        mm["grp"] = np.where(mm["m_rf"] == top, top, "OTHER REGISTERED")
        print("\nQ4 2025 -> Q1 2026, same pairs:")
        for g_, g in mm.groupby("grp"):
            db, dr = g[g["d_bdc"] <= -2], g[g["d_rf"] <= -2]
            print(f"{g_:>18}: n = {len(g):,}; mean change registered fund {g['d_rf'].mean():+.2f}, BDC {g['d_bdc'].mean():+.2f}; "
                  f"BDC down 2+ -> fund follows {(db['d_rf'] <= -1).mean():.0%} (n = {len(db)}); "
                  f"fund down 2+ -> BDC follows {(dr['d_bdc'] <= -1).mean():.0%} (n = {len(dr)})")
    if len(rf_c) and len(b_c):
        rf_c["grp"] = np.where(rf_c["FUND_KEY"].map(rf.drop_duplicates("FUND_KEY").set_index("FUND_KEY")["mgr"]) == top,
                               top, "OTHER REGISTERED")
        print("\nValuation change of continuing loans, Q4 2025 -> Q1 2026 (value-weighted, %):")
        for g_, x in rf_c.groupby("grp"):
            sh, a_sh, a_ot, a_all = summ(x)
            print(f"{g_:>18}: share shared {sh:.0%}; shared loans {a_sh:+.2f}; other loans {a_ot:+.2f}; all {a_all:+.2f}")
        print(f"{'BDCs':>18}: share shared {s_b:.0%}; shared loans {b_sh_:+.2f}; other loans {b_ot:+.2f}; all {b_all:+.2f}")
    print(f"\nSaved in {out}: pairs.csv, difference_by_quarter.csv")


if __name__ == "__main__":
    main()
