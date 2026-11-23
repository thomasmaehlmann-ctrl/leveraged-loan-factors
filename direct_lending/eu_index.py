#!/usr/bin/env python3
"""
eu_index.py

European direct lending index from the BDC position panel (bdc_panel.py, bdc_link.py), constructed with the
same functions as the US index (dl_index.py): income and price returns, exits and recoveries, estimated cost
basis, equal weighting across managers, credit health barometer.

Universe   positions of direct lending BDCs in European currencies (EUR, GBP, CHF, SEK, NOK, DKK, PLN),
           calendar quarter-ends; optionally (--borrower) loans of European borrowers in any currency
Returns    in loan currency (prices converted with quarter-end exchange rates), i.e. without currency effects
Position   BDC x position key x currency; revolvers, delayed-draw tranches, bonds and equipment financings excluded
Coupon     tagged InvestmentInterestRate, else the rate stated in the identifier, else 3-month base rate of the
           currency (FRED) plus the spread stated in the identifier, else median of the BDC, currency and quarter
Distress   BDCs do not tag non-accrual status: loans described as non-accrual or valued below --nonaccrual-price
           (70) earn no income; distressed exits are realized at --recovery (70.8% of par, the estimate from the
           US N-PORT data), capped at the last valuation

Output (eu_out/)
    index_*.csv, eu_position_returns.parquet, credit_health_barometer.csv

Usage
    python eu_index.py
    python eu_index.py --start 2023-03-31 --min-positions 5
    python eu_index.py --borrower                 (European borrowers in any currency)
"""

import argparse
import io
from pathlib import Path

import numpy as np
import pandas as pd
import requests

import dl_index as di

# 3-month interbank rates (OECD via FRED), monthly, in % p.a.
BASE = {"EUR": "IR3TIB01EZM156N", "GBP": "IR3TIB01GBM156N", "SEK": "IR3TIB01SEM156N", "NOK": "IR3TIB01NOM156N",
        "DKK": "IR3TIB01DKM156N", "CHF": "IR3TIB01CHM156N", "PLN": "IR3TIB01PLM156N", "USD": "IR3TIB01USM156N"}


def base_rates(ccys, ua: str) -> pd.DataFrame:
    rows = []
    for c in ccys:
        if c not in BASE:
            continue
        r = requests.get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={BASE[c]}", headers={"User-Agent": ua},
                         timeout=60)
        r.raise_for_status()
        f = pd.read_csv(io.StringIO(r.text))
        f.columns = ["date", "base"]
        f["month_end"] = pd.to_datetime(f["date"]) + pd.offsets.MonthEnd(0)
        f["base"] = pd.to_numeric(f["base"], errors="coerce")
        f["ccy"] = c
        rows.append(f[["month_end", "ccy", "base"]].dropna())
    b = pd.concat(rows)
    # carry the last available month forward to later quarter-ends
    full = []
    for c, g in b.groupby("ccy"):
        idx = pd.date_range(g["month_end"].min(), pd.Timestamp.today() + pd.offsets.MonthEnd(0), freq="ME")
        full.append(g.set_index("month_end")["base"].reindex(idx).ffill().rename_axis("month_end").reset_index()
                    .assign(ccy=c))
    return pd.concat(full)


def main() -> None:
    ap = argparse.ArgumentParser(description="European direct lending index from BDC filings")
    ap.add_argument("--dir", default="bdc_out")
    ap.add_argument("--out-dir", default="eu_out")
    ap.add_argument("--start", default="2023-03-31", help="first quarter-end (returns start one quarter later)")
    ap.add_argument("--min-positions", type=int, default=5, help="positions per manager for the main index")
    ap.add_argument("--distress-price", type=float, default=80.0)
    ap.add_argument("--region", choices=["europe", "us"], default="europe",
                    help="europe: loans in European currencies (OpenDL Europe); us: US dollar loans of BDCs")
    ap.add_argument("--cdli", default=None, help="CSV with quarterly CDLI returns in %% (quarter, total[, income, "
                                                 "realized, unrealized]) for the comparison of the US BDC index")
    ap.add_argument("--borrower", action="store_true", help="European borrowers in any currency instead of "
                                                             "European-currency loans")
    ap.add_argument("--recovery", type=float, default=70.8,
                    help="recovery rate in %% of par (default: estimate from the US N-PORT data)")
    ap.add_argument("--nonaccrual-price", type=float, default=70.0,
                    help="loans valued below this are treated as non-accrual (BDCs do not tag non-accrual status)")
    ap.add_argument("--base-csv", default=None, help="CSV with month_end, ccy, base (instead of FRED)")
    ap.add_argument("--no-collapse-filter", action="store_true",
                    help="keep temporary collapses of prices (robustness of the reporting-error rule)")
    ap.add_argument("--no-imputed", action="store_true", help="drop positions whose coupon had to be imputed")
    ap.add_argument("--ccy", nargs="*", default=None, help="restrict to these loan currencies (e.g. EUR GBP)")
    ap.add_argument("--first-lien-only", action="store_true", help="only positions identified as first lien")
    ap.add_argument("--exclude-manager", nargs="*", default=None, help="managers to leave out (e.g. BLACKSTONE)")
    ap.add_argument("--esdi", default=None, help="CSV with quarter, total (%%) of the Lincoln European Senior Debt Index")
    ap.add_argument("--repay-price", type=float, default=95.0,
                    help="exits with a last valuation at or above this are treated as repayments at par")
    ap.add_argument("--user-agent", default="Research name@example.com")
    args = ap.parse_args()
    out = Path(args.out_dir)
    out.mkdir(exist_ok=True)
    pd.set_option("display.width", 220)

    p = pd.read_parquet(Path(args.dir) / "bdc_positions.parquet")
    p["month_end"] = pd.to_datetime(p["month_end"])
    if args.region == "us":
        sel = p["ccy"].eq("USD")
    else:
        sel = p["eu_borrower"] if args.borrower else p["eu_ccy"]
    p = p[p["dl_bdc"] & sel & p["month_end"].dt.month.isin([3, 6, 9, 12])
          & (p["month_end"] >= pd.Timestamp(args.start) - pd.offsets.QuarterEnd(1))]
    p = p[p["price"].between(1, 150) & ~p["instrument"].isin(["bond", "equipment", "revolver", "delayed_draw"])].copy()
    n_q = p.groupby("month_end").size()
    thin = [q for i, q in enumerate(n_q.index) if i > 0 and n_q[q] < 0.5 * n_q.iloc[:i].tail(4).median()]
    if thin:
        print(f"Quarter-ends with incomplete reporting dropped: {[str(pd.Timestamp(q).date()) for q in thin]}")
        p = p[~p["month_end"].isin(thin)]
    if args.ccy:
        p = p[p["ccy"].isin([c.upper() for c in args.ccy])]
    if args.first_lien_only:
        p = p[p["instrument"].eq("first_lien")]
    if args.exclude_manager:
        p = p[~p["manager"].isin([m.upper() for m in args.exclude_manager])]
    structured = p["ident"].str.contains(r"\bCLO\b|Structured Finance|Structured Product|Subordinated Notes|"
                                         r"Asset[- ]Backed|Securitization|\bABS\b", case=False, na=False)
    print(f"CLO tranches and structured finance excluded: {structured.sum():,}")
    p = p[~structured]

    # ---- temporary collapses: a price below 60% of both the previous and a later price of the same position
    #      is treated as a reporting error (e.g. a tranche reported without fair value) and dropped
    p = p.sort_values(["cik", "key", "ccy", "month_end"])
    n_drop = 0
    for _ in range(0 if args.no_collapse_filter else 4):   # repeated, so that collapses over several quarters are removed
        g = p.groupby(["cik", "key", "ccy"])["price"]
        prev = g.shift(1)
        later_max = g.transform(lambda x: x[::-1].cummax()[::-1].shift(-1))
        spike = (p["price"] < 0.6 * prev) & (p["price"] < 0.6 * later_max) & ~p["nonaccrual"]
        first_low = prev.isna() & (p["price"] < 0.6 * later_max) & ~p["nonaccrual"]
        drop = spike | first_low
        if not drop.any():
            break
        n_drop += int(drop.sum())
        p = p[~drop]
    print(f"Observations dropped as temporary collapses: {n_drop:,}")

    # ---- coupon: tagged or stated rate, else base rate + spread, else median of the BDC / currency / quarter
    if args.base_csv:
        base = pd.read_csv(args.base_csv, parse_dates=["month_end"])
    else:
        base = base_rates(sorted(set(p["ccy"].unique()) | set(BASE)), args.user_agent)
        base.to_csv(out / "base_rates.csv", index=False)        # reusable with --base-csv
    p = p.merge(base, on=["month_end", "ccy"], how="left")
    src = np.where(p["coupon"].notna(), p["rate_src"].fillna("tag"), "none")
    from_spread = p["coupon"].isna() & p["spread"].notna() & p["base"].notna()
    p.loc[from_spread, "coupon"] = p.loc[from_spread, "base"].clip(lower=0) + p.loc[from_spread, "spread"]
    src = np.where(from_spread, "base + spread", src)
    for grp in (["cik", "key", "ccy"], ["cik", "ccy", "month_end"], ["ccy", "month_end"]):
        miss = p["coupon"].isna()
        p.loc[miss, "coupon"] = p.groupby(grp)["coupon"].transform("median")[miss]
        src = np.where(miss & p["coupon"].notna(), "imputed", src)
    print("Coupon source (share of positions):")
    print(pd.Series(src).value_counts(normalize=True).round(3).to_string())
    if args.no_imputed:
        keep = pd.Series(src, index=p.index).isin(["tag", "text", "base + spread"])
        print(f"Positions with imputed coupon dropped: {(~keep).sum():,}")
        p = p[keep]
    # plausibility: coupon over the 3-month base rate (implied spread), median by currency and year
    ok = p["coupon"].notna() & p["base"].notna()
    if ok.any():
        sp = (p.loc[ok, "coupon"] - p.loc[ok, "base"]).groupby([p.loc[ok, "ccy"], p.loc[ok, "month_end"].dt.year]).median()
        tab = sp.unstack(0)[[c for c in ["EUR", "GBP", "USD"] if c in sp.index.get_level_values(0)]]
        print("Median coupon minus 3-month base rate (implied spread, % p.a.):")
        print(tab.round(2).to_string())

    # ---- non-accrual: stated in the identifier, or valued below --nonaccrual-price
    na = p["nonaccrual"] | (p["price"] < args.nonaccrual_price)
    # weights in US dollars: principal converted at the exchange rate of the first quarter-end of each position
    # (fixed, so that exchange rate moves do not appear as draws or repayments); prices stay in loan currency
    p = p.sort_values("month_end")
    p["usd_per_ccy_t"] = (p["fv_usd"] / p["fv_local"]).where(p["fv_local"] > 0)
    p["fx0"] = p.groupby(["cik", "key", "ccy"])["usd_per_ccy_t"].transform("first").fillna(p["usd_per_ccy_t"]).fillna(1.0)
    p["par_usd"] = p["par"] * p["fx0"]
    pos = pd.DataFrame({
        "FUND_KEY": p["cik"].astype(str), "borrower": p["key"] + "|" + p["ccy"], "month_end": p["month_end"],
        "manager": p["manager"], "par": p["par_usd"], "value": p["par_usd"] * p["price"] / 100, "price": p["price"],
        "coupon": np.where(na, 0.0, p["coupon"]), "default": na, "pik": p["pik"], "ccy": p["ccy"]})
    print(f"Positions: {len(pos):,}; BDCs {pos['FUND_KEY'].nunique()}; managers {pos['manager'].nunique()}; "
          f"quarter-ends {pos['month_end'].nunique()}; treated as non-accrual {pos['default'].mean():.1%} "
          f"(stated {p['nonaccrual'].mean():.1%}); coupon still missing {pos['coupon'].isna().mean():.1%}")
    pos = pos[pos["coupon"].notna()]

    pos = di.add_cost_basis(pos)
    rec = args.recovery
    print(f"Recovery rate for distressed exits: {rec:.1f}% of par")
    di.REPAY_MIN_PRICE = args.repay_price
    ret = di.position_returns(pos, 0.0, rec, args.distress_price)
    # exits of borrowers that the same BDC still holds in the next quarter (under another identifier, tranche
    # or currency) are not exits: refinancings and restructurings within the lender are not sales
    import bdc_link as bl
    dd = p[["cik", "month_end", "key"]].drop_duplicates().copy()
    dd["dist"] = bl.distinctive(dd)
    dist = {(str(c), m, k): d for c, m, k, d in zip(dd["cik"], dd["month_end"], dd["key"], dd["dist"])}
    nxt = {}
    for (c, m), g in dd.groupby(["cik", "month_end"]):
        nxt[(str(c), m)] = [d for d in g["dist"] if d]
    def still_held(row) -> bool:
        key = row["borrower"].rsplit("|", 1)[0]
        prev_q = row["month_end"] - pd.offsets.QuarterEnd(1)
        d0 = dist.get((row["FUND_KEY"], prev_q, key))
        if not d0:
            return False
        return any(len(d0 & d1) / min(len(d0), len(d1)) >= 0.75 for d1 in nxt.get((row["FUND_KEY"], row["month_end"]), []))
    ex = ret[ret["exit"]]
    held = ex.apply(still_held, axis=1) if len(ex) else pd.Series(dtype=bool)
    print(f"Exits of borrowers still held by the same BDC in the next quarter (not counted as exits): "
          f"{int(held.sum()):,} of {len(ex):,}; of these with last valuation below {args.repay_price:g}: "
          f"{int((held & ex['p0'].lt(args.repay_price)).sum()):,}")
    ret = ret.drop(index=held[held].index)
    ex2 = ret[ret["exit"]]
    print(f"Remaining exits: {len(ex2):,}, of which treated as repayments at par: "
          f"{(ex2['price_ret'] >= (100 - ex2['p0']) / ex2['p0'] - 1e-9).mean():.0%}")
    # quarters in which the principal more than doubled or halved: price changes mainly reflect draws or partial
    # repayments of the tranche, so no return is computed for that quarter
    pp = pos.sort_values(["FUND_KEY", "borrower", "month_end"])
    pp["par_ratio"] = pp["par"] / pp.groupby(["FUND_KEY", "borrower"])["par"].shift(1)
    jump = pp.loc[(pp["par_ratio"] > 2) | (pp["par_ratio"] < 0.5), ["FUND_KEY", "borrower", "month_end"]]
    jk = set(zip(jump["FUND_KEY"], jump["borrower"], jump["month_end"]))
    mj = ~ret["exit"] & pd.Series(list(zip(ret["FUND_KEY"], ret["borrower"], ret["month_end"])), index=ret.index).isin(jk)
    print(f"Position-quarters without a return because the principal more than doubled or halved: {mj.sum():,}")
    ret = ret[~mj]
    # BDC-quarters in which fewer than half of the positions are found again: identifiers changed, so the
    # missing positions are treated like positions of a fund that does not report (no exits)
    qe = sorted(pos["month_end"].unique())
    low = set()
    for a_, b_ in zip(qe[:-1], qe[1:]):
        A, B = pos[pos["month_end"] == a_], pos[pos["month_end"] == b_]
        for f, g in A.groupby("FUND_KEY"):
            nb = set(B.loc[B["FUND_KEY"] == f, "borrower"])
            if nb and len(g) >= 5 and g["borrower"].isin(nb).mean() < 0.5:
                low.add((f, b_))
    if low:
        m = ret["exit"] & pd.Series(list(zip(ret["FUND_KEY"], ret["month_end"])), index=ret.index).isin(low)
        print(f"BDC-quarters with identifier changes (< 50% of positions found again): {len(low)}; "
              f"exits not counted: {m.sum():,}")
        ret = ret[~m]
    ret = ret[ret["exit"] | ret["distress"] | (ret["total"].abs() <= 0.5)]
    ret = ret[ret["month_end"] > pd.Timestamp(args.start)]
    largest = ret.groupby("manager")["v0"].sum().idxmax()
    print(f"Largest manager: {largest}")
    ix = di.build_indices(ret, args.min_positions, largest)
    for k, v in ix.items():
        v.to_csv(out / f"index_{k.replace(' ', '_').lower()}.csv")
    ret.to_parquet(out / "eu_position_returns.parquet", index=False)

    summ = di.summary(ix)
    print(f"\n=== {'European' if args.region == 'europe' else 'US BDC'} direct lending index (returns in loan currency) ===")
    print(summ.round(2).to_string())
    tab = pd.DataFrame({k: v["total"] * 100 for k, v in ix.items()})
    n = ix["EW managers"]
    tab["managers (EW)"] = n["managers"] if "managers" in n else np.nan
    tab["positions"] = ix["VW all"]["positions"] if "positions" in ix["VW all"] else np.nan
    print("\n=== Quarterly total returns (%) ===")
    print(tab.round(2).to_string())
    full = tab.drop(columns=["managers (EW)", "positions"])
    full = full[full.groupby(full.index.year)[full.columns[0]].transform("size") == 4]
    if len(full):
        print("\n=== Calendar-year total returns (%) ===")
        print((((1 + full / 100).groupby(full.index.year).prod() - 1) * 100).round(2).to_string())

    if args.esdi:
        e = pd.read_csv(args.esdi, parse_dates=["quarter"]).set_index("quarter")["total"].dropna()
        e.index = e.index + pd.offsets.QuarterEnd(0)
        rows = []
        for k, v in ix.items():
            j = pd.concat([v["total"] * 100, e], axis=1, sort=True).dropna()
            if len(j) < 3:
                continue
            rows.append({"index": k, "quarters": len(j), "corr": j.iloc[:, 0].corr(j.iloc[:, 1]),
                         "mean diff (pp/q)": (j.iloc[:, 0] - j.iloc[:, 1]).mean(),
                         "mean abs diff (pp/q)": (j.iloc[:, 0] - j.iloc[:, 1]).abs().mean(),
                         "index p.a. (common q)": ((1 + j.iloc[:, 0] / 100).prod() ** (4 / len(j)) - 1) * 100,
                         "ESDI p.a. (common q)": ((1 + j.iloc[:, 1] / 100).prod() ** (4 / len(j)) - 1) * 100})
        print("\n=== Comparison with the Lincoln European Senior Debt Index (ESDI), common quarters ===")
        print(pd.DataFrame(rows).set_index("index").round(2).to_string())
        cmp_ = pd.concat([ix["EW managers"]["total"] * 100, ix["VW all"]["total"] * 100, e], axis=1, sort=True)
        cmp_.columns = ["EW managers", "VW all", "ESDI"]
        print(cmp_.loc[cmp_.index >= ix["VW all"].index.min()].round(2).to_string())

    if args.cdli:
        c = pd.read_csv(args.cdli)
        qc = c.columns[0]
        c[qc] = pd.PeriodIndex(c[qc].astype(str).str.replace(" ", ""), freq="Q").to_timestamp(how="end").normalize() \
            if not str(c[qc].iloc[0])[:4].isdigit() or "Q" in str(c[qc].iloc[0]) else pd.to_datetime(c[qc])
        c[qc] = c[qc] + pd.offsets.QuarterEnd(0)
        c = c.set_index(qc)
        tcol = [x for x in c.columns if x.lower().startswith("total")][0]
        rows = []
        for k, v in ix.items():
            j = pd.concat([v["total"] * 100, c[tcol]], axis=1, sort=True).dropna()
            if len(j) < 3:
                continue
            row = {"index": k, "quarters": len(j), "corr total": j.iloc[:, 0].corr(j.iloc[:, 1]),
                   "index p.a.": ((1 + j.iloc[:, 0] / 100).prod() ** (4 / len(j)) - 1) * 100,
                   "CDLI p.a.": ((1 + j.iloc[:, 1] / 100).prod() ** (4 / len(j)) - 1) * 100}
            for comp, mine in [("income", "income"), ("price", "price_ret"), ("realized", "realized_cost"),
                               ("unrealized", "unrealized_cost")]:
                cc = [x for x in c.columns if x.lower().startswith(comp)]
                if cc and mine in v:
                    jj = pd.concat([v[mine] * 100, c[cc[0]]], axis=1, sort=True).dropna()
                    if len(jj) >= 3:
                        row[f"corr {comp}"] = jj.iloc[:, 0].corr(jj.iloc[:, 1])
                        row[f"{comp} p.a. index / CDLI"] = f"{jj.iloc[:, 0].mean() * 4:.2f} / {jj.iloc[:, 1].mean() * 4:.2f}"
            rows.append(row)
        print("\n=== Comparison with the Cliffwater Direct Lending Index (CDLI), common quarters ===")
        print(pd.DataFrame(rows).set_index("index").round(2).to_string())
        cmp_ = pd.concat([ix["EW managers"]["total"] * 100, ix["VW all"]["total"] * 100, c[tcol]], axis=1, sort=True)
        cmp_.columns = ["EW managers", "VW all", "CDLI"]
        print(cmp_.loc[cmp_.index >= ix["VW all"].index.min()].round(2).to_string())

    bar = di.credit_barometer(pos, ix, largest, args.start)
    pc = pos[pos["month_end"] > pd.Timestamp(args.start) - pd.offsets.QuarterEnd(1)]
    tot = pc.groupby("month_end")["cost"].sum()
    bar["marked < 80 % cost"] = pc[pc["price"] < 80].groupby("month_end")["cost"].sum().reindex(tot.index, fill_value=0) / tot * 100
    bar.to_csv(out / "credit_health_barometer.csv")
    cols = [c for c in ["marked < 80 % cost", "marked < 90 % cost", "PIK % par", "T4Q realized (cost) % (VW)",
                        "T4Q unrealized % (VW)"] if c in bar]
    print(f"\n=== Credit health barometer ({'European' if args.region == 'europe' else 'US'} direct lending in BDCs) ===")
    print(bar[cols].round(2).to_string())
    print(f"\nSaved in {out}")


if __name__ == "__main__":
    main()
