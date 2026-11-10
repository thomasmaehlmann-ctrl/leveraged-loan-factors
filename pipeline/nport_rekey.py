#!/usr/bin/env python3
"""
nport_rekey.py
==============

Second step after nport_loans.py. Works directly on nport_out/holdings_v2
(no new download, no new unzipping) and creates a cleaned panel
loan_price_panel_v2.parquet with the same structure as loan_price_panel.parquet.

Improvements over the first panel
---------------------------------
1. LoanX IDs are additionally extracted from issuer name and title
   (e.g. "Redstone_TL_LX194111", "LX173260T/L BI LO LLC").
2. Placeholder CUSIPs (999999999, 000000000, ...) are discarded.
3. US and Canadian ISINs are mapped to their CUSIP, so that the same loan does
   not appear twice under "ISIN" and "CUSIP".
4. Crosswalk: holdings that carry a LoanX ID AND a CUSIP/ISIN/FIGI provide the
   mapping. All holdings with this CUSIP/ISIN/FIGI then receive the LX key, even if
   the reporting fund itself does not report a LoanX ID.
   With several candidates the most frequent mapping wins (counts are recorded).
5. Consumer and platform loans (Prosper, LendingClub, Block, ...) are excluded,
   but only for holdings without any identifier (name keys).

Outputs (in --out-dir)
----------------------
    loan_price_panel_v2.parquet     panel loan x month (columns as before, plus n_old_keys)
    loan_id_crosswalk.parquet       mapping CUSIP/ISIN/FIGI -> LoanX ID with frequencies
    rekeyed/                        cleaned individual holdings, partitioned by month

Usage
-----
    pip install duckdb pandas pyarrow
    python nport_rekey.py
    python nport_loan_returns.py --panel nport_out/loan_price_panel_v2.parquet --base-source sofr
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

import pandas as pd


def sql_path(p: Path) -> str:
    return p.resolve().as_posix().replace("'", "''")


TEXT = "upper(coalesce(ISSUER_NAME, '') || ' ' || coalesce(ISSUER_TITLE, ''))"
SUFFIXES = (r"\b(INC|INCORPORATED|LLC|L L C|CORP|CORPORATION|CO|COMPANY|LTD|LIMITED|LP|L P|"
            r"PLC|SA|SARL|S A R L|BV|GMBH|AG|HOLDINGS?|HOLDCO|GROUP|THE)\b")
# long loan IDs (not decimals such as "0.00000000"), platform suffixes, application numbers
PLATFORM_RE = r"(^|[^0-9.])[0-9]{6,}|FTS\.B|APP-[0-9]+"


def main() -> None:
    ap = argparse.ArgumentParser(description="Merge loan keys and rebuild the panel")
    ap.add_argument("--out-dir", default="nport_out")
    ap.add_argument("--memory-limit", default="4GB")
    ap.add_argument("--temp-dir", default=None, help="folder for DuckDB spill files")
    ap.add_argument("--include-unfunded", action="store_true")
    args = ap.parse_args()

    import duckdb

    out_dir = Path(args.out_dir)
    hold_dir = out_dir / "holdings_v2"
    if not list(hold_dir.glob("*/part-*.parquet")):
        sys.exit(f"No data found in {hold_dir}.")
    tmp = Path(args.temp_dir) if args.temp_dir else out_dir / "_duckdb_tmp"
    tmp.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect()
    con.execute(f"SET memory_limit='{args.memory_limit}'")
    con.execute(f"SET temp_directory='{sql_path(tmp)}'")
    con.execute("SET preserve_insertion_order=false")

    pattern = sql_path(hold_dir) + "/*/part-*.parquet"
    con.execute(f"CREATE VIEW h AS SELECT * FROM read_parquet('{pattern}', union_by_name=true)")

    # --- 1. Amendments: per fund and report date keep only the latest version
    print("Handling amendments ...")
    con.execute("""
        CREATE TEMP TABLE latest AS
        SELECT ACCESSION_NUMBER FROM (
            SELECT DISTINCT FUND_KEY, REPORT_DATE, ACCESSION_NUMBER, FILING_DATE FROM h)
        QUALIFY row_number() OVER (
            PARTITION BY FUND_KEY, REPORT_DATE
            ORDER BY FILING_DATE DESC NULLS LAST, ACCESSION_NUMBER DESC) = 1
    """)

    # --- 2. Clean identifiers per holding
    con.execute(f"""
        CREATE VIEW hy AS
        WITH a AS (
            SELECT *,
                CASE WHEN regexp_full_match(upper(trim(LOANX_ID)), 'LX[0-9]{{6}}')
                     THEN upper(trim(LOANX_ID)) END                                   AS lx_own,
                nullif(regexp_extract({TEXT}, 'LX([0-9]{{6}})([^0-9]|$)', 1), '')     AS lx_txt,
                CASE WHEN regexp_full_match(upper(trim(ISIN)), '[A-Z]{{2}}[0-9A-Z]{{9}}[0-9]')
                     THEN upper(trim(ISIN)) END                                       AS isin_v,
                CASE WHEN regexp_full_match(upper(trim(FIGI)), 'BBG[0-9A-Z]{{9}}')
                     THEN upper(trim(FIGI)) END                                       AS figi_v,
                CASE WHEN KEY_TYPE = 'CUSIP' THEN substr(LOAN_KEY, 7) END             AS cusip_raw,
                nullif(regexp_extract({TEXT}, '(BL[0-9]{{7}})', 1), '')               AS bl_id
            FROM h
            WHERE ACCESSION_NUMBER IN (SELECT ACCESSION_NUMBER FROM latest)
        )
        SELECT *,
            coalesce(lx_own, 'LX' || lx_txt)                                          AS lx_any,
            coalesce(
                CASE WHEN cusip_raw IS NOT NULL
                      AND length(replace(cusip_raw, substr(cusip_raw, 1, 1), '')) > 0
                     THEN cusip_raw END,
                CASE WHEN substr(isin_v, 1, 2) IN ('US', 'CA') THEN substr(isin_v, 3, 9) END
            )                                                                         AS cusip_v
        FROM a
    """)

    # --- 3. Crosswalk CUSIP / non-US ISIN / FIGI -> LoanX ID
    print("Building crosswalk to LoanX IDs ...")
    con.execute("""
        CREATE TEMP TABLE xw AS
        WITH pairs AS (
            SELECT 'CUSIP' AS id_type, cusip_v AS id, lx_any AS lx FROM hy
              WHERE lx_any IS NOT NULL AND cusip_v IS NOT NULL
            UNION ALL
            SELECT 'ISIN', isin_v, lx_any FROM hy
              WHERE lx_any IS NOT NULL AND isin_v IS NOT NULL AND cusip_v IS NULL
            UNION ALL
            SELECT 'FIGI', figi_v, lx_any FROM hy
              WHERE lx_any IS NOT NULL AND figi_v IS NOT NULL
        ),
        cnt AS (SELECT id_type, id, lx, count(*) AS n FROM pairs GROUP BY ALL)
        SELECT id_type, id,
               arg_max(lx, n)  AS lx,
               count(*)        AS n_lx_candidates,
               max(n)          AS n_best,
               sum(n)          AS n_total
        FROM cnt GROUP BY id_type, id
    """)
    con.execute(f"COPY xw TO '{sql_path(out_dir / 'loan_id_crosswalk.parquet')}' (FORMAT PARQUET)")
    n_xw, n_amb = con.execute(
        "SELECT count(*), count(*) FILTER (WHERE n_lx_candidates > 1) FROM xw").fetchone()
    print(f"  {n_xw:,} mappings, of which {n_amb:,} with several LX candidates")

    # --- 4. New key
    con.execute(f"""
        CREATE VIEW hz AS
        WITH j AS (
            SELECT hy.*,
                coalesce(hy.lx_any, xc.lx, xi.lx, xf.lx) AS lx_final,
                CASE WHEN hy.lx_own IS NOT NULL THEN 'LX_own'
                     WHEN hy.lx_any IS NOT NULL THEN 'LX_text'
                     WHEN coalesce(xc.lx, xi.lx, xf.lx) IS NOT NULL THEN 'LX_crosswalk'
                END AS lx_source
            FROM hy
            LEFT JOIN xw xc ON xc.id_type = 'CUSIP' AND xc.id = hy.cusip_v
            LEFT JOIN xw xi ON xi.id_type = 'ISIN'  AND xi.id = hy.isin_v
            LEFT JOIN xw xf ON xf.id_type = 'FIGI'  AND xf.id = hy.figi_v
        ),
        k AS (
            SELECT *,
                CASE WHEN lx_final IS NOT NULL THEN 'LX:'    || lx_final
                     WHEN cusip_v  IS NOT NULL THEN 'CUSIP:' || cusip_v
                     WHEN isin_v   IS NOT NULL THEN 'ISIN:'  || isin_v
                     WHEN figi_v   IS NOT NULL THEN 'FIGI:'  || figi_v
                     ELSE 'NM:' || trim(regexp_replace(regexp_replace(
                              regexp_replace(upper(coalesce(ISSUER_NAME, '')), '[^A-Z0-9]+', ' ', 'g'),
                              '{SUFFIXES}', ' ', 'g'), ' +', ' ', 'g'))
                          || '|' || coalesce(strftime(CAST(MATURITY_DATE AS DATE), '%Y-%m-%d'), 'NA')
                END AS NEW_KEY
            FROM j
        )
        SELECT *,
            split_part(NEW_KEY, ':', 1) AS NEW_KEY_TYPE,
            (NEW_KEY LIKE 'NM:%' AND regexp_matches({TEXT}, '{PLATFORM_RE}')) AS IS_PLATFORM
        FROM k
    """)

    # --- 5. Write cleaned holdings partitioned by month
    rk_dir = out_dir / "rekeyed"
    if rk_dir.exists():
        shutil.rmtree(rk_dir)
    print("Writing cleaned holdings ...")
    con.execute(f"""
        COPY (
            SELECT NEW_KEY AS LOAN_KEY, NEW_KEY_TYPE AS KEY_TYPE, lx_source, LOAN_KEY AS OLD_KEY,
                   lx_final AS LOANX_ID, isin_v AS ISIN, figi_v AS FIGI, cusip_v AS CUSIP, bl_id AS BL_ID,
                   ACCESSION_NUMBER, FUND_KEY, MONTH_END, REPORT_DATE, ISSUER_NAME, ISSUER_TITLE,
                   MATURITY_DATE, BALANCE, CURRENCY_VALUE, PRICE, ANNUALIZED_RATE, IS_DEFAULT, IS_PIK,
                   IS_UNFUNDED_OR_REVOLVER, PRICE_PLAUSIBLE, FAIR_VALUE_LEVEL,
                   strftime(CAST(MONTH_END AS DATE), '%Y-%m') AS month
            FROM hz
            WHERE NOT IS_PLATFORM AND MONTH_END IS NOT NULL
        ) TO '{sql_path(rk_dir)}' (FORMAT PARQUET, PARTITION_BY (month))
    """)

    # --- 6. Panel month by month
    unf = "" if args.include_unfunded else "AND NOT IS_UNFUNDED_OR_REVOLVER"
    panel_sql = f"""
        SELECT LOAN_KEY, MONTH_END,
               median(PRICE)              AS price_median,
               avg(PRICE)                 AS price_mean,
               stddev_samp(PRICE)         AS price_std,
               min(PRICE)                 AS price_min,
               max(PRICE)                 AS price_max,
               count(DISTINCT FUND_KEY)   AS n_funds,
               sum(BALANCE)               AS par_total,
               sum(CURRENCY_VALUE)        AS value_total,
               any_value(ISSUER_NAME)     AS issuer_name,
               any_value(ISSUER_TITLE)    AS issue_title,
               any_value(KEY_TYPE)        AS key_type,
               any_value(LOANX_ID)        AS loanx_id,
               any_value(FIGI)            AS figi,
               any_value(ISIN)            AS isin,
               any_value(CUSIP)           AS cusip,
               any_value(BL_ID)           AS bl_id,
               mode(MATURITY_DATE)        AS maturity,
               median(ANNUALIZED_RATE)    AS coupon_median,
               bool_or(IS_DEFAULT)        AS any_default,
               bool_or(IS_PIK)            AS any_pik,
               mode(FAIR_VALUE_LEVEL)     AS fv_level_mode,
               count(DISTINCT OLD_KEY)    AS n_old_keys
        FROM read_parquet(?)
        WHERE PRICE_PLAUSIBLE {unf}
        GROUP BY LOAN_KEY, MONTH_END
    """
    parts_dir = out_dir / "panel_parts_v2"
    if parts_dir.exists():
        shutil.rmtree(parts_dir)
    parts_dir.mkdir(parents=True)
    months = sorted(p for p in rk_dir.glob("month=*") if p.is_dir())
    print(f"Building panel for {len(months)} months ...")
    for mdir in months:
        files = [f.resolve().as_posix() for f in mdir.glob("*.parquet")]
        df = con.execute(panel_sql, [files]).df()
        df.to_parquet(parts_dir / f"{mdir.name.split('=')[1]}.parquet", index=False)

    panel_path = out_dir / "loan_price_panel_v2.parquet"
    con.execute(f"COPY (SELECT * FROM read_parquet('{sql_path(parts_dir)}/*.parquet', union_by_name=true)) "
                f"TO '{sql_path(panel_path)}' (FORMAT PARQUET)")

    # --- 7. Overview
    p = f"read_parquet('{sql_path(panel_path)}')"
    old = f"read_parquet('{sql_path(out_dir / 'loan_price_panel.parquet')}')"
    print("\n=== Summary ===")
    n_platform = con.execute("SELECT count(*) FROM hz WHERE IS_PLATFORM").fetchone()[0]
    print(f"Excluded platform/consumer loans (holdings): {n_platform:,}")
    print("\nOrigin of LoanX IDs (holdings):")
    print(con.execute(f"""
        SELECT coalesce(lx_source, 'no LX') AS origin, count(*) AS holdings
        FROM read_parquet('{sql_path(rk_dir)}/*/*.parquet', hive_partitioning=true)
        GROUP BY 1 ORDER BY 2 DESC""").df().to_string(index=False))
    print("\nUnique loans per key type (only loans held by >= 2 funds at least once):")
    q_new = f"""
        SELECT key_type, count(*) AS loans FROM (
            SELECT LOAN_KEY, any_value(key_type) AS key_type, max(n_funds) AS mx
            FROM {p} GROUP BY LOAN_KEY) WHERE mx >= 2 GROUP BY 1 ORDER BY 2 DESC"""
    print(con.execute(q_new).df().to_string(index=False))
    if (out_dir / "loan_price_panel.parquet").exists():
        n_old = con.execute(f"""SELECT count(*) FROM (SELECT LOAN_KEY FROM {old}
                                 GROUP BY LOAN_KEY HAVING max(n_funds) >= 2)""").fetchone()[0]
        n_new = con.execute(f"""SELECT count(*) FROM (SELECT LOAN_KEY FROM {p}
                                 GROUP BY LOAN_KEY HAVING max(n_funds) >= 2)""").fetchone()[0]
        print(f"\nLoans with >= 2 funds: before {n_old:,}, after {n_new:,}")
    print("\nLoans per quarter-end (>= 2 funds in the month, last 8):")
    print(con.execute(f"""
        SELECT * FROM (
            SELECT CAST(MONTH_END AS DATE) AS month_end,
                   count(*) FILTER (WHERE n_funds >= 2) AS loans,
                   count(*) FILTER (WHERE n_funds >= 2 AND key_type = 'LX') AS of_which_lx
            FROM {p} WHERE month(MONTH_END) IN (3, 6, 9, 12)
            GROUP BY 1 ORDER BY 1 DESC LIMIT 8) ORDER BY month_end""").df().to_string(index=False))
    con.close()
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
