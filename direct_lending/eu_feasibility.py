#!/usr/bin/env python3
"""
eu_feasibility.py

Feasibility of European loan indices from Form N-PORT: European direct lending and European syndicated loans.

Input
    nport_out_eu/holdings_v2/     from nport_loans.py --europe (non-USD loans and USD loans of European borrowers)
    dl_out/ncen_advisers.csv, dl_out/ncen_advisers_by_cik.csv   optional, adviser and fund type (ncen_advisers.py)

Steps
    1. Latest filing per fund and report date
    2. Exchange rate convention: N-PORT reports the value in USD and the principal in the loan currency. The price
       in loan currency is value x rate / principal if the rate is quoted as currency units per USD, or
       value / rate / principal if quoted as USD per currency unit. The script chooses the convention under which
       identified (syndicated) loans are priced closest to par.
    3. Region: borrower country in Europe; other non-USD loans are reported separately
    4. Segments: syndicated (valid LoanX ID, ISIN, FIGI or CUSIP) and direct lending candidates (no valid identifier,
       fair value level 3, principal >= 250,000 in loan currency, funded, corporate, closed-end funds if N-CEN known)
    5. Per calendar quarter-end: loans, borrowers, funds, managers, market value by currency; concentration;
       syndicated loans held by at least two funds (needed for factor portfolios)

Usage
    python eu_feasibility.py
"""

import argparse
import re
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

EUROPE = {"AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU", "IE", "IT", "LV", "LT",
          "LU", "MT", "NL", "PL", "PT", "RO", "SK", "SI", "ES", "SE", "GB", "NO", "CH", "IS", "LI", "JE", "GG", "IM"}
EXCLUDE_RE = re.compile(
    r"MORTGAGE|REAL ESTATE|\bCRE\b|APARTMENT|PROPERTY|HOTEL|RECEIVABLE|EQUIPMENT|AIRCRAFT|AUTO LOAN|CONSUMER|"
    r"STUDENT|SOLAR|\bABL\b|ASSET[- ]BASED|SUPPLY CHAIN|TRADE FINANCE|REVOLV|\bREV\b|\bRCF\b|DELAYED DRAW|\bDDTL\b|"
    r"UNFUNDED|\bNAV\b|CLASS [A-Z] NOTE|[0-9A-F]{8}-[0-9A-F]{4}-", re.I)


def pct(x):
    return f"{x:.1%}"


def main() -> None:
    ap = argparse.ArgumentParser(description="Feasibility of European loan indices from N-PORT")
    ap.add_argument("--dir", default="nport_out_eu")
    ap.add_argument("--ncen-dir", default="dl_out")
    ap.add_argument("--out-dir", default="eu_feasibility")
    args = ap.parse_args()
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    pd.set_option("display.width", 220)
    pd.set_option("display.max_colwidth", 45)

    src = f"read_parquet('{(Path(args.dir) / 'holdings_v2').as_posix()}/**/*.parquet', union_by_name = true)"
    con = duckdb.connect()
    d = con.execute(f"""
        WITH h AS (SELECT * FROM {src}),
             latest AS (SELECT ACCESSION_NUMBER FROM (
                 SELECT ACCESSION_NUMBER, row_number() OVER (PARTITION BY FUND_KEY, REPORT_DATE
                        ORDER BY FILING_DATE DESC, ACCESSION_NUMBER DESC) AS rn
                 FROM (SELECT DISTINCT FUND_KEY, REPORT_DATE, ACCESSION_NUMBER, FILING_DATE FROM h)) WHERE rn = 1)
        SELECT FUND_KEY, SERIES_NAME, CAST(MONTH_END AS DATE) AS month_end, ISSUER_NAME, ISSUER_TITLE, KEY_TYPE, LOAN_KEY,
               upper(CURRENCY_CODE) AS cur, upper(INVESTMENT_COUNTRY) AS cty, EXCHANGE_RATE AS rate,
               CURRENCY_VALUE AS value_usd, BALANCE AS par, FAIR_VALUE_LEVEL AS fvl, ANNUALIZED_RATE AS coupon,
               IS_DEFAULT AS dflt, IS_UNFUNDED_OR_REVOLVER AS unfunded
        FROM h WHERE ACCESSION_NUMBER IN (SELECT ACCESSION_NUMBER FROM latest)""").df()
    d["month_end"] = pd.to_datetime(d["month_end"])
    print(f"Holdings (latest filings): {len(d):,}")

    # ---- 1. overview by currency and country (all holdings)
    d["region"] = np.where(d["cty"].isin(EUROPE), "Europe", "non-Europe")
    ov = d.groupby(["region", "cur"]).agg(holdings=("par", "size"), value_usd_bn=("value_usd", lambda x: x.sum() / 1e9),
                                          funds=("FUND_KEY", "nunique")).sort_values("value_usd_bn", ascending=False)
    print("\n=== 1. All holdings by region and currency (summed over report dates) ===")
    print(ov.head(15).round(2).to_string())
    big = (d.groupby(["SERIES_NAME"]).agg(holdings=("par", "size"), value_usd_bn=("value_usd", lambda x: x.sum() / 1e9))
           .sort_values("holdings", ascending=False).head(8))
    print("\nFunds with the most holdings (to spot platform loan portfolios):")
    print(big.round(2).to_string())

    # ---- 2. exchange rate convention
    usd = d["cur"].eq("USD")
    d["price_usd_basis"] = d["value_usd"] / d["par"] * 100
    d["price_mult"] = np.where(usd, d["price_usd_basis"], d["value_usd"] * d["rate"] / d["par"] * 100)
    d["price_div"] = np.where(usd, d["price_usd_basis"], d["value_usd"] / d["rate"] / d["par"] * 100)
    ident = d["KEY_TYPE"].isin(["LX", "ISIN", "FIGI"])
    chk = d[ident & ~usd & d["rate"].gt(0)]
    conv = chk.groupby("cur").agg(n=("par", "size"), median_rate=("rate", "median"),
                                  median_price_mult=("price_mult", "median"), median_price_div=("price_div", "median"))
    print("\n=== 2. Exchange rate convention: median price of identified non-USD loans ===")
    print(conv.sort_values("n", ascending=False).head(8).round(3).to_string())
    m_ok = (chk["price_mult"] - 99).abs().median() < (chk["price_div"] - 99).abs().median()
    d["price"] = d["price_mult"] if m_ok else d["price_div"]
    print(f"Chosen convention: {'value x rate / par (rate = currency units per USD)' if m_ok else 'value / rate / par (rate = USD per currency unit)'}")

    # ---- fund type and manager (N-CEN), if available
    d["closed_end"], d["manager"] = np.nan, d["SERIES_NAME"].fillna("").str.upper().str.split().str[0]
    a1, a2 = Path(args.ncen_dir) / "ncen_advisers.csv", Path(args.ncen_dir) / "ncen_advisers_by_cik.csv"
    if a1.exists():
        s1 = pd.read_csv(a1, dtype=str).set_index("SERIES_ID")
        s2 = pd.read_csv(a2, dtype=str).set_index("CIK") if a2.exists() else pd.DataFrame()
        cik = d["FUND_KEY"].str.extract(r"^CIK0*(\d+)_", expand=False)
        adv = s1["ADVISER"].reindex(d["FUND_KEY"]).to_numpy()
        typ = s1["INVESTMENT_COMPANY_TYPE"].reindex(d["FUND_KEY"]).to_numpy()
        if len(s2):
            adv = np.where(pd.isna(adv), s2["ADVISER"].reindex(cik).to_numpy(), adv)
            typ = np.where(pd.isna(typ), s2["INVESTMENT_COMPANY_TYPE"].reindex(cik).to_numpy(), typ)
        d["manager"] = pd.Series(adv, index=d.index).fillna(d["manager"]).str.upper().str.split().str[0]
        d["closed_end"] = pd.Series(typ, index=d.index).fillna("").str.upper().str.contains("N-2")
    else:
        print("Note: no N-CEN adviser file found; managers approximated by the first word of the fund name.")

    # ---- 3. segments (European borrowers, calendar quarter-ends)
    eu = d[d["region"].eq("Europe") & d["month_end"].dt.month.isin([3, 6, 9, 12]) & d["price"].between(1, 150)].copy()
    text = (eu["ISSUER_TITLE"].fillna("") + " " + eu["ISSUER_NAME"].fillna("")).str.upper()
    lk = eu["LOAN_KEY"].fillna("").astype(str)
    eu["cusip_placeholder"] = lk.map(lambda k: k.startswith("CUSIP:") and len(set(k[6:])) == 1)
    no_id = eu["KEY_TYPE"].eq("NM") | eu["cusip_placeholder"]
    eu["segment"] = np.where(~no_id, "syndicated", "other")
    par_loc = eu["par"]
    dl = (no_id & eu["fvl"].astype(str).eq("3") & par_loc.ge(250_000) & ~eu["unfunded"].fillna(False).astype(bool)
          & ~text.str.contains(EXCLUDE_RE)
          & (eu["coupon"].fillna(0).ge(2) | eu["dflt"].fillna(False).astype(bool) | (eu["coupon"].fillna(0).le(0.01) & eu["price"].lt(90))))
    if eu["closed_end"].notna().any():
        dl &= eu["closed_end"].fillna(False).astype(bool)
    eu.loc[dl, "segment"] = "direct lending"
    eu["borrower"] = eu["ISSUER_NAME"].fillna("").str.upper().str.replace(r"[^A-Z0-9 ]", " ", regex=True).str.split().str[:2].str.join(" ")

    def summary(seg: pd.DataFrame) -> pd.DataFrame:
        g = seg.groupby("month_end")
        s = g.agg(loans=("LOAN_KEY", "nunique"), borrowers=("borrower", "nunique"), funds=("FUND_KEY", "nunique"),
                  managers=("manager", "nunique"), value_usd_bn=("value_usd", lambda x: x.sum() / 1e9),
                  median_price=("price", "median"), median_coupon=("coupon", "median"))
        for c in ["EUR", "GBP", "USD"]:
            s[f"share_{c}"] = seg[seg["cur"].eq(c)].groupby("month_end")["value_usd"].sum().reindex(s.index, fill_value=0) / g["value_usd"].sum()
        mv = seg.groupby(["month_end", "manager"])["value_usd"].sum()
        s["largest_manager_share"] = mv.groupby(level=0).max() / mv.groupby(level=0).sum()
        s["largest_manager"] = mv.groupby(level=0).idxmax().map(lambda x: x[1])
        return s

    for name in ["direct lending", "syndicated"]:
        seg = eu[eu["segment"].eq(name)]
        if seg.empty:
            print(f"\n=== {name}: no holdings ===")
            continue
        s = summary(seg)
        s.to_csv(out / f"{name.replace(' ', '_')}_by_quarter.csv")
        print(f"\n=== 3. European {name} at calendar quarter-ends ===")
        print(s.round({"value_usd_bn": 2, "median_price": 2, "median_coupon": 2, "share_EUR": 2, "share_GBP": 2,
                       "share_USD": 2, "largest_manager_share": 2}).to_string())

    # ---- 4. syndicated loans held by at least two funds (factor portfolios need breadth)
    syn = eu[eu["segment"].eq("syndicated")]
    if len(syn):
        nf = syn.groupby(["month_end", "LOAN_KEY"])["FUND_KEY"].nunique()
        two = (nf >= 2).groupby(level=0).sum()
        print("\n=== 4. European syndicated loans held by at least two funds, per quarter-end ===")
        print(two.to_string())

    # ---- 5. largest direct lending managers and samples
    dls = eu[eu["segment"].eq("direct lending")]
    if len(dls):
        last = dls[dls["month_end"] == dls["month_end"].max()]
        print("\n=== 5. Direct lending managers in the latest quarter ===")
        print(last.groupby("manager").agg(loans=("LOAN_KEY", "nunique"), value_usd_bn=("value_usd", lambda x: x.sum() / 1e9))
              .sort_values("value_usd_bn", ascending=False).head(20).round(3).to_string())
        dls.sample(min(50, len(dls)), random_state=1)[["SERIES_NAME", "ISSUER_NAME", "ISSUER_TITLE", "cur", "cty", "par", "price", "coupon"]] \
            .to_csv(out / "sample_direct_lending.csv", index=False)
    print(f"\nSaved in: {out} (by-quarter tables, sample_direct_lending.csv)")


if __name__ == "__main__":
    main()
