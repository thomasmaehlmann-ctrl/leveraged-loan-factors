#!/usr/bin/env python3
"""
dl_feasibility.py

Phase 1 of the direct lending project: feasibility of a US direct lending index from Form N-PORT.

Works on the cleaned individual holdings of the existing pipeline (nport_out/rekeyed, from nport_rekey.py).
Candidate direct lending positions are loans without any identifier (name key "NM"), valued at fair value
level 3 (syndicated loans are mostly level 2), with a plausible price, a minimum position size (to exclude
consumer and small-business loans from lending platforms) and a minimum coupon (to exclude unfunded
tranches that only pay a commitment fee). Revolvers, delayed-draw tranches, real estate, mortgage,
trade finance and similar positions are excluded by their titles and by the names of the funds.

Questions answered
    1. Size: number of candidate loans, funds and market value per quarter-end since 2019
    2. Ownership: held by one fund, by several funds of the same manager, or by several managers
    3. Concentration: share of the largest 1, 5 and 10 funds and managers in the candidate market value
    4. Characteristics: fair value level 3, floating rate, PIK, default, price, coupon, maturity,
       seniority from the titles (first lien, second lien, unitranche, ...)
    5. Tracking: share of fund-loan positions observed again three months later
    6. Reporting dates: share of value reported at calendar quarter-ends
    7. Largest funds by candidate market value (to see which fund types hold the loans)

"Manager" is approximated by the first word of the fund's series name; this is a rough proxy that a later
phase replaces by the adviser from Form N-CEN.

Usage
    python dl_feasibility.py
    python dl_feasibility.py --min-size 500000 --start 2019-10
"""

import argparse
from pathlib import Path

import duckdb
import pandas as pd

TEXT = "upper(coalesce(ISSUER_TITLE, '') || ' ' || coalesce(ISSUER_NAME, ''))"
EXCLUDE_RE = (r"MORTGAGE|REAL ESTATE|\bCRE\b|APARTMENT|MULTIFAMILY|HOTEL|PROPERTY|LAND LOAN|"
              r"RECEIVABLE|EQUIPMENT|AIRCRAFT|AUTO LOAN|CONSUMER|STUDENT|SOLAR|LITIGATION|"
              r"\bABL\b|ASSET[- ]BASED|WAREHOUSE|LETTER OF CREDIT|SUPPLY CHAIN|TRADE FINANCE|"
              r"FHLMC|FNMA|GNMA|FREDDIE|FANNIE|CONFORMING|"
              r"REVOLV|\bREV\b|\bRCF\b|DELAYED DRAW|\bDDTL\b|\bDD TL\b|UNFUNDED")
# funds whose loans are not corporate direct lending (mortgages, real estate, trade finance, municipal)
FUND_EXCLUDE_RE = r"MORTGAGE|REAL ESTATE|REIT|PROPERTY|MUNICIPAL|\bMUNI\b|TRADE FINANCE|INFRASTRUCTURE"
SENIORITY = {
    "first_lien": r"FIRST LIEN|1ST LIEN|1L\b|SENIOR SECURED|FIRST OUT",
    "unitranche": r"UNITRANCHE",
    "second_lien": r"SECOND LIEN|2ND LIEN|2L\b|LAST OUT",
    "subordinated": r"SUBORDINATED|MEZZANINE|\bMEZZ\b|JUNIOR",
    "delayed_draw": r"DELAYED DRAW|\bDDTL\b|\bDD TL\b",
    "revolver": r"REVOLV|\bRCF\b",
}


def pct(x: float) -> str:
    return f"{x:.1%}"


def main() -> None:
    ap = argparse.ArgumentParser(description="Feasibility of a direct lending index from N-PORT")
    ap.add_argument("--dir", default="nport_out")
    ap.add_argument("--min-size", type=float, default=250_000, help="minimum principal of a position in USD")
    ap.add_argument("--start", default="2019-09")
    ap.add_argument("--min-coupon", type=float, default=2.0,
                    help="minimum annualized rate in %% (lower rates are commitment fees on unfunded tranches)")
    ap.add_argument("--any-level", action="store_true",
                    help="do not require fair value level 3 (default: level 3 only, which removes syndicated loans)")
    ap.add_argument("--out-dir", default="dl_feasibility")
    args = ap.parse_args()

    src = (Path(args.dir) / "rekeyed").as_posix()
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    pd.set_option("display.width", 220)
    pd.set_option("display.max_columns", 30)
    con = duckdb.connect()

    sen_cols = ",\n".join(f"regexp_matches({TEXT}, '{p}') AS sen_{k}" for k, p in SENIORITY.items())
    raw = f"read_parquet('{src}/**/*.parquet', hive_partitioning = true, union_by_name = true)"
    have = set(con.execute(f"DESCRIBE SELECT * FROM {raw}").df()["column_name"])
    needed = {"FUND_KEY": "VARCHAR", "LOAN_KEY": "VARCHAR", "KEY_TYPE": "VARCHAR", "MONTH_END": "DATE",
              "ISSUER_NAME": "VARCHAR", "ISSUER_TITLE": "VARCHAR", "BALANCE": "DOUBLE", "CURRENCY_VALUE": "DOUBLE",
              "PRICE": "DOUBLE", "PRICE_PLAUSIBLE": "BOOLEAN", "FAIR_VALUE_LEVEL": "VARCHAR",
              "COUPON_TYPE": "VARCHAR", "ANNUALIZED_RATE": "DOUBLE", "IS_PIK": "BOOLEAN", "IS_DEFAULT": "BOOLEAN",
              "MATURITY_DATE": "DATE"}
    missing = [c for c in needed if c not in have]
    if missing:
        print("Note: columns not in the holdings, set to empty:", ", ".join(missing))
    sel = ", ".join(c if c in have else f"CAST(NULL AS {t}) AS {c}" for c, t in needed.items())
    # fund names from the original holdings (the cleaned holdings contain only the fund key)
    hv = Path(args.dir) / "holdings_v2"
    if "SERIES_NAME" in have:
        names = f"SELECT FUND_KEY, any_value(SERIES_NAME) AS SERIES_NAME FROM {raw} GROUP BY 1"
    elif hv.exists():
        names = (f"SELECT FUND_KEY, any_value(SERIES_NAME) AS SERIES_NAME FROM read_parquet("
                 f"'{hv.as_posix()}/**/*.parquet', union_by_name = true) GROUP BY 1")
    else:
        names = f"SELECT DISTINCT FUND_KEY, FUND_KEY AS SERIES_NAME FROM {raw}"
    con.execute(f"CREATE TABLE fund_names AS {names}")
    con.execute(f"""
        CREATE VIEW all_loans AS
        SELECT h.*, n.SERIES_NAME, CAST(h.MONTH_END AS DATE) AS m,
               upper(split_part(trim(coalesce(n.SERIES_NAME, h.FUND_KEY)), ' ', 1)) AS manager
        FROM (SELECT {sel} FROM {raw}) h LEFT JOIN fund_names n USING (FUND_KEY)
        WHERE h.PRICE_PLAUSIBLE AND CAST(h.MONTH_END AS DATE) >= DATE '{args.start}-01'
    """)
    con.execute(f"""
        CREATE TABLE cand AS
        SELECT *, {sen_cols}
        FROM all_loans
        WHERE KEY_TYPE = 'NM' AND BALANCE >= {args.min_size}
          AND NOT regexp_matches({TEXT}, '{EXCLUDE_RE}')
          AND NOT regexp_matches(upper(coalesce(SERIES_NAME, '')), '{FUND_EXCLUDE_RE}')
          AND coalesce(ANNUALIZED_RATE, 0) >= {args.min_coupon}
          {"" if args.any_level else "AND FAIR_VALUE_LEVEL = '3'"}
    """)

    # ------------------------------------------------------------------ 0. overview of the filter
    f = con.execute(f"""
        SELECT
          count(*) FILTER (WHERE KEY_TYPE = 'NM') AS nm_holdings,
          sum(CURRENCY_VALUE) FILTER (WHERE KEY_TYPE = 'NM') / 1e9 AS nm_value_bn,
          count(*) FILTER (WHERE KEY_TYPE = 'NM' AND BALANCE >= {args.min_size}) AS nm_large_holdings,
          sum(CURRENCY_VALUE) FILTER (WHERE KEY_TYPE = 'NM' AND BALANCE >= {args.min_size}) / 1e9 AS nm_large_value_bn,
          (SELECT count(*) FROM cand) AS cand_holdings,
          (SELECT sum(CURRENCY_VALUE) FROM cand) / 1e9 AS cand_value_bn,
          sum(CURRENCY_VALUE) / 1e9 AS all_loans_value_bn
        FROM all_loans""").df().T
    print("=== 0. Filter steps (holdings and market value summed over all report dates) ===")
    print(f.round(2).to_string(header=False))

    # ------------------------------------------------------------------ 1. size per quarter-end month
    size = con.execute("""
        SELECT m AS month_end, count(DISTINCT LOAN_KEY) AS loans, count(DISTINCT FUND_KEY) AS funds,
               count(DISTINCT manager) AS managers, sum(CURRENCY_VALUE) / 1e9 AS value_bn,
               median(BALANCE) / 1e6 AS median_position_mn
        FROM cand GROUP BY 1 ORDER BY 1""").df()
    size.to_csv(out / "size_by_month.csv", index=False)
    q = size[pd.to_datetime(size["month_end"]).dt.month.isin([3, 6, 9, 12])]
    print("\n=== 1. Candidate loans at calendar quarter-ends ===")
    print(q.round({"value_bn": 2, "median_position_mn": 2}).to_string(index=False))

    ex = con.execute("""
        WITH t AS (SELECT m, manager, sum(CURRENCY_VALUE) AS v, count(DISTINCT LOAN_KEY) AS loans,
                          count(DISTINCT FUND_KEY) AS funds FROM cand GROUP BY 1, 2),
             lg AS (SELECT manager FROM cand GROUP BY 1 ORDER BY sum(CURRENCY_VALUE) DESC LIMIT 1)
        SELECT m AS month_end, any_value((SELECT manager FROM lg)) AS largest_manager,
               sum(v) FILTER (WHERE manager IN (SELECT manager FROM lg)) / sum(v) AS share_largest_manager,
               sum(v) FILTER (WHERE manager NOT IN (SELECT manager FROM lg)) / 1e9 AS value_bn_ex_largest,
               count(DISTINCT manager) FILTER (WHERE manager NOT IN (SELECT manager FROM lg)) AS managers_ex_largest
        FROM t GROUP BY 1 ORDER BY 1""").df()
    ex.to_csv(out / "largest_manager_by_month.csv", index=False)
    qe = ex[pd.to_datetime(ex["month_end"]).dt.month.isin([3, 6, 9, 12])].copy()
    qe["share_largest_manager"] = qe["share_largest_manager"].map(pct)
    print("\n=== 1b. Largest manager overall: share of value, and the market without it ===")
    print(qe.round({"value_bn_ex_largest": 2}).to_string(index=False))

    # ------------------------------------------------------------------ 2. ownership structure
    own = con.execute("""
        WITH k AS (SELECT m, LOAN_KEY, count(DISTINCT FUND_KEY) AS nf, count(DISTINCT manager) AS nm,
                          sum(CURRENCY_VALUE) AS v FROM cand GROUP BY 1, 2)
        SELECT CASE WHEN nf = 1 THEN '1 fund'
                    WHEN nm = 1 THEN 'several funds, one manager'
                    ELSE 'several managers' END AS ownership,
               count(*) AS loan_months, sum(v) / 1e9 AS value_bn
        FROM k GROUP BY 1 ORDER BY 1""").df()
    own["share_value"] = own["value_bn"] / own["value_bn"].sum()
    print("\n=== 2. Ownership of candidate loans (loan-months, all report dates) ===")
    print(own.round(3).to_string(index=False))

    # ------------------------------------------------------------------ 3. concentration
    def top_shares(level: str, label: str) -> pd.DataFrame:
        return con.execute(f"""
            WITH g AS (SELECT m, {level} AS unit, any_value(SERIES_NAME) AS name, sum(CURRENCY_VALUE) AS v
                       FROM cand GROUP BY 1, 2),
                 r AS (SELECT *, row_number() OVER (PARTITION BY m ORDER BY v DESC) AS rk,
                              sum(v) OVER (PARTITION BY m) AS tot FROM g)
            SELECT m AS month_end,
                   sum(v) FILTER (WHERE rk = 1) / any_value(tot) AS top1_{label},
                   sum(v) FILTER (WHERE rk <= 5) / any_value(tot) AS top5_{label},
                   sum(v) FILTER (WHERE rk <= 10) / any_value(tot) AS top10_{label},
                   any_value(name) FILTER (WHERE rk = 1) AS largest_{label}
            FROM r GROUP BY m ORDER BY m""").df()
    conc = top_shares("FUND_KEY", "fund").merge(
        top_shares("manager", "manager").drop(columns="largest_manager"), on="month_end")
    conc.to_csv(out / "concentration_by_month.csv", index=False)
    qc = conc[pd.to_datetime(conc["month_end"]).dt.month.isin([3, 6, 9, 12])].copy()
    for c in ["top1_fund", "top5_fund", "top10_fund", "top1_manager", "top5_manager", "top10_manager"]:
        qc[c] = qc[c].map(pct)
    print("\n=== 3. Concentration of candidate market value at calendar quarter-ends ===")
    print(qc.to_string(index=False))

    # ------------------------------------------------------------------ 4. characteristics
    sen_avg = ", ".join(f"avg(CAST(sen_{k} AS DOUBLE)) AS {k}" for k in SENIORITY)
    ch = con.execute(f"""
        SELECT year(m) AS year,
               avg(CAST(FAIR_VALUE_LEVEL = '3' AS DOUBLE)) AS level3,
               avg(CAST(upper(COUPON_TYPE) LIKE 'FLOAT%' AS DOUBLE)) AS floating,
               avg(CAST(IS_PIK AS DOUBLE)) AS pik,
               avg(CAST(IS_DEFAULT AS DOUBLE)) AS in_default,
               median(PRICE) AS price_median,
               quantile_cont(PRICE, 0.10) AS price_p10,
               median(ANNUALIZED_RATE) AS coupon_median,
               median(date_diff('day', m, CAST(MATURITY_DATE AS DATE)) / 365.25) AS years_to_maturity,
               {sen_avg}
        FROM cand GROUP BY 1 ORDER BY 1""").df()
    ch.to_csv(out / "characteristics_by_year.csv", index=False)
    print("\n=== 4. Characteristics of candidate holdings by year (shares of holdings) ===")
    print(ch.round(3).to_string(index=False))

    # ------------------------------------------------------------------ 5. tracking across quarters
    tr = con.execute("""
        WITH p AS (SELECT DISTINCT FUND_KEY, LOAN_KEY, m FROM cand),
             f AS (SELECT DISTINCT FUND_KEY, m FROM all_loans)
        SELECT year(p.m) AS year, count(*) AS positions,
               avg(CAST(EXISTS (SELECT 1 FROM p p2 WHERE p2.FUND_KEY = p.FUND_KEY AND p2.LOAN_KEY = p.LOAN_KEY
                                AND p2.m = last_day(p.m + INTERVAL 3 MONTH)) AS DOUBLE)) AS seen_again_3m,
               avg(CAST(EXISTS (SELECT 1 FROM f WHERE f.FUND_KEY = p.FUND_KEY
                                AND f.m = last_day(p.m + INTERVAL 3 MONTH)) AS DOUBLE)) AS fund_reports_3m
        FROM p GROUP BY 1 ORDER BY 1""").df()
    tr["seen_again_if_fund_reports"] = tr["seen_again_3m"] / tr["fund_reports_3m"]
    print("\n=== 5. Tracking: same fund reports the same loan three months later ===")
    print(tr.round(3).to_string(index=False))

    # ------------------------------------------------------------------ 6. reporting dates
    rd = con.execute("""
        SELECT month(m) IN (3, 6, 9, 12) AS calendar_quarter_end, sum(CURRENCY_VALUE) / 1e9 AS value_bn,
               count(DISTINCT FUND_KEY) AS funds
        FROM cand GROUP BY 1""").df()
    rd["share_value"] = rd["value_bn"] / rd["value_bn"].sum()
    print("\n=== 6. Value reported at calendar quarter-ends vs. other month-ends ===")
    print(rd.round(3).to_string(index=False))

    # ------------------------------------------------------------------ 7. largest funds
    top = con.execute("""
        WITH last_year AS (SELECT * FROM cand WHERE m > (SELECT max(m) FROM cand) - INTERVAL 12 MONTH),
             latest AS (SELECT FUND_KEY, max(m) AS lm FROM last_year GROUP BY 1)
        SELECT any_value(c.SERIES_NAME) AS fund, any_value(c.manager) AS manager, c.m AS report_date,
               count(*) AS loans, sum(c.CURRENCY_VALUE) / 1e9 AS dl_value_bn,
               avg(CAST(c.FAIR_VALUE_LEVEL = '3' AS DOUBLE)) AS level3
        FROM last_year c JOIN latest l ON c.FUND_KEY = l.FUND_KEY AND c.m = l.lm
        GROUP BY c.FUND_KEY, c.m ORDER BY dl_value_bn DESC LIMIT 25""").df()
    top.to_csv(out / "largest_funds.csv", index=False)
    print("\n=== 7. Largest funds by candidate market value (latest report within the last 12 months) ===")
    print(top.round({"dl_value_bn": 3, "level3": 3}).to_string(index=False))

    # sample of titles for a manual check of the filter
    smp = con.execute("""
        SELECT ISSUER_NAME, ISSUER_TITLE, SERIES_NAME, BALANCE, PRICE, ANNUALIZED_RATE, FAIR_VALUE_LEVEL
        FROM cand USING SAMPLE 60 ROWS (reservoir, 1)""").df()
    smp.to_csv(out / "sample_positions.csv", index=False)
    print(f"\nRandom sample of 60 candidate positions for a manual check: {out / 'sample_positions.csv'}")
    print(f"Results saved in: {out}")


if __name__ == "__main__":
    main()
