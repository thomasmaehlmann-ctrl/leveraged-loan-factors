#!/usr/bin/env python3
"""
dl_panel.py

Phase 2 of the direct lending project: a clean quarterly panel of direct lending positions from N-PORT.

Input
    nport_out/holdings_v2/      individual loan holdings from nport_loans.py (all fields, incl. coupon type)
    dl_out/ncen_advisers.csv    optional: fund series -> adviser from ncen_advisers.py
    manager_overrides.csv       optional: columns SERIES_NAME_CONTAINS, MANAGER (manual corrections)

Steps
    1. Latest filing per fund and report date (amendments replace originals)
    2. Direct lending candidates: no valid identifier (same rules as nport_rekey.py, so placeholder CUSIPs
       such as 000000000 count as no identifier), fair value level 3, funded term loans with a minimum
       size and coupon, excluding syndicated term loan B, platform loan pools, real estate, mortgage,
       trade finance and similar positions, and funds whose names indicate such strategies
    3. Calendar quarter-ends only; closed-end funds registered on Form N-2 (interval, tender offer and
       listed credit funds) unless --all-fund-types
    4. Manager of each fund: adviser from Form N-CEN, otherwise the first words of the fund name
    5. Borrower key: normalized issuer name (legal forms, facility words, dates and punctuation removed,
       truncated to 20 characters because some funds truncate names); a position is fund x borrower,
       with all tranches of the same borrower in the same fund combined
    6. Diagnostics: size, managers, tracking from quarter to quarter, largest positions

Output
    dl_out/dl_positions.parquet     fund x borrower x quarter-end: manager, par, value, price, coupon,
                                    coupon type, PIK, default, maturity, number of tranches
    dl_out/managers.csv             funds with their manager, for a manual check

Usage
    python dl_panel.py
"""

import argparse
import re
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

TEXT = "upper(coalesce(ISSUER_TITLE, '') || ' ' || coalesce(ISSUER_NAME, ''))"
EXCLUDE_RE = (
    r"MORTGAGE|REAL ESTATE|\bCRE\b|APARTMENT|MULTIFAMILY|HOTEL|PROPERTY|LAND LOAN|"
    r"RECEIVABLE|EQUIPMENT|AIRCRAFT|AUTO LOAN|CONSUMER|STUDENT|SOLAR|LITIGATION|"
    r"\bABL\b|ASSET[- ]BASED|WAREHOUSE|LETTER OF CREDIT|SUPPLY CHAIN|TRADE FINANCE|"
    r"FHLMC|FNMA|GNMA|FREDDIE|FANNIE|CONFORMING|"
    r"REVOLV|\bREV\b|\bRCF\b|DELAYED DRAW|DELAY DRAW|\bDDTL\b|\bDD TL\b|UNFUNDED|"
    r"TERM LOAN,? B\b|\bTLB\b|\bTL B\b|\bTLB[0-9]|"          # syndicated term loan B
    r"\bOWNER\b|RESORT|DATA CENTER|VISION FUND|\bNAV\b|FUND [IVX]+ L\.?P|CLASS [A-Z] NOTE|"  # real assets, fund finance, ABS
    r"[0-9A-F]{8}-[0-9A-F]{4}-|\.SR[0-9]+\.RF|"               # platform loan pools
    r"\bLX[0-9]{6}\b")                                        # LoanX IDs in the text
FUND_EXCLUDE_RE = (r"MORTGAGE|REAL ESTATE|REIT|PROPERTY|MUNICIPAL|\bMUNI\b|TRADE FINANCE|INFRASTRUCTURE|"
                   r"ALTERNATIVE LENDING|COMMUNITY DEVELOPMENT|IMPACT")

DROP_WORDS = {
    "TERM", "LOAN", "LOANS", "TL", "TLA", "FIRST", "SECOND", "1ST", "2ND", "LIEN", "1L", "2L", "SENIOR",
    "SECURED", "UNITRANCHE", "INCREMENTAL", "AMENDMENT", "AMENDED", "AMD", "AM", "TRANCHE", "FACILITY",
    "USD", "DOLLAR", "NEW", "ADD", "ON", "ADDON", "REFI", "REFINANCING", "EXIT", "INITIAL", "CLOSING",
    "DATE", "DELAYED", "DRAW", "OUT", "LAST", "THE", "AND", "OF", "DBA",
    "LLC", "LL", "INC", "CORP", "CORPORATION", "CO", "COS", "COMPANY", "LP", "LTD", "LIMITED", "SARL", "BV",
    "GMBH", "PLC", "HOLDINGS", "HOLDING", "HLDGS", "HOLDCO", "TOPCO", "MIDCO", "BIDCO", "OPCO", "BUYER",
    "PARENT", "INTERMEDIATE", "ACQUISITION", "ACQUIROR", "ACQUIRER", "PURCHASER", "MERGER", "SUB", "GROUP",
    "INTERNATIONAL", "INTL",
}


def normalize(name: str) -> str:
    s = (name or "").upper().split(" / ")[0].split("/ ")[0]
    s = re.sub(r"\(.*?\)", " ", s)                          # remarks in brackets, e.g. (Co-invest)
    s = re.sub(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b", " ", s)       # dates
    s = re.sub(r"\b(19|20)\d{2}\b", " ", s)                  # years
    s = re.sub(r"SOFR\s*\+?\s*\d+|L\s*\+\s*\d+", " ", s)      # spreads
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    words = [w for w in s.split() if w not in DROP_WORDS and len(w) > 1 and not w.isdigit()
             and not re.fullmatch(r"(AMD|AM|TL|TLA|TRANCHE|DDTL)\d+|\d+(ST|ND|RD|TH)", w)]
    return " ".join(words)[:20].strip()


GENERIC_FIRST = {"FIRST", "BLUE", "NEW", "GOLDEN", "MOUNT", "SIERRA", "PACIFIC", "NORTHERN", "AMERICAN", "GLOBAL",
                 "CAPITAL", "THE", "MA", "CIM", "WESTERN", "NATIONAL", "PRINCIPAL", "LIQUID", "PORTFOLIO", "FLAT",
                 "BENEFIT", "JOHN", "T", "LORD", "EATON", "MORGAN", "WELLS", "GOLDMAN", "HAMILTON", "NEUBERGER"}


def manager_family(name: str) -> str:
    """Adviser family: first word of the adviser name (two words if the first is generic), so that
    e.g. 'EAGLE POINT CREDIT MANAGEMENT LLC' and 'EAGLE POINT INCOME MANAGEMENT LLC' form one manager."""
    w = re.sub(r"[^A-Z0-9 ]", " ", str(name or "").upper()).split()
    if not w:
        return ""
    return " ".join(w[:2]) if w[0] in GENERIC_FIRST and len(w) > 1 else w[0]


def main() -> None:
    ap = argparse.ArgumentParser(description="Direct lending position panel from N-PORT")
    ap.add_argument("--dir", default="nport_out")
    ap.add_argument("--out-dir", default="dl_out")
    ap.add_argument("--start", default="2019-09")
    ap.add_argument("--min-size", type=float, default=250_000)
    ap.add_argument("--min-coupon", type=float, default=2.0,
                    help="minimum coupon in %%; loans in default, or with a coupon of zero and a mark below 90 (non-accrual), stay in")
    ap.add_argument("--overrides", default="manager_overrides.csv")
    ap.add_argument("--all-fund-types", action="store_true",
                    help="keep open-end funds (default: closed-end funds registered on Form N-2 only)")
    args = ap.parse_args()
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    pd.set_option("display.width", 220)
    pd.set_option("display.max_colwidth", 50)

    src = f"read_parquet('{(Path(args.dir) / 'holdings_v2').as_posix()}/**/*.parquet', union_by_name = true)"
    con = duckdb.connect()
    con.execute(f"CREATE VIEW h AS SELECT * FROM {src}")
    # 1. latest filing per fund and report date
    con.execute("""
        CREATE TABLE latest AS
        SELECT ACCESSION_NUMBER FROM (
            SELECT ACCESSION_NUMBER, row_number() OVER (PARTITION BY FUND_KEY, REPORT_DATE
                                                        ORDER BY FILING_DATE DESC, ACCESSION_NUMBER DESC) AS rn
            FROM (SELECT DISTINCT FUND_KEY, REPORT_DATE, ACCESSION_NUMBER, FILING_DATE FROM h))
        WHERE rn = 1""")
    # 2. candidates
    d = con.execute(f"""
        SELECT FUND_KEY, SERIES_NAME, CAST(MONTH_END AS DATE) AS month_end, ISSUER_NAME, ISSUER_TITLE,
               BALANCE, CURRENCY_VALUE, PRICE, ANNUALIZED_RATE, COUPON_TYPE, IS_PIK, IS_DEFAULT,
               CAST(MATURITY_DATE AS DATE) AS maturity
        FROM h
        WHERE ACCESSION_NUMBER IN (SELECT ACCESSION_NUMBER FROM latest)
          AND NOT regexp_full_match(upper(trim(coalesce(LOANX_ID, ''))), 'LX[0-9]{{6}}')
          AND NOT regexp_matches({TEXT}, 'LX[0-9]{{6}}([^0-9]|$)')
          AND NOT regexp_full_match(upper(trim(coalesce(ISIN, ''))), '[A-Z]{{2}}[0-9A-Z]{{9}}[0-9]')
          AND NOT regexp_full_match(upper(trim(coalesce(FIGI, ''))), 'BBG[0-9A-Z]{{9}}')
          AND NOT regexp_matches({TEXT}, 'BL[0-9]{{7}}')
          AND NOT (KEY_TYPE = 'CUSIP' AND length(replace(substr(LOAN_KEY, 7), substr(LOAN_KEY, 7, 1), '')) > 0)
          AND KEY_TYPE IN ('NM', 'CUSIP')
          AND PRICE_PLAUSIBLE AND NOT coalesce(IS_UNFUNDED_OR_REVOLVER, FALSE)
          AND FAIR_VALUE_LEVEL = '3' AND BALANCE >= {args.min_size}
          AND (coalesce(ANNUALIZED_RATE, 0) >= {args.min_coupon}      -- unfunded tranches paying a commitment fee
               OR coalesce(IS_DEFAULT, FALSE)                         -- (0 < coupon < min) are excluded; loans in
               OR (coalesce(ANNUALIZED_RATE, 0) <= 0.01 AND PRICE < 90))  -- default or non-accrual (coupon zero) stay in
          AND CAST(MONTH_END AS DATE) >= DATE '{args.start}-01'
          AND NOT regexp_matches({TEXT}, '{EXCLUDE_RE}')
          AND NOT regexp_matches(upper(coalesce(SERIES_NAME, '')), '{FUND_EXCLUDE_RE}')
    """).df()
    d["month_end"] = pd.to_datetime(d["month_end"])
    v_all = d["CURRENCY_VALUE"].sum()
    d = d[d["month_end"].dt.month.isin([3, 6, 9, 12])].copy()
    print(f"Candidate holdings: {len(d):,}; share of value at calendar quarter-ends: "
          f"{d['CURRENCY_VALUE'].sum() / v_all:.1%}")

    # 4. managers
    funds = d.groupby("FUND_KEY")["SERIES_NAME"].agg(lambda s: s.mode().iat[0] if len(s.mode()) else "").reset_index()
    adv_file, cik_file = out / "ncen_advisers.csv", out / "ncen_advisers_by_cik.csv"
    funds["ADVISER"], funds["IS_INTERVAL"], funds["INVESTMENT_COMPANY_TYPE"] = np.nan, np.nan, np.nan
    if adv_file.exists():
        cols = ["ADVISER", "IS_INTERVAL", "INVESTMENT_COMPANY_TYPE"]
        funds["INVESTMENT_COMPANY_TYPE"] = np.nan
        adv = pd.read_csv(adv_file, dtype=str).set_index("SERIES_ID")[cols]
        funds[cols] = adv.reindex(funds["FUND_KEY"]).to_numpy()
        if cik_file.exists():   # closed-end funds without a series ID: fund key "CIK<cik>_<name>"
            byc = pd.read_csv(cik_file, dtype=str).set_index("CIK")[cols]
            cik = funds["FUND_KEY"].str.extract(r"^CIK0*(\d+)_", expand=False)
            fill = byc.reindex(cik).to_numpy()
            miss = funds["ADVISER"].isna().to_numpy()
            funds.loc[miss, cols] = fill[miss]
    else:
        print("Note: dl_out/ncen_advisers.csv not found; managers from fund names only.")
    first_words = funds["SERIES_NAME"].fillna("").str.upper().str.replace(r"[^A-Z0-9 ]", " ", regex=True).str.split()
    funds["NAME_PROXY"] = first_words.apply(
        lambda w: " ".join(w[:2]) if w and w[0] in {"FIRST", "JOHN", "BLUE", "STONE", "T", "NORTHERN"} else (w[0] if w else ""))
    funds["MANAGER"] = funds["ADVISER"].fillna(funds["NAME_PROXY"])
    funds["MANAGER"] = funds["MANAGER"].map(manager_family)
    funds["MANAGER_SOURCE"] = np.where(funds["ADVISER"].notna(), "N-CEN", "fund name")
    ov = Path(args.overrides)
    if ov.exists():
        o = pd.read_csv(ov, dtype=str)
        for r in o.itertuples():
            mask = funds["SERIES_NAME"].str.upper().str.contains(str(r.SERIES_NAME_CONTAINS).upper(), regex=False, na=False)
            funds.loc[mask, ["MANAGER", "MANAGER_SOURCE"]] = [str(r.MANAGER).upper(), "override"]
    t = funds["INVESTMENT_COMPANY_TYPE"].fillna("").str.upper().str.replace(" ", "")
    funds["CLOSED_END"] = t.str.contains("N-2|N2|CLOSED") | funds["IS_INTERVAL"].astype(str).str.upper().isin(["TRUE", "Y"])
    vf = d.groupby("FUND_KEY")["CURRENCY_VALUE"].sum()
    funds["VALUE_BN"] = funds["FUND_KEY"].map(vf) / 1e9
    print("\nFund types (N-CEN), candidate value in USD bn summed over quarters:")
    print(funds.groupby(funds["INVESTMENT_COMPANY_TYPE"].fillna("unknown"))
          .agg(funds=("FUND_KEY", "size"), value_bn=("VALUE_BN", "sum")).round(2).to_string())
    if not args.all_fund_types:
        drop = funds[~funds["CLOSED_END"]].sort_values("VALUE_BN", ascending=False)
        print(f"\nExcluded as open-end or unknown type: {len(drop)} funds, {drop['VALUE_BN'].sum():.1f} bn; largest:")
        print(drop[["SERIES_NAME", "INVESTMENT_COMPANY_TYPE", "VALUE_BN"]].head(12).round(2).to_string(index=False))
        d = d[d["FUND_KEY"].isin(funds.loc[funds["CLOSED_END"], "FUND_KEY"])]
    d = d.merge(funds[["FUND_KEY", "MANAGER"]], on="FUND_KEY", how="left")

    # 5. borrower key and fund x borrower positions
    d["borrower"] = (d["ISSUER_NAME"].fillna("").where(d["ISSUER_NAME"].notna() & (d["ISSUER_NAME"] != ""),
                                                        d["ISSUER_TITLE"].fillna(""))).map(normalize)
    d = d[d["borrower"] != ""]
    d["coupon_x_par"] = d["ANNUALIZED_RATE"] * d["BALANCE"]
    d["floating"] = d["COUPON_TYPE"].fillna("").str.upper().str.match(r"FLOAT|VARIABLE")
    g = d.groupby(["FUND_KEY", "borrower", "month_end"])
    d = d.merge(funds[["FUND_KEY", "IS_INTERVAL"]], on="FUND_KEY", how="left")
    g = d.groupby(["FUND_KEY", "borrower", "month_end"])
    pos = g.agg(manager=("MANAGER", "first"), fund=("SERIES_NAME", "first"), interval_fund=("IS_INTERVAL", "first"),
                par=("BALANCE", "sum"), value=("CURRENCY_VALUE", "sum"), coupon_x_par=("coupon_x_par", "sum"),
                floating=("floating", "mean"), pik=("IS_PIK", "max"), default=("IS_DEFAULT", "max"),
                maturity=("maturity", "max"), n_tranches=("BALANCE", "size"),
                issuer_name=("ISSUER_NAME", "first"), issuer_title=("ISSUER_TITLE", "first")).reset_index()
    pos["price"] = pos["value"] / pos["par"] * 100
    pos["coupon"] = pos["coupon_x_par"] / pos["par"]
    pos = pos.drop(columns="coupon_x_par")
    pos.to_parquet(out / "dl_positions.parquet", index=False)
    funds.to_csv(out / "managers.csv", index=False)
    print("\nAdviser names combined into manager families (check in dl_out/managers.csv):")
    fam = funds[funds["ADVISER"].notna()].groupby("MANAGER")["ADVISER"].nunique()
    print(fam[fam > 1].sort_values(ascending=False).head(15).to_string())

    # 6. diagnostics
    print(f"\nPositions (fund x borrower x quarter): {len(pos):,}; funds {pos['FUND_KEY'].nunique():,}; "
          f"managers {pos['manager'].nunique():,}; managers from N-CEN: "
          f"{(funds['MANAGER_SOURCE'] == 'N-CEN').mean():.0%} of funds")
    s = pos.groupby("month_end").agg(positions=("par", "size"), borrowers=("borrower", "nunique"),
                                     funds=("FUND_KEY", "nunique"), managers=("manager", "nunique"),
                                     value_bn=("value", lambda x: x.sum() / 1e9),
                                     median_price=("price", "median"), median_coupon=("coupon", "median"),
                                     floating=("floating", "mean"), pik=("pik", "mean"), default=("default", "mean"),
                                     non_accrual=("coupon", lambda x: (x <= 0.01).mean()))
    lm = pos.groupby(["month_end", "manager"])["value"].sum()
    s["largest_manager_share"] = lm.groupby(level=0).max() / lm.groupby(level=0).sum()
    print("\n=== Panel by quarter-end ===")
    print(s.round(3).to_string())

    # tracking: same fund and borrower in the next quarter, if the fund reports then
    nxt = pos[["FUND_KEY", "borrower", "month_end"]].copy()
    nxt["month_end"] = nxt["month_end"] - pd.offsets.QuarterEnd(1)
    nxt["seen_next"] = True
    t = pos.merge(nxt, on=["FUND_KEY", "borrower", "month_end"], how="left")
    rep = pos[["FUND_KEY", "month_end"]].drop_duplicates()
    rep["month_end"] = rep["month_end"] - pd.offsets.QuarterEnd(1)
    rep["fund_reports_next"] = True
    t = t.merge(rep, on=["FUND_KEY", "month_end"], how="left")
    t = t[t["fund_reports_next"].eq(True)]
    tr = t.groupby(t["month_end"].dt.year)["seen_next"].apply(lambda x: x.notna().mean())
    print("\n=== Tracking: position seen again in the next quarter (if the fund reports) ===")
    print(tr.map("{:.1%}".format).to_string())

    lat = pos[pos["month_end"] == pos["month_end"].max()]
    print("\n=== Managers in the latest quarter ===")
    mg = lat.groupby("manager").agg(funds=("FUND_KEY", "nunique"), positions=("par", "size"),
                                    value_bn=("value", lambda x: x.sum() / 1e9)).sort_values("value_bn", ascending=False)
    print(mg.round(3).head(40).to_string())
    print("\n=== Largest positions in the latest quarter (check for non-direct-lending loans) ===")
    print(lat.nlargest(20, "value")[["fund", "issuer_name", "issuer_title", "par", "price", "coupon"]]
          .assign(par=lambda x: (x["par"] / 1e6).round(1)).to_string(index=False))
    print(f"\nSaved: {out / 'dl_positions.parquet'}, {out / 'managers.csv'}")


if __name__ == "__main__":
    main()
