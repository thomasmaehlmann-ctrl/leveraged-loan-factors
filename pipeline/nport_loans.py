#!/usr/bin/env python3
"""
nport_loans.py  (version 2, memory-efficient)
==============================================

Extracts loan holdings (ASSET_CAT = "LON") from the SEC "Form N-PORT Data Sets"
and builds a price panel (loan x month-end).

Source: https://www.sec.gov/data-research/sec-markets-data/form-n-port-data-sets

Workflow
--------
1. Download the quarterly ZIP files (cached).
2. Per quarter, in chunks: filter loans, join IDENTIFIERS / DEBT_SECURITY /
   SUBMISSION / FUND_REPORTED_INFO, compute price and loan key, and write
   chunk-wise Parquet files (holdings_v2/<quarter>/part-*.parquet).
   A full quarter with all columns is never held in memory.
3. With DuckDB (spills to disk if needed instead of using RAM):
   handle amendments and aggregate the panel.

Requirements
------------
    pip install pandas pyarrow requests duckdb

Example
-------
    python nport_loans.py --start 2019q4 --end 2026q2 \\
        --user-agent "First Last first.last@university.edu" --csv

An interrupted run can simply be restarted: finished quarters (file _DONE in the
quarter folder) are skipped. ZIP files are deleted after successful processing
(keep them with --keep-zips).
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
import time
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import requests

BASE_URL = "https://www.sec.gov/files/dera/data/form-n-port-data-sets/{q}_nport.zip"
CHUNKSIZE = 500_000

HOLDING_COLS = [
    "ACCESSION_NUMBER", "HOLDING_ID", "ISSUER_NAME", "ISSUER_TITLE", "ISSUER_CUSIP",
    "BALANCE", "UNIT", "CURRENCY_CODE", "CURRENCY_VALUE", "PAYOFF_PROFILE",
    "ASSET_CAT", "FAIR_VALUE_LEVEL",
]
KEEP_HOLD = ["ACCESSION_NUMBER", "HOLDING_ID", "ISSUER_NAME", "ISSUER_TITLE",
             "ISSUER_CUSIP", "BALANCE", "CURRENCY_CODE", "CURRENCY_VALUE", "FAIR_VALUE_LEVEL"]
IDENT_COLS = ["HOLDING_ID", "IDENTIFIER_ISIN", "OTHER_IDENTIFIER", "OTHER_IDENTIFIER_DESC"]
DEBT_COLS = ["HOLDING_ID", "MATURITY_DATE", "COUPON_TYPE", "ANNUALIZED_RATE",
             "IS_DEFAULT", "IS_ANY_PORTION_INTEREST_PAID"]
SUB_COLS = ["ACCESSION_NUMBER", "FILING_DATE", "SUB_TYPE", "REPORT_DATE"]
FUND_COLS = ["ACCESSION_NUMBER", "SERIES_NAME", "SERIES_ID"]
REG_COLS = ["ACCESSION_NUMBER", "CIK"]

OUT_STR = ["ACCESSION_NUMBER", "FUND_KEY", "SERIES_NAME", "LOAN_KEY", "KEY_TYPE",
           "ISSUER_NAME", "ISSUER_TITLE", "LOANX_ID", "FIGI", "ISIN", "CURRENCY_CODE",
           "FAIR_VALUE_LEVEL", "COUPON_TYPE", "SUB_TYPE"]
OUT_COLS = OUT_STR + ["HOLDING_ID", "REPORT_DATE", "FILING_DATE", "MONTH_END",
                      "MATURITY_DATE", "BALANCE", "CURRENCY_VALUE", "PRICE",
                      "ANNUALIZED_RATE", "IS_DEFAULT", "IS_PIK",
                      "IS_UNFUNDED_OR_REVOLVER", "PRICE_PLAUSIBLE"]

UNFUNDED_RE = re.compile(
    r"DELAYED\s*DRAW|\bDDTL\b|\bDD\s*TL\b|UNFUNDED|REVOLV|\bRCF\b|\bLOC\b|LETTER OF CREDIT",
    re.IGNORECASE,
)
LOANX_RE = re.compile(r"^LX\d{6}$")
FIGI_RE = re.compile(r"^BBG[0-9A-Z]{9}$")
CUSIP_RE = re.compile(r"^[0-9A-Z]{8}[0-9]$")
NAME_SUFFIX_RE = re.compile(
    r"\b(INC|INCORPORATED|LLC|L L C|CORP|CORPORATION|CO|COMPANY|LTD|LIMITED|LP|L P|"
    r"PLC|SA|SARL|S A R L|BV|GMBH|AG|HOLDINGS?|HOLDCO|GROUP|THE)\b"
)


# --------------------------------------------------------------------------- #
# Helper functions
# --------------------------------------------------------------------------- #
def quarter_range(start: str, end: str) -> list[str]:
    def parse(q: str) -> tuple[int, int]:
        m = re.fullmatch(r"(\d{4})q([1-4])", q.lower())
        if not m:
            raise ValueError(f"Invalid quarter: {q} (format e.g. 2019q4)")
        return int(m.group(1)), int(m.group(2))

    y, q = parse(start)
    ye, qe = parse(end)
    out = []
    while (y, q) <= (ye, qe):
        out.append(f"{y}q{q}")
        q += 1
        if q == 5:
            y, q = y + 1, 1
    return out


def download(q: str, data_dir: Path, user_agent: str) -> Path | None:
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / f"{q}_nport.zip"
    if path.exists() and path.stat().st_size > 0:
        return path
    url = BASE_URL.format(q=q)
    print(f"[{q}] Downloading {url}")
    headers = {"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"}
    with requests.get(url, headers=headers, stream=True, timeout=120) as r:
        if r.status_code == 404:
            print(f"[{q}] not available (404), skipped")
            return None
        r.raise_for_status()
        tmp = path.with_suffix(".part")
        try:
            with open(tmp, "wb") as f:
                for block in r.iter_content(chunk_size=1 << 20):
                    f.write(block)
        except BaseException:
            tmp.unlink(missing_ok=True)   # do not leave partial files behind
            raise
        tmp.replace(path)
    time.sleep(0.5)
    return path


def find_member(zf: zipfile.ZipFile, table: str) -> str | None:
    for name in zf.namelist():
        if Path(name).stem.upper() == table.upper():
            return name
    return None


def read_table(zf: zipfile.ZipFile, table: str, usecols: list[str], chunksize=None):
    member = find_member(zf, table)
    if member is None:
        raise FileNotFoundError(f"Table {table} not found in ZIP")
    with zf.open(member) as fh:
        header = fh.readline().decode("utf-8", errors="replace").rstrip("\r\n").split("\t")
    cols = [c for c in usecols if c in header]
    return pd.read_csv(
        zf.open(member), sep="\t", dtype=str, usecols=cols, quoting=3,
        encoding="utf-8", encoding_errors="replace", on_bad_lines="skip",
        chunksize=chunksize, low_memory=False,
    )


def col(df: pd.DataFrame, name: str) -> pd.Series:
    """Column, or an empty column if it is missing from the data set."""
    return df[name] if name in df else pd.Series(np.nan, index=df.index, dtype=object)


def to_date(s: pd.Series) -> pd.Series:
    d = pd.to_datetime(s, format="%d-%b-%Y", errors="coerce")
    rest = d.isna() & s.notna()
    if rest.any():
        d.loc[rest] = pd.to_datetime(s[rest], errors="coerce")
    return d


def to_num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")


def yes(s: pd.Series) -> pd.Series:
    return s.fillna("").str.upper().eq("Y")


def normalize_name(name) -> str:
    if not isinstance(name, str):
        return ""
    n = re.sub(r"[^A-Z0-9 ]", " ", name.upper())
    n = NAME_SUFFIX_RE.sub(" ", n)
    return re.sub(r"\s+", " ", n).strip()


def concat_or_empty(parts: list[pd.DataFrame], cols: list[str]) -> pd.DataFrame:
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=cols)


# --------------------------------------------------------------------------- #
# Step 2: process one quarter chunk by chunk
# --------------------------------------------------------------------------- #
def process_quarter(zip_path: Path, q: str, qdir: Path, usd_only: bool) -> None:
    if (qdir / "_DONE").exists():
        print(f"[{q}] already processed, skipped")
        return
    if qdir.exists():
        shutil.rmtree(qdir)
    tmpdir = qdir / "_tmp"
    tmpdir.mkdir(parents=True)

    with zipfile.ZipFile(zip_path) as zf:
        # --- Pass 1: filter loan holdings and store them temporarily
        print(f"[{q}] Filtering loan holdings ...")
        id_arrays, n_rows, k = [], 0, 0
        for chunk in read_table(zf, "FUND_REPORTED_HOLDING", HOLDING_COLS, CHUNKSIZE):
            m = (col(chunk, "ASSET_CAT").str.upper().eq("LON")
                 & col(chunk, "UNIT").str.upper().eq("PA")
                 & col(chunk, "PAYOFF_PROFILE").fillna("Long").str.lower().eq("long"))
            if usd_only:
                m &= col(chunk, "CURRENCY_CODE").str.upper().eq("USD")
            c = chunk.loc[m, [x for x in KEEP_HOLD if x in chunk]].copy()
            del chunk
            if c.empty:
                continue
            c["HOLDING_ID"] = to_num(c["HOLDING_ID"])
            c["BALANCE"] = to_num(c["BALANCE"])
            c["CURRENCY_VALUE"] = to_num(c["CURRENCY_VALUE"])
            c = c[c["HOLDING_ID"].notna() & c["BALANCE"].gt(0)]
            c["HOLDING_ID"] = c["HOLDING_ID"].astype("int64")
            id_arrays.append(c["HOLDING_ID"].to_numpy())
            c.to_parquet(tmpdir / f"h{k:04d}.parquet", index=False)
            k += 1
            n_rows += len(c)
        ids = np.unique(np.concatenate(id_arrays)) if id_arrays else np.array([], dtype="int64")
        print(f"[{q}] {n_rows:,} loan holdings")

        # --- Identifiers (LoanX ID, FIGI, ISIN)
        parts = []
        for chunk in read_table(zf, "IDENTIFIERS", IDENT_COLS, CHUNKSIZE):
            hid = to_num(chunk["HOLDING_ID"])
            sel = hid.isin(ids)
            if not sel.any():
                continue
            c = chunk[sel]
            other = col(c, "OTHER_IDENTIFIER").fillna("").str.strip().str.upper()
            desc = col(c, "OTHER_IDENTIFIER_DESC").fillna("").str.upper()
            isin = col(c, "IDENTIFIER_ISIN").fillna("").str.strip().str.upper()
            parts.append(pd.DataFrame({
                "HOLDING_ID": hid[sel].astype("int64"),
                "LOANX_ID": other.where(other.str.match(LOANX_RE)
                                        | (desc.str.contains("LOANX|LXID|MARKIT") & other.ne(""))),
                "FIGI": other.where(other.str.match(FIGI_RE)),
                "ISIN": isin.where(isin.ne("")),
            }))
        ident = concat_or_empty(parts, ["HOLDING_ID", "LOANX_ID", "FIGI", "ISIN"])
        ident["HOLDING_ID"] = ident["HOLDING_ID"].astype("int64")
        ident = ident.groupby("HOLDING_ID").first()
        del parts

        # --- Debt / loan characteristics
        parts = []
        for chunk in read_table(zf, "DEBT_SECURITY", DEBT_COLS, CHUNKSIZE):
            hid = to_num(chunk["HOLDING_ID"])
            sel = hid.isin(ids)
            if not sel.any():
                continue
            c = chunk[sel]
            parts.append(pd.DataFrame({
                "HOLDING_ID": hid[sel].astype("int64"),
                "MATURITY_DATE": to_date(col(c, "MATURITY_DATE")),
                "COUPON_TYPE": col(c, "COUPON_TYPE"),
                "ANNUALIZED_RATE": to_num(col(c, "ANNUALIZED_RATE")).astype("float32"),
                "IS_DEFAULT": yes(col(c, "IS_DEFAULT")),
                "IS_PIK": yes(col(c, "IS_ANY_PORTION_INTEREST_PAID")),
            }))
        debt = concat_or_empty(parts, ["HOLDING_ID", "MATURITY_DATE", "COUPON_TYPE",
                                       "ANNUALIZED_RATE", "IS_DEFAULT", "IS_PIK"])
        debt["HOLDING_ID"] = debt["HOLDING_ID"].astype("int64")
        debt = debt.drop_duplicates("HOLDING_ID").set_index("HOLDING_ID")
        del parts

        # --- Filing metadata (small)
        sub = read_table(zf, "SUBMISSION", SUB_COLS)
        fund = read_table(zf, "FUND_REPORTED_INFO", FUND_COLS)
        reg = read_table(zf, "REGISTRANT", REG_COLS)

    meta = sub.merge(fund, on="ACCESSION_NUMBER", how="left").merge(reg, on="ACCESSION_NUMBER", how="left")
    meta["REPORT_DATE"] = to_date(meta["REPORT_DATE"])
    meta["FILING_DATE"] = to_date(meta["FILING_DATE"])
    meta["MONTH_END"] = meta["REPORT_DATE"] + pd.offsets.MonthEnd(0)
    meta["FUND_KEY"] = col(meta, "SERIES_ID").fillna(
        "CIK" + col(meta, "CIK").fillna("") + "_" + col(meta, "SERIES_NAME").fillna(""))
    meta = (meta[["ACCESSION_NUMBER", "FUND_KEY", "SERIES_NAME", "SUB_TYPE",
                  "REPORT_DATE", "FILING_DATE", "MONTH_END"]]
            .drop_duplicates("ACCESSION_NUMBER").set_index("ACCESSION_NUMBER"))

    # --- Pass 2: join chunks, compute measures, write
    for p in sorted(tmpdir.glob("h*.parquet")):
        s = pd.read_parquet(p)
        s = (s.join(ident, on="HOLDING_ID")
              .join(debt, on="HOLDING_ID")
              .join(meta, on="ACCESSION_NUMBER"))

        s["PRICE"] = (s["CURRENCY_VALUE"] / s["BALANCE"] * 100).astype("float32")
        s["PRICE_PLAUSIBLE"] = s["PRICE"].between(1, 150)
        s["IS_UNFUNDED_OR_REVOLVER"] = (
            s["ISSUER_TITLE"].fillna("").str.contains(UNFUNDED_RE)
            | s["ISSUER_NAME"].fillna("").str.contains(UNFUNDED_RE))
        s["IS_DEFAULT"] = s["IS_DEFAULT"].fillna(False).astype(bool)
        s["IS_PIK"] = s["IS_PIK"].fillna(False).astype(bool)

        cusip = col(s, "ISSUER_CUSIP").fillna("").str.strip().str.upper()
        cusip = cusip.where(cusip.str.match(CUSIP_RE) & ~cusip.str.fullmatch(r"0+"))
        name_key = ("NM:" + s["ISSUER_NAME"].map(normalize_name) + "|"
                    + s["MATURITY_DATE"].dt.strftime("%Y-%m-%d").fillna("NA"))
        s["LOAN_KEY"] = ("LX:" + s["LOANX_ID"]).fillna(
            ("FIGI:" + s["FIGI"]).fillna(
                ("ISIN:" + s["ISIN"]).fillna(
                    ("CUSIP:" + cusip).fillna(name_key))))
        s["KEY_TYPE"] = s["LOAN_KEY"].str.split(":").str[0]

        for c in OUT_COLS:
            if c not in s:
                s[c] = np.nan
        out = s[OUT_COLS].copy()
        for c in OUT_STR:
            out[c] = out[c].astype("string")
        out.to_parquet(qdir / p.name.replace("h", "part-", 1), index=False)
        p.unlink()
        del s, out

    tmpdir.rmdir()
    (qdir / "_DONE").touch()


# --------------------------------------------------------------------------- #
# Step 3: panel with DuckDB
# --------------------------------------------------------------------------- #
def sql_path(p: Path) -> str:
    return p.resolve().as_posix().replace("'", "''")


def build_outputs(hold_dir: Path, out_dir: Path, include_unfunded: bool,
                  write_csv: bool, export_holdings: bool, memory_limit: str,
                  temp_dir: str | None = None) -> None:
    import duckdb

    if not list(hold_dir.glob("*/part-*.parquet")):
        sys.exit("No processed data found.")

    tmp = Path(temp_dir) if temp_dir else out_dir / "_duckdb_tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute(f"SET memory_limit='{memory_limit}'")
    con.execute(f"SET temp_directory='{sql_path(tmp)}'")
    con.execute("SET preserve_insertion_order=false")

    pattern = sql_path(hold_dir) + "/*/part-*.parquet"
    con.execute(f"CREATE VIEW h AS SELECT * FROM read_parquet('{pattern}', union_by_name=true)")

    # Amendments: per fund and report date, keep only the most recently filed version
    con.execute("""
        CREATE TEMP TABLE latest AS
        SELECT ACCESSION_NUMBER FROM (
            SELECT DISTINCT FUND_KEY, REPORT_DATE, ACCESSION_NUMBER, FILING_DATE FROM h)
        QUALIFY row_number() OVER (
            PARTITION BY FUND_KEY, REPORT_DATE
            ORDER BY FILING_DATE DESC NULLS LAST, ACCESSION_NUMBER DESC) = 1
    """)
    con.execute("CREATE VIEW clean AS SELECT * FROM h "
                "WHERE ACCESSION_NUMBER IN (SELECT ACCESSION_NUMBER FROM latest)")

    unf = "" if include_unfunded else "AND NOT IS_UNFUNDED_OR_REVOLVER"
    panel_sql = """
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
               any_value(MATURITY_DATE)   AS maturity,
               median(ANNUALIZED_RATE)    AS coupon_median,
               bool_or(IS_DEFAULT)        AS any_default,
               bool_or(IS_PIK)            AS any_pik,
               mode(FAIR_VALUE_LEVEL)     AS fv_level_mode
        FROM clean
        WHERE PRICE_PLAUSIBLE {unf} AND MONTH_END = ?
        GROUP BY LOAN_KEY, MONTH_END
    """.format(unf=unf)

    # Aggregate month by month: keeps RAM and disk usage small,
    # and an interruption only costs the current month.
    parts_dir = out_dir / "panel_parts"
    parts_dir.mkdir(parents=True, exist_ok=True)
    months = [r[0] for r in con.execute(
        "SELECT DISTINCT MONTH_END FROM h WHERE MONTH_END IS NOT NULL ORDER BY 1").fetchall()]
    print(f"\nBuilding panel for {len(months)} months ...")
    for m in months:
        part = parts_dir / f"{pd.Timestamp(m):%Y-%m}.parquet"
        if part.exists():
            continue
        tmp_part = part.with_suffix(".tmp")
        df = con.execute(panel_sql, [m]).df()
        df.to_parquet(tmp_part, index=False)
        tmp_part.replace(part)
        print(f"  {pd.Timestamp(m):%Y-%m}: {len(df):,} Loans")

    panel_path = out_dir / "loan_price_panel.parquet"
    parts_glob = sql_path(parts_dir) + "/*.parquet"
    con.execute(f"COPY (SELECT * FROM read_parquet('{parts_glob}', union_by_name=true)) "
                f"TO '{sql_path(panel_path)}' (FORMAT PARQUET)")
    if write_csv:
        con.execute(f"COPY (SELECT * FROM read_parquet('{sql_path(panel_path)}')) "
                    f"TO '{sql_path(out_dir / 'loan_price_panel.csv')}' (HEADER, DELIMITER ',')")
    if export_holdings:
        con.execute(f"COPY (SELECT * FROM clean) TO "
                    f"'{sql_path(out_dir / 'loan_holdings_clean.parquet')}' (FORMAT PARQUET)")

    # Overview
    p = f"read_parquet('{sql_path(panel_path)}')"
    n_obs, n_loans = con.execute(f"SELECT count(*), count(DISTINCT LOAN_KEY) FROM {p}").fetchone()
    print("\n=== Summary ===")
    print(f"Panel observations: {n_obs:,}")
    print(f"Unique loans:       {n_loans:,}")
    print("\nKey types (share of loans):")
    print(con.execute(f"""
        SELECT key_type, round(count(*) / sum(count(*)) OVER (), 3) AS share
        FROM (SELECT LOAN_KEY, any_value(key_type) AS key_type FROM {p} GROUP BY LOAN_KEY)
        GROUP BY key_type ORDER BY share DESC""").df().to_string(index=False))
    print("\nLoans and funds per month (last 12):")
    print(con.execute(f"""
        SELECT * FROM (
            SELECT CAST(MONTH_END AS DATE) AS month, count(*) AS loans,
                   median(n_funds) AS median_funds
            FROM {p} GROUP BY 1 ORDER BY 1 DESC LIMIT 12) ORDER BY month
        """).df().to_string(index=False))
    con.close()
    shutil.rmtree(tmp, ignore_errors=True)


# --------------------------------------------------------------------------- #
def main() -> None:
    ap = argparse.ArgumentParser(description="Loan price panel from the SEC N-PORT data sets")
    ap.add_argument("--start", default="2019q4", help="first quarter, e.g. 2019q4")
    ap.add_argument("--end", required=True, help="last quarter, e.g. 2026q2")
    ap.add_argument("--user-agent", required=True, help='e.g. "Name name@university.edu" (required by the SEC)')
    ap.add_argument("--data-dir", default="nport_data", help="folder for ZIP files")
    ap.add_argument("--out-dir", default="nport_out", help="folder for results")
    ap.add_argument("--all-currencies", action="store_true", help="not only USD loans")
    ap.add_argument("--include-unfunded", action="store_true",
                    help="keep unfunded/DDTL/revolver tranches in the panel")
    ap.add_argument("--csv", action="store_true", help="also save the panel as CSV")
    ap.add_argument("--export-holdings", action="store_true",
                    help="export cleaned individual holdings as one Parquet file")
    ap.add_argument("--keep-zips", action="store_true",
                    help="keep ZIP files after processing (default: delete)")
    ap.add_argument("--temp-dir", default=None,
                    help="folder for DuckDB spill files (e.g. external drive)")
    ap.add_argument("--memory-limit", default="4GB", help="RAM limit for DuckDB, e.g. 4GB")
    args = ap.parse_args()

    data_dir, out_dir = Path(args.data_dir), Path(args.out_dir)
    hold_dir = out_dir / "holdings_v2"
    for q in quarter_range(args.start, args.end):
        if (hold_dir / q / "_DONE").exists():
            print(f"[{q}] already processed, skipped")
            continue
        zp = download(q, data_dir, args.user_agent)
        if zp is None:
            continue
        process_quarter(zp, q, hold_dir / q, usd_only=not args.all_currencies)
        if not args.keep_zips:
            zp.unlink(missing_ok=True)
            print(f"[{q}] ZIP deleted (disk space)")

    build_outputs(hold_dir, out_dir, args.include_unfunded, args.csv,
                  args.export_holdings, args.memory_limit, args.temp_dir)


if __name__ == "__main__":
    main()
