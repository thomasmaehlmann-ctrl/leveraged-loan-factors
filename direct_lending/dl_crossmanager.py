#!/usr/bin/env python3
"""
dl_crossmanager.py

Loan-level validation of the direct lending data: the same loan valued by different managers.

For borrowers held by at least two managers in the same quarter (and with maturities within --max-maturity-gap
days of each other, so that different facilities of the same borrower are not compared), the script compares
the managers' marks (par-weighted price per manager, across its funds):

    1. Agreement in levels: mean absolute difference between managers, share within 1 and 2 points,
       by price bucket (performing vs. stressed loans)
    2. Agreement in changes: correlation of quarterly mark changes of the same loan by different managers,
       contemporaneous and with one quarter lead/lag (who marks down first?)
    3. Systematic differences by manager: mean deviation of a manager's mark from the average mark of the other
       managers on the same loan and quarter (positive = marks higher than the others)
    4. Non-accrual agreement: if one manager reports a loan as non-accrual (coupon zero), does the other?
    5. Club loans: share of each manager's principal in borrowers also held by other managers, together with
       position size, coupon, non-accrual share and share valued below 90 of its portfolio

Input: dl_out/dl_positions.parquet (from dl_panel.py)
Output: dl_out/crossmanager_*.csv

Usage
    python dl_crossmanager.py
"""

import argparse
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd


def manager_marks(pos: pd.DataFrame, max_gap: int) -> pd.DataFrame:
    pos = pos.copy()
    pos["value_par"] = pos["price"] * pos["par"]
    pos["na_par"] = pos["coupon"].fillna(0).le(0.01) * pos["par"]
    pos["df_par"] = pos["default"].map(lambda v: bool(v) if v is not None and v == v else False) * pos["par"]
    m = pos.groupby(["borrower", "month_end", "manager"]).agg(
        par=("par", "sum"), value_par=("value_par", "sum"), na_par=("na_par", "sum"), df_par=("df_par", "sum"),
        maturity=("maturity", "max"), funds=("FUND_KEY", "nunique"),
        name=("issuer_name", "first"), title=("issuer_title", "first"), coupon=("coupon", "mean")).reset_index()
    m["price"] = m["value_par"] / m["par"]
    m["non_accrual"] = m["na_par"] / m["par"] > 0.5
    m["default_flag"] = m["df_par"] / m["par"] > 0.5
    # keep borrower-quarters with at least two managers and close maturities
    g = m.groupby(["borrower", "month_end"])
    m["n_mgr"] = g["manager"].transform("size")
    mat = pd.to_datetime(m["maturity"])
    spread = mat.groupby([m["borrower"], m["month_end"]]).transform(
        lambda x: (x.max() - x.min()).days if x.notna().all() else 10**6)   # unknown maturity: no comparison
    return m[(m["n_mgr"] >= 2) & (spread <= max_gap)].drop(columns=["value_par", "na_par", "df_par"])


def pairs(m: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (b, q), g in m.groupby(["borrower", "month_end"]):
        recs = g[["manager", "price", "non_accrual", "default_flag", "title", "coupon", "maturity"]].to_dict("records")
        for a, c in combinations(recs, 2):
            rows.append({"borrower": b, "month_end": q, "m1": a["manager"], "m2": c["manager"],
                         "p1": a["price"], "p2": c["price"], "na1": a["non_accrual"], "na2": c["non_accrual"],
                         "df1": a["default_flag"], "df2": c["default_flag"],
                         "title1": a["title"], "title2": c["title"], "cpn1": a["coupon"], "cpn2": c["coupon"],
                         "mat1": a["maturity"], "mat2": c["maturity"]})
    return pd.DataFrame(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description="Same loan, different managers: comparison of marks")
    ap.add_argument("--dir", default="dl_out")
    ap.add_argument("--start", default="2021-12-31")
    ap.add_argument("--max-maturity-gap", type=int, default=180, help="max. difference of maturities in days")
    ap.add_argument("--max-diff", type=float, default=20.0,
                    help="pairs differing by more points are treated as different instruments and excluded")
    args = ap.parse_args()
    d = Path(args.dir)
    pd.set_option("display.width", 200)

    pos = pd.read_parquet(d / "dl_positions.parquet")
    pos["month_end"] = pd.to_datetime(pos["month_end"])
    pos = pos[(pos["month_end"] >= pd.Timestamp(args.start)) & pos["price"].between(1, 150)]
    m = manager_marks(pos, args.max_maturity_gap)
    print(f"Borrower-quarters held by two or more managers: {m.groupby(['borrower', 'month_end']).ngroups:,} "
          f"({m['borrower'].nunique():,} borrowers, {m['manager'].nunique()} managers)")
    share = m.groupby("month_end")["par"].sum() / pos.groupby("month_end")["par"].sum()
    print(f"Share of par in multi-manager loans: median {share.median():.1%} per quarter")

    # 1. levels
    p = pairs(m)
    p["absdiff"] = (p["p1"] - p["p2"]).abs()
    p["level"] = pd.cut(p[["p1", "p2"]].mean(axis=1), [0, 80, 90, 95, 98, 200],
                        labels=["< 80", "80-90", "90-95", "95-98", ">= 98"])
    lv = p.groupby("level", observed=True).agg(pairs=("absdiff", "size"), mean_abs_diff=("absdiff", "mean"),
                                               median_abs_diff=("absdiff", "median"),
                                               within_1pt=("absdiff", lambda x: (x <= 1).mean()),
                                               within_2pt=("absdiff", lambda x: (x <= 2).mean()))
    tot = pd.DataFrame({"pairs": [len(p)], "mean_abs_diff": [p["absdiff"].mean()],
                        "median_abs_diff": [p["absdiff"].median()], "within_1pt": [(p["absdiff"] <= 1).mean()],
                        "within_2pt": [(p["absdiff"] <= 2).mean()]}, index=["all"])
    lv = pd.concat([tot, lv])
    lv.to_csv(d / "crossmanager_levels.csv")
    print("\n=== 1. Agreement of marks (manager pairs, same borrower and quarter), by average mark ===")
    print(lv.round(3).to_string())
    big_gap = p[p["absdiff"] > args.max_diff].sort_values("absdiff", ascending=False)
    print(f"\nPairs differing by more than {args.max_diff:g} points (likely different instruments of the same "
          f"borrower): {len(big_gap):,} of {len(p):,}; the largest:")
    cols = ["borrower", "month_end", "m1", "p1", "cpn1", "title1", "m2", "p2", "cpn2", "title2"]
    print(big_gap[cols].head(15).assign(title1=lambda x: x["title1"].str[:28], title2=lambda x: x["title2"].str[:28])
          .round({"p1": 1, "p2": 1, "cpn1": 1, "cpn2": 1}).to_string(index=False))
    bad = set(zip(big_gap["borrower"], big_gap["month_end"]))
    m = m[[(b, q) not in bad for b, q in zip(m["borrower"], m["month_end"])]]
    pf = p[p["absdiff"] <= args.max_diff]
    print(f"\nWithout these pairs: mean abs diff {pf['absdiff'].mean():.2f}, within 1 pt {(pf['absdiff'] <= 1).mean():.1%}, "
          f"within 2 pts {(pf['absdiff'] <= 2).mean():.1%} (n = {len(pf):,}); "
          f"marks below 95: mean abs diff {pf.loc[pf[['p1','p2']].mean(axis=1) < 95, 'absdiff'].mean():.2f}")
    print("All following results exclude borrower-quarters with such pairs.")

    # 2. changes: quarter-on-quarter change of each manager's mark, matched pairs
    m = m.sort_values(["borrower", "manager", "month_end"])
    gg = m.groupby(["borrower", "manager"])
    m["chg"] = m["price"] - gg["price"].shift(1)
    m.loc[gg["month_end"].shift(1) != m["month_end"] - pd.offsets.QuarterEnd(1), "chg"] = np.nan
    ch = m[["borrower", "month_end", "manager", "chg"]].dropna()
    pc = ch.merge(ch, on=["borrower", "month_end"], suffixes=("1", "2"))
    pc = pc[pc["manager1"] < pc["manager2"]]
    lead = ch.copy()
    lead["month_end"] = lead["month_end"] - pd.offsets.QuarterEnd(1)   # change of the other manager one quarter later
    pl = ch.merge(lead, on=["borrower", "month_end"], suffixes=("1", "2"))
    pl = pl[pl["manager1"] != pl["manager2"]]
    big = pc[(pc["chg1"].abs() >= 2) | (pc["chg2"].abs() >= 2)]
    print("\n=== 2. Agreement of quarterly mark changes (points) ===")
    print(f"Contemporaneous correlation: {pc['chg1'].corr(pc['chg2']):.2f}, rank correlation "
          f"{pc['chg1'].corr(pc['chg2'], method='spearman'):.2f} (n = {len(pc):,}); "
          f"for changes of at least 2 points: {big['chg1'].corr(big['chg2']):.2f} (n = {len(big):,})")
    print(f"Correlation with the other manager's change one quarter later: {pl['chg1'].corr(pl['chg2']):.2f} "
          f"(n = {len(pl):,})")
    dn = pc[(pc["chg1"] <= -2) | (pc["chg2"] <= -2)]
    if len(dn):
        same_q = ((dn["chg1"] <= -1) & (dn["chg2"] <= -1)).mean()
        print(f"Markdowns of 2 points or more by one manager: the other also marks down by 1 point or more "
              f"in the same quarter in {same_q:.0%} of cases (n = {len(dn):,})")

    # 3. systematic differences by manager (leave-one-out deviation)
    s = m.groupby(["borrower", "month_end"])
    m["others_avg"] = (s["price"].transform("sum") - m["price"]) / (s["price"].transform("size") - 1)
    m["dev"] = m["price"] - m["others_avg"]
    trim = lambda x: x[(x >= x.quantile(0.05)) & (x <= x.quantile(0.95))].mean()
    by = m.groupby("manager").agg(loan_quarters=("dev", "size"), borrowers=("borrower", "nunique"),
                                  mean_dev=("dev", "mean"), trimmed_mean_dev=("dev", trim),
                                  median_dev=("dev", "median"), sd_dev=("dev", "std"),
                                  share_higher=("dev", lambda x: (x > 0.25).mean()),
                                  share_lower=("dev", lambda x: (x < -0.25).mean()))
    # t-statistic across borrowers (deviations of the same loan over time are averaged first)
    bb = m.groupby(["manager", "borrower"])["dev"].mean().groupby("manager")
    by["t (borrower-clustered)"] = bb.mean() / (bb.std() / np.sqrt(bb.size()))
    by = by[by["loan_quarters"] >= 20].sort_values("mean_dev", ascending=False)
    by.to_csv(d / "crossmanager_by_manager.csv")
    print("\n=== 3. Mark relative to the other managers on the same loan (points; managers with >= 20 loan-quarters) ===")
    print(by.round(2).to_string())

    # 4. agreement on distress status (all pairs, including those excluded above)
    print("\n=== 4. Agreement on distress status (all manager pairs) ===")
    for c1, c2, lab in [("na1", "na2", "non-accrual (coupon zero)"), ("df1", "df2", "default flag")]:
        one_or_both = p[p[c1] | p[c2]]
        if not len(one_or_both):
            print(f"{lab}: no pair in which a manager reports this status")
            continue
        both = (one_or_both[c1] & one_or_both[c2]).mean()
        x = one_or_both.assign(p_flag=np.where(one_or_both[c1], one_or_both["p1"], one_or_both["p2"]),
                               p_other=np.where(one_or_both[c1], one_or_both["p2"], one_or_both["p1"]))
        dis = x[x[c1] ^ x[c2]]
        msg = (f"{lab}: {len(one_or_both):,} pairs with the status at one or both managers; both report it in "
               f"{both:.0%}")
        if len(dis):
            msg += (f"; where only one reports it, median mark {dis['p_flag'].median():.1f} (with status) vs. "
                    f"{dis['p_other'].median():.1f} (without)")
        print(msg)
    # 5. jointly held (club) loans by manager: share of a manager's principal in borrowers that other managers
    #    also hold in the same quarter, with size, coupon and credit indicators of its portfolio
    allp = pos.copy()
    nm = allp.groupby(["borrower", "month_end"])["manager"].transform("nunique")
    allp["club"] = nm >= 2
    allp["na"] = allp["coupon"].fillna(0).le(0.01)
    allp["b90"] = allp["price"] < 90
    w = lambda x, col: (allp.loc[x.index, col] * allp.loc[x.index, "par"]).sum() / allp.loc[x.index, "par"].sum()
    cm = allp.groupby("manager").agg(position_quarters=("par", "size"), par_bn=("par", lambda x: x.sum() / 1e9))
    cm["club_share_par"] = allp.groupby("manager").apply(lambda g: g.loc[g["club"], "par"].sum() / g["par"].sum(), include_groups=False)
    cm["median_position_mn"] = allp.groupby("manager")["par"].median() / 1e6
    cm["median_coupon"] = allp.groupby("manager")["coupon"].median()
    cm["non_accrual_share_par"] = allp.groupby("manager").apply(lambda g: g.loc[g["na"], "par"].sum() / g["par"].sum(), include_groups=False)
    cm["below90_share_par"] = allp.groupby("manager").apply(lambda g: g.loc[g["b90"], "par"].sum() / g["par"].sum(), include_groups=False)
    cm = cm[cm["position_quarters"] >= 100].sort_values("par_bn", ascending=False)
    cm.to_csv(d / "crossmanager_club_by_manager.csv")
    print("\n=== 5. Jointly held (club) loans and portfolio characteristics by manager (all quarters, managers with >= 100 position-quarters) ===")
    print(cm.round(3).to_string())
    others = allp[allp["manager"] != cm.index[0]] if len(cm) else allp
    largest = allp[allp["manager"] == cm.index[0]] if len(cm) else allp.iloc[:0]
    if len(largest):
        print(f"Club share of principal: largest manager ({cm.index[0]}) {largest.loc[largest['club'], 'par'].sum() / largest['par'].sum():.1%}, "
              f"all other managers {others.loc[others['club'], 'par'].sum() / others['par'].sum():.1%}")

    p.to_csv(d / "crossmanager_pairs.csv", index=False)
    print(f"\nSaved: {d}/crossmanager_levels.csv, crossmanager_by_manager.csv, crossmanager_pairs.csv")


if __name__ == "__main__":
    main()
