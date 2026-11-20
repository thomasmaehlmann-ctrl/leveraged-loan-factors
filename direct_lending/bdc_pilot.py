#!/usr/bin/env python3
"""
bdc_pilot.py

Pilot: how many European direct loans do US business development companies (BDCs) report?

BDCs tag their schedules of investments in XBRL (Regulation S-T Rule 405). Each holding is a context with the
axis us-gaap:InvestmentIdentifierAxis; its facts include the fair value (InvestmentOwnedAtFairValue), the cost
(InvestmentOwnedAtCost) and the principal (InvestmentOwnedBalancePrincipalAmount), whose unit shows the loan
currency (USD, EUR, GBP ...). The SEC publishes all XBRL facts of all filings in the "Financial Statement and
Notes" data sets (num.txt with a "segments" column for the dimensions, sub.txt with the filers).

The script reads one or more of these ZIP files (downloaded automatically or given with --zip), keeps the
holdings of 10-Q and 10-K filings, and classifies a holding as European if its principal is denominated in a
European currency, or its identifier or another dimension names a European country.

Output (bdc_pilot/)
    summary by filer: holdings, European holdings, fair value, European share
    overall: European holdings, borrowers, filers, fair value by currency
    sample_european.csv: 100 European holdings for inspection
    axes.csv: frequency of the dimension axes (to see how filers tag country and currency)

Usage
    python bdc_pilot.py --period 2026q2 --user-agent "Name name@university.edu"
    python bdc_pilot.py --zip 2026_05_notes.zip            (file downloaded manually)
"""

import argparse
import io
import re
import time
import zipfile
from pathlib import Path

import pandas as pd
import requests

BASE = "https://www.sec.gov/files/dera/data/financial-statement-and-notes-data-sets/"
TAGS = {"InvestmentOwnedAtFairValue": "fv", "InvestmentOwnedAtCost": "cost",
        "InvestmentOwnedBalancePrincipalAmount": "principal", "InvestmentInterestRate": "rate"}
EUR_CCY = {"EUR", "GBP", "CHF", "SEK", "NOK", "DKK", "PLN", "CZK", "ISK"}
COUNTRIES = ["United Kingdom", "UK", "England", "Scotland", "Germany", "France", "Netherlands", "Luxembourg",
             "Spain", "Italy", "Ireland", "Sweden", "Norway", "Denmark", "Finland", "Belgium", "Switzerland",
             "Austria", "Jersey", "Guernsey", "Poland", "Portugal", "Czech", "Europe", "European"]
CTRY_RE = re.compile(r"\b(?:" + "|".join(COUNTRIES) + r")\b")
CCY_RE = re.compile(r"\b(?:EUR|GBP|CHF|SEK|NOK|DKK)\b|€|£")
IDENT_RE = r"InvestmentIdentifier(?:Axis)?=([^;]*)"


def download(period: str, ua: str, folder: Path) -> list[Path]:
    """Quarterly file (YYYYqN_notes.zip) or the three monthly files (YYYY_MM_notes.zip)."""
    folder.mkdir(exist_ok=True)
    y, q = int(period[:4]), int(period[-1])
    names = [f"{period}_notes.zip"] + [f"{y}_{m:02d}_notes.zip" for m in range(3 * q - 2, 3 * q + 1)]
    got = []
    for n in names:
        p = folder / n
        if p.exists():
            got.append(p)
            continue
        r = requests.get(BASE + n, headers={"User-Agent": ua}, stream=True, timeout=120)
        if r.status_code != 200:
            continue
        print(f"Downloading {n} ...")
        with open(p, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
        got.append(p)
        time.sleep(0.5)
        if n.endswith(f"{period}_notes.zip"):
            break                                   # quarterly file found: no monthly files needed
    if not got:
        raise SystemExit("No Financial Statement and Notes file found; download it manually and use --zip.")
    return got


def member(z: zipfile.ZipFile, stem: str) -> str:
    """Name of the member sub.txt / num.txt, also in subfolders, with .tsv ending or in upper case."""
    for n in z.namelist():
        base = n.replace("\\", "/").split("/")[-1].lower()
        if base in (f"{stem}.txt", f"{stem}.tsv"):
            return n
    raise SystemExit(f"{stem}.txt not found. Files in the archive: {z.namelist()[:20]}")


def read_zip(p: Path) -> pd.DataFrame:
    z = zipfile.ZipFile(p)
    print(f"{p.name}: {len(z.namelist())} files, e.g. {z.namelist()[:8]}")
    sub = pd.read_csv(z.open(member(z, "sub")), sep="\t", dtype=str)
    sub.columns = [c.lower() for c in sub.columns]
    sub = sub[[c for c in ["adsh", "cik", "name", "form", "period"] if c in sub.columns]]
    sub = sub[sub["form"].isin(["10-Q", "10-K", "10-Q/A", "10-K/A"])]
    rows = []
    cols = ["adsh", "tag", "ddate", "uom", "segments", "dimh", "value"]
    # newer data sets store the dimensions in dim.tsv (dimhash -> segments) and a hash (dimh) in num.tsv
    dims = None
    names = [n.replace("\\", "/").split("/")[-1].lower() for n in z.namelist()]
    if "dim.tsv" in names or "dim.txt" in names:
        dm = pd.read_csv(z.open(member(z, "dim")), sep="\t", dtype=str, quoting=3, on_bad_lines="skip")
        dm.columns = [c.lower() for c in dm.columns]
        hcol = "dimhash" if "dimhash" in dm.columns else dm.columns[0]
        dm = dm[dm["segments"].fillna("").str.contains("InvestmentIdentifier")]
        dims = dict(zip(dm[hcol], dm["segments"]))
        print(f"  dimension combinations with InvestmentIdentifierAxis: {len(dims):,}")
    with z.open(member(z, "num")) as f:
        for ch in pd.read_csv(io.TextIOWrapper(f, encoding="utf-8", errors="replace"), sep="\t", dtype=str,
                              chunksize=500_000, on_bad_lines="skip", quoting=3, usecols=lambda c: c.lower() in cols):
            ch.columns = [c.lower() for c in ch.columns]
            ch = ch[ch["tag"].isin(TAGS)]
            if "segments" not in ch.columns:
                if dims is None or "dimh" not in ch.columns:
                    raise SystemExit(f"num file has neither 'segments' nor 'dimh': {list(ch.columns)}")
                ch = ch[ch["dimh"].isin(dims)].copy()
                if ch.empty:
                    continue
                ch["segments"] = ch["dimh"].map(dims).astype(str)
            ch = ch[ch["segments"].fillna("").astype(str).str.contains("InvestmentIdentifier")]
            if len(ch):
                rows.append(ch.drop(columns=[c for c in ["dimh"] if c in ch.columns]))
    num = pd.concat(rows) if rows else pd.DataFrame(columns=cols)
    num = num[num["adsh"].isin(sub["adsh"])]
    print(f"{p.name}: {len(sub):,} 10-Q/10-K filings, {len(num):,} investment facts")
    return num.merge(sub, on="adsh")


def main() -> None:
    ap = argparse.ArgumentParser(description="Pilot: European loans in BDC schedules of investments")
    ap.add_argument("--period", default="2026q2")
    ap.add_argument("--zip", nargs="*", default=None)
    ap.add_argument("--user-agent", default="Research name@example.com")
    ap.add_argument("--data-dir", default="fsn_data")
    ap.add_argument("--out-dir", default="bdc_pilot")
    args = ap.parse_args()
    out = Path(args.out_dir)
    out.mkdir(exist_ok=True)
    pd.set_option("display.width", 220)
    pd.set_option("display.max_colwidth", 60)

    files = [Path(z) for z in args.zip] if args.zip else download(args.period, args.user_agent, Path(args.data_dir))
    d = pd.concat([read_zip(p) for p in files])
    if d.empty:
        raise SystemExit("No investment facts found.")

    # ---- dimension axes (diagnostics)
    axes = d["segments"].str.findall(r"(?:^|;)([A-Za-z]+)=").explode().value_counts()
    axes.to_csv(out / "axes.csv")
    print("\nMost frequent dimension axes in investment facts:")
    print(axes.head(15).to_string())
    print("\nExamples of the segments field:")
    for x in d["segments"].drop_duplicates().sample(min(8, d["segments"].nunique()), random_state=3):
        print("  ", x[:200])

    # ---- one row per holding: latest balance-sheet date per filing
    d["ident"] = d["segments"].str.extract(IDENT_RE, expand=False).fillna("")
    d["value"] = pd.to_numeric(d["value"], errors="coerce")
    d = d[d["ddate"] == d.groupby("adsh")["ddate"].transform("max")]
    key = ["adsh", "cik", "name", "segments"]
    wide = d.pivot_table(index=key, columns="tag", values="value", aggfunc="first").rename(columns=TAGS).reset_index()
    for c in TAGS.values():
        if c not in wide:
            wide[c] = float("nan")
    ccy = d[d["tag"] == "InvestmentOwnedBalancePrincipalAmount"].groupby(key)["uom"].first().rename("principal_unit")
    wide = wide.merge(ccy, left_on=key, right_index=True, how="left")
    wide["ident"] = wide["segments"].str.extract(IDENT_RE, expand=False).fillna("")
    # keep one filing per filer (the latest)
    last = wide.groupby("cik")["adsh"].transform("max")
    h = wide[(wide["adsh"] == last) & wide["fv"].notna()].copy()

    # ---- European classification
    unit = h["principal_unit"].fillna("").str.upper()
    txt = h["segments"].fillna("")
    h["eu_ccy"] = unit.isin(EUR_CCY) | h["ident"].str.contains(CCY_RE)
    h["eu_ctry"] = txt.str.contains(CTRY_RE)
    non_eu_ccy = ~unit.isin(EUR_CCY | {"USD", ""})              # e.g. KRW, AUD, CAD: not European
    h["european"] = (h["eu_ccy"] | h["eu_ctry"]) & ~non_eu_ccy
    debt = h["ident"].str.contains(r"Loan|Lien|Unitranche|Term|Senior Secured|Delayed|Debt|Revolv|Secured|Notes?\b|Bond",
                                   case=False)
    equity = h["ident"].str.contains(r"Equity|Stock|Warrant|Units\b|Membership|Shares|Interests\b|Partnership",
                                     case=False) & ~h["ident"].str.contains(r"Debt|Loan|Lien", case=False)
    h["loan_like"] = (debt & ~equity) | (h["principal"].notna() & ~equity)
    h["borrower"] = h["ident"].str.split(r",|\(|-| First| Second| Senior| Term| Unitranche", n=1, regex=True).str[0] \
        .str.upper().str.replace(r"[^A-Z0-9 ]", "", regex=True).str.strip().str[:20]
    h["fv_usd_bn"] = h["fv"] / 1e9

    # ---- summaries
    by = h.groupby("name").agg(holdings=("ident", "size"), loans=("loan_like", "sum"),
                               european=("european", "sum"), fv_usd_bn=("fv_usd_bn", "sum"),
                               eu_fv_usd_bn=("fv_usd_bn", lambda x: x[h.loc[x.index, "european"]].sum()))
    by["eu_share_fv"] = by["eu_fv_usd_bn"] / by["fv_usd_bn"]
    by = by.sort_values("eu_fv_usd_bn", ascending=False)
    by.to_csv(out / "by_filer.csv")
    print(f"\n=== Filers with tagged schedules of investments: {len(by)}; with European holdings: {(by['european'] > 0).sum()} ===")
    print(by.head(30).round(3).to_string())

    eu = h[h["european"] & h["loan_like"]]
    print("\n=== European loans (latest filing per BDC) ===")
    print(f"Loan holdings: {len(eu):,}; borrowers (approx.): {eu['borrower'].nunique():,}; "
          f"BDCs: {eu['name'].nunique()}; fair value: USD {eu['fv'].sum() / 1e9:.1f} bn")
    print(f"identified by currency: {eu['eu_ccy'].mean():.0%}, by country text: {eu['eu_ctry'].mean():.0%}")
    print("Fair value by principal unit (USD bn):")
    print((eu.groupby(eu["principal_unit"].fillna("n/a"))["fv"].sum() / 1e9).sort_values(ascending=False).round(2).head(8).to_string())
    if eu.empty:
        print("No European loan holdings recognized; check the examples of the segments field above.")
        return
    top = eu.groupby("name")["fv"].sum().sort_values(ascending=False)
    print(f"Share of the largest BDC: {top.iloc[0] / top.sum():.0%} ({top.index[0]}); largest five: {top.head(5).sum() / top.sum():.0%}")
    eu.sample(min(100, len(eu)), random_state=1)[["name", "ident", "principal_unit", "principal", "fv", "cost", "rate"]] \
        .to_csv(out / "sample_european.csv", index=False)
    print(f"\nSaved in {out}: by_filer.csv, sample_european.csv, axes.csv")


if __name__ == "__main__":
    main()
