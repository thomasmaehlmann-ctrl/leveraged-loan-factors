#!/usr/bin/env python3
"""
ncen_advisers.py

Maps each fund series to its investment adviser using the SEC Form N-CEN data sets
(annual census filings of registered investment companies).

The quarterly ZIP files are downloaded to --data-dir (or placed there manually from
https://www.sec.gov/data-research/sec-markets-data/form-n-cen-data-sets). Because the table layout
of the data sets is documented only in the readme, the script locates the relevant tables by their
columns: a table with SERIES_ID (fund level) and an adviser table with the adviser's name. It writes
a description of all tables to ncen_tables.txt for checking.

Output
    <out-dir>/ncen_advisers.csv         by series: SERIES_ID, ADVISER (latest adviser), fund name, interval flag
    <out-dir>/ncen_advisers_by_cik.csv  by registrant CIK, for closed-end funds without a series ID

Usage
    python ncen_advisers.py --user-agent "Name name@university.edu"
    python ncen_advisers.py --start 2021q1 --end 2026q1 --user-agent "..."
"""

import argparse
import io
import zipfile
from pathlib import Path

import pandas as pd
import requests

BASE = "https://www.sec.gov/files/dera/data/form-n-cen-data-sets/"


def quarters(start: str, end: str) -> list[str]:
    y, q = int(start[:4]), int(start[-1])
    ye, qe = int(end[:4]), int(end[-1])
    out = []
    while (y, q) <= (ye, qe):
        out.append(f"{y}q{q}")
        q += 1
        if q == 5:
            y, q = y + 1, 1
    return out


def get_zip(q: str, data_dir: Path, ua: str) -> Path | None:
    for name in (f"{q}_ncen.zip", f"{q}_ncen_0.zip"):
        p = data_dir / name
        if p.exists():
            return p
    for name in (f"{q}_ncen.zip", f"{q}_ncen_0.zip"):
        r = requests.get(BASE + name, headers={"User-Agent": ua}, timeout=120)
        if r.status_code == 200 and r.content[:2] == b"PK":
            p = data_dir / name
            p.write_bytes(r.content)
            print(f"[{q}] downloaded {name}")
            return p
    print(f"[{q}] not found online; place the ZIP file manually in {data_dir}")
    return None


def read_tables(zp: Path) -> dict[str, pd.DataFrame]:
    out = {}
    with zipfile.ZipFile(zp) as zf:
        for n in zf.namelist():
            if n.lower().endswith((".tsv", ".txt", ".csv")) and "readme" not in n.lower():
                sep = "\t" if not n.lower().endswith(".csv") else ","
                with zf.open(n) as fh:
                    out[Path(n).stem.upper()] = pd.read_csv(io.TextIOWrapper(fh, "utf-8", errors="replace"),
                                                            sep=sep, dtype=str, quoting=3, low_memory=False)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Fund series -> adviser from Form N-CEN")
    ap.add_argument("--start", default="2020q1")
    ap.add_argument("--end", default="2026q1")
    ap.add_argument("--user-agent", required=True)
    ap.add_argument("--data-dir", default="ncen_data")
    ap.add_argument("--out-dir", default="dl_out")
    args = ap.parse_args()

    data_dir, out = Path(args.data_dir), Path(args.out_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)

    rows, described = [], False
    for q in quarters(args.start, args.end):
        zp = get_zip(q, data_dir, args.user_agent)
        if zp is None:
            continue
        t = read_tables(zp)
        if not described:
            with open(out / "ncen_tables.txt", "w", encoding="utf-8") as fh:
                for name, df in t.items():
                    fh.write(f"{name}: {', '.join(df.columns)}\n")
            described = True
        need = {"ADVISER", "FUND_REPORTED_INFO", "REGISTRANT"}
        if not need <= set(t):
            print(f"[{q}] tables {sorted(need - set(t))} missing; see {out / 'ncen_tables.txt'}")
            continue
        adv = t["ADVISER"]
        # investment advisers, not sub-advisers
        typ = adv.get("ADVISER_TYPE", pd.Series("", index=adv.index)).fillna("").str.upper()
        adv = adv[~typ.str.contains("SUB")][["FUND_ID", "ADVISER_NAME"]]
        fri = t["FUND_REPORTED_INFO"][["FUND_ID", "ACCESSION_NUMBER", "SERIES_ID", "FUND_NAME", "IS_INTERVAL"]]
        reg = t["REGISTRANT"][["ACCESSION_NUMBER", "CIK", "REGISTRANT_NAME", "INVESTMENT_COMPANY_TYPE"]]
        m = adv.merge(fri, on="FUND_ID").merge(reg, on="ACCESSION_NUMBER", how="left")
        m["QUARTER"] = q
        rows.append(m)
        print(f"[{q}] {m['FUND_ID'].nunique():,} funds with adviser")

    if not rows:
        raise SystemExit("No adviser data extracted. Please send ncen_tables.txt.")
    a = pd.concat(rows, ignore_index=True)
    a["ADVISER"] = a["ADVISER_NAME"].str.strip().str.upper()
    a["CIK"] = a["CIK"].fillna("").str.lstrip("0")
    a["IS_INTERVAL"] = a["IS_INTERVAL"].fillna("").str.upper().isin(["Y", "YES", "TRUE", "1"])

    def most_frequent(df: pd.DataFrame, key: str) -> pd.DataFrame:
        d = df[df[key].fillna("") != ""]
        g = (d.groupby([key, "ADVISER"]).agg(FILINGS=("QUARTER", "size"), LAST=("QUARTER", "max")).reset_index()
             .sort_values([key, "LAST", "FILINGS"], ascending=[True, False, False]).drop_duplicates(key))
        info = d.sort_values("QUARTER").groupby(key).agg(
            FUND_NAME=("FUND_NAME", "last"), REGISTRANT_NAME=("REGISTRANT_NAME", "last"),
            IS_INTERVAL=("IS_INTERVAL", "max"), INVESTMENT_COMPANY_TYPE=("INVESTMENT_COMPANY_TYPE", "last"))
        return g.merge(info, on=key)

    by_series = most_frequent(a, "SERIES_ID")
    by_cik = most_frequent(a, "CIK")
    by_series.to_csv(out / "ncen_advisers.csv", index=False)
    by_cik.to_csv(out / "ncen_advisers_by_cik.csv", index=False)
    print(f"\n{len(by_series):,} series and {len(by_cik):,} registrants (CIK) mapped to "
          f"{a['ADVISER'].nunique():,} advisers; interval funds: {by_cik['IS_INTERVAL'].sum():,} registrants")
    print(f"Saved: {out / 'ncen_advisers.csv'}, {out / 'ncen_advisers_by_cik.csv'}")


if __name__ == "__main__":
    main()
