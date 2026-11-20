#!/usr/bin/env python3
"""
bdc_panel.py

Position panel of all business development companies (BDCs) from the SEC Financial Statement and Notes data sets
(XBRL-tagged schedules of investments, available from Q3 2022 positions onward).

Steps
    1. Holdings: for every 10-Q / 10-K filing, the facts InvestmentOwnedAtFairValue, InvestmentOwnedAtCost,
       InvestmentOwnedBalancePrincipalAmount (with its currency unit) and InvestmentInterestRate per position
       (us-gaap:InvestmentIdentifierAxis). Latest filing per BDC and balance-sheet date (amendments replace).
    2. Cleaning: subtotals (identifier is the beginning of another identifier and has no principal, or starts
       with Total / Cash / Net Assets), cash and money market funds, equity, positions without principal.
    3. Classification: instrument (first lien, second lien, unsecured/subordinated, revolver, delayed draw, bond,
       equipment financing, other debt), loan currency (unit of the principal), European currency
       (EUR, GBP, CHF, SEK, NOK, DKK, PLN), European borrower (country names or European legal forms).
    4. Position key: identifier without the parts that change every quarter (rates, spreads, percentages, dates,
       maturities) and without a trailing tranche number, so that all tranches of a borrower and instrument in a
       BDC are combined and followed from quarter to quarter.
    5. Prices in loan currency: fair value is reported in USD, principal in the loan currency; quarter-end
       exchange rates from FRED (Federal Reserve H.10) convert the fair value.
    6. Manager families (e.g. Blackstone, Blue Owl incl. Owl Rock, Morgan Stanley incl. North Haven) and BDC types
       (direct lending vs. real estate, infrastructure, asset-based, venture, SBA lending).

Input
    fsn_data/*.zip        Financial Statement and Notes data sets (quarterly up to 2025 Q3, monthly afterwards)
Output (bdc_out/)
    bdc_holdings.parquet   cleaned holdings (one row per tagged position and filing)
    bdc_positions.parquet  BDC x position key x currency x quarter-end, with par, fair value, price, coupon, flags
    fx_quarter_end.csv     exchange rates used

Usage
    python bdc_panel.py                       (all ZIP files in fsn_data)
    python bdc_panel.py --fx-csv fx.csv       (exchange rates from a file instead of FRED)
"""

import argparse
import io
import re
from pathlib import Path

import numpy as np
import pandas as pd
import requests

import bdc_pilot as bp

EU_CCY = ["EUR", "GBP", "CHF", "SEK", "NOK", "DKK", "PLN"]
# FRED series: (id, True if quoted as USD per currency unit)
FRED = {"EUR": ("DEXUSEU", True), "GBP": ("DEXUSUK", True), "CHF": ("DEXSZUS", False), "SEK": ("DEXSDUS", False),
        "NOK": ("DEXNOUS", False), "DKK": ("DEXDNUS", False), "CAD": ("DEXCAUS", False), "AUD": ("DEXUSAL", True)}

SUBTOTAL_RE = re.compile(r"^\s*(?:Total|Net Assets|Cash|Largest|Top Five|Liabilities)|Money Market|Liquidity Fund|"
                         r"T-Fund|Treasury Portfolio|Institutional (?:Class|Shares)|Non-Money Market Cash", re.I)
EQUITY_RE = re.compile(r"\b(?:Common|Preferred|Stock|Shares|Units?\b|LP interests?|Limited partnership|Partnership "
                       r"Interests?|Warrants?|Equity|Membership|Ordinary|Class [A-Z]\b)", re.I)
DEBT_RE = re.compile(r"Loan|Lien|Unitranche|One stop|Secured|Debt|Revolv|Delayed Draw|Facility|Subordinated|"
                     r"Mezzanine|Term\b|Notes?\b|Bond|Financing", re.I)
INSTR = [("revolver", r"Revolv|\bRCF\b|Revolving"), ("delayed_draw", r"Delayed Draw|\bDDTL\b|Undrawn"),
         ("second_lien", r"Second Lien|2nd Lien"), ("unsecured", r"Unsecured|Subordinated|Mezzanine|Junior"),
         ("bond", r"\bBonds?\b|\bNotes?\b"), ("equipment", r"Equipment Financing|Equipment Loan"),
         ("first_lien", r"First Lien|1st Lien|Unitranche|One stop|Senior Secured|Secured Debt|Term Loan|Secured Loan")]
LEGAL_EU = re.compile(r"\b(?:GmbH|S\.?\s?[aà]\.?\s?r\.?\s?l\.?|SARL|B\.V\.|BV|N\.V\.|Oy|AB|S\.p\.A\.|SpA|SAS|S\.A\.S\.|AG|"
                      r"A/S|ApS|PLC|DAC|Cooperatief|SRL|S\.L\.|Sp\. z o\.o\.|ASA|SE)\b", re.I)
COUNTRY = re.compile(r"\b(?:United Kingdom|England|Scotland|Germany|France|Netherlands|Luxembourg|Spain|Italy|Ireland|"
                     r"Sweden|Norway|Denmark|Finland|Belgium|Switzerland|Austria|Jersey|Guernsey|Poland|Portugal|"
                     r"Czech|Iceland)\b", re.I)
VOLATILE = [r"\(?Incl\.?[^)]*\)?", r"Interest Rate[^A-Za-z]*(?:Fixed|Variable)?[^A-Za-z]*", r"Reference Rate and Spread",
            r"Interest Term", r"Current Coupon", r"Basis Point Spread Above Index", r"Spread", r"Index",
            r"\b(?:SOFR|SONIA|EURIBOR|SN|SON|S|E|N|L|P|C|3M|1M|6M)\s*\+\s*[\d.,]+\s*%?", r"\+\s*[\d.,]+",
            r"[\d.,]+\s*%", r"\bPIK\b", r"\bFloor\b", r"\b\d{1,2}/\d{1,2}/\d{2,4}\b", r"\b\d{1,2}/\d{4}\b",
            r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}",
            r"(?:Maturity(?:/\s*Dissolution)?\s*Date|Maturity|MaturityDate|Investment Date|Acquisition Date|Due)",
            r"of Net Assets", r"\b\d{4}\b", r"\[[^\]]*\]", r"HTTPS?\S*"]
MANAGERS = [("BLUE OWL", r"^(?:BLUE OWL|OWL ROCK)"), ("MORGAN STANLEY", r"^(?:MORGAN STANLEY|NORTH HAVEN|SL INVESTMENT)"),
            ("KKR", r"^(?:FS KKR|KKR)"), ("GOLDMAN SACHS", r"^GOLDMAN"), ("NUVEEN CHURCHILL", r"^NUVEEN CHURCHILL"),
            ("HPS", r"^HPS"), ("BLACKSTONE", r"^BLACKSTONE"), ("APOLLO", r"^(?:APOLLO|MIDCAP)"), ("ARES", r"^ARES"),
            ("BAIN", r"^BAIN"), ("OAKTREE", r"^OAKTREE"), ("SIXTH STREET", r"^SIXTH STREET"), ("GOLUB", r"^GOLUB"),
            ("BARINGS", r"^BARINGS"), ("CARLYLE", r"^CARLYLE"), ("ANTARES", r"^ANTARES"), ("T ROWE OHA", r"^T\. ROWE"),
            ("BLACKROCK", r"^BLACKROCK"), ("CRESCENT", r"^CRESCENT"), ("TPG TWIN BROOK", r"^(?:TPG|AG TWIN BROOK)")]
NON_DL = re.compile(r"REAL ESTATE|INFRASTRUCTURE|ASSET BACKED|TIAA|NEWTEK|TRINITY|HERCULES|TRIPLEPOINT|HORIZON TECH|"
                    r"RUNWAY|VENTURE|TERRA (?:INCOME|SECURED)", re.I)


GENERIC = [r"Non[- ]?Affiliated Issuer", r"Affiliated Issuer", r"Non[- ]?Controlled\s*/?\s*,?\s*Non[- ]?Affiliated",
           r"Non[- ]?Controlled", r"Non[- ]?Affiliated", r"Controlled\s*/?\s*Affiliated", r"Affiliated Investments?",
           r"Controlled Investments?", r"Portfolio Compan(?:y|ies)", r"\bInvestments?\b", r"\bDebt Investments\b",
           r"British Pound|Pound Sterling|European Currency|Euro Currency|\bEuro\b|Swedish Krona|Norwegian Krone|"
           r"Danish Krone|Swiss Franc|Canadian Dollar|Australian Dollar|U\.?S\.? Dollar",
           r"\b(?:SOFR|SONIA|EURIBOR|EUIBOR|EURIB|SARON|STIBOR|NIBOR|CIBOR|BBSW|CORRA|LIBOR|Prime|Base Rate)\b",
           r"\b(?:Not )?Qualifying\b", r"\bNon[- ]?Accrual\b", r"\bPIK\b",
           r"\b(?:One|Two|Three|Four|Five|Six|Seven|Eight|Nine|Ten)\s*$"]


def norm_key(ident: str) -> str:
    s = ident
    for p in VOLATILE + GENERIC:
        s = re.sub(p, " ", s, flags=re.I)
    s = re.sub(r"[-|,;:()/]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip().upper()
    return re.sub(r"(?:\s+\d{1,2})+$", "", s)       # trailing tranche number(s)


def instrument(ident: str) -> str:
    for name, pat in INSTR:
        if re.search(pat, ident, re.I):
            return name
    return "other_debt"


def manager(name: str) -> str:
    n = name.upper()
    for m, pat in MANAGERS:
        if re.search(pat, n):
            return m
    return n.split()[0] if n else ""


def fred_rates(currencies: list[str], start: str, end: str, ua: str) -> pd.DataFrame:
    rows = []
    for c in currencies:
        if c not in FRED:
            continue
        sid, usd_per = FRED[c]
        url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}&cosd={start}&coed={end}"
        r = requests.get(url, headers={"User-Agent": ua}, timeout=60)
        r.raise_for_status()
        f = pd.read_csv(io.StringIO(r.text))
        f.columns = ["date", "rate"]
        f["date"] = pd.to_datetime(f["date"])
        f["rate"] = pd.to_numeric(f["rate"], errors="coerce")
        f = f.dropna()
        f["usd_per_ccy"] = f["rate"] if usd_per else 1 / f["rate"]
        f["ccy"] = c
        rows.append(f[["date", "ccy", "usd_per_ccy"]])
    return pd.concat(rows) if rows else pd.DataFrame(columns=["date", "ccy", "usd_per_ccy"])


def main() -> None:
    ap = argparse.ArgumentParser(description="Position panel of BDC schedules of investments")
    ap.add_argument("--data-dir", default="fsn_data")
    ap.add_argument("--zip", nargs="*", default=None)
    ap.add_argument("--out-dir", default="bdc_out")
    ap.add_argument("--fx-csv", default=None, help="CSV with date, ccy, usd_per_ccy (instead of FRED)")
    ap.add_argument("--user-agent", default="Research name@example.com")
    args = ap.parse_args()
    out = Path(args.out_dir)
    out.mkdir(exist_ok=True)
    pd.set_option("display.width", 220)

    files = [Path(z) for z in args.zip] if args.zip else sorted(Path(args.data_dir).glob("*notes*.zip"))
    if not files:
        raise SystemExit(f"No ZIP files found in {args.data_dir}")

    # ---- 1. holdings
    parts = []
    for p in files:
        d = bp.read_zip(p)
        if d.empty:
            continue
        d["value"] = pd.to_numeric(d["value"], errors="coerce")
        d["ddate"] = pd.to_datetime(d["ddate"], format="%Y%m%d", errors="coerce")
        d = d[d["ddate"] == d.groupby("adsh")["ddate"].transform("max")]       # balance-sheet date of the filing
        key = ["adsh", "cik", "name", "ddate", "segments"]
        w = d.pivot_table(index=key, columns="tag", values="value", aggfunc="first").rename(columns=bp.TAGS).reset_index()
        for c in bp.TAGS.values():
            if c not in w:
                w[c] = np.nan
        unit = d[d["tag"] == "InvestmentOwnedBalancePrincipalAmount"].groupby(key)["uom"].first().rename("ccy")
        w = w.merge(unit, left_on=key, right_index=True, how="left")
        parts.append(w)
    h = pd.concat(parts, ignore_index=True)
    h["month_end"] = h["ddate"] + pd.offsets.MonthEnd(0)
    # latest filing per BDC and balance-sheet date (amendments, and filings that appear in two data sets)
    h = h[h["adsh"] == h.groupby(["cik", "month_end"])["adsh"].transform("max")]
    h["ident"] = h["segments"].str.extract(bp.IDENT_RE, expand=False).fillna("").str.strip()
    h["other_dims"] = h["segments"].str.replace(bp.IDENT_RE, "", regex=True).str.strip(";")
    print(f"\nHoldings: {len(h):,} in {h['cik'].nunique()} BDCs, {h['month_end'].nunique()} balance-sheet dates")

    # ---- 2. cleaning
    idents = h.groupby("adsh")["ident"].apply(lambda x: sorted(set(x)))
    def prefix_flags(g: pd.DataFrame) -> pd.Series:
        s = idents[g.name]
        out = []
        for i in g["ident"]:
            j = np.searchsorted(s, i, side="right")
            out.append(j < len(s) and s[j].startswith(i) and s[j] != i)
        return pd.Series(out, index=g.index)
    try:
        h["is_prefix"] = h.groupby("adsh", group_keys=False)[["ident"]].apply(prefix_flags)
    except TypeError:
        h["is_prefix"] = h.groupby("adsh", group_keys=False).apply(prefix_flags)
    h["subtotal"] = h["ident"].str.contains(SUBTOTAL_RE) | (h["is_prefix"] & h["principal"].isna())
    h["equity"] = h["ident"].str.contains(EQUITY_RE) & ~h["ident"].str.contains(DEBT_RE)
    h["ccy"] = h["ccy"].fillna("").str.upper()
    n0 = len(h)
    h = h[~h["subtotal"] & ~h["equity"] & h["principal"].gt(0) & h["fv"].notna()].copy()
    print(f"Debt holdings after removing subtotals, cash, equity and positions without principal: {len(h):,} of {n0:,}")

    # ---- 3./4./6. classification, key, manager, BDC type
    h["instrument"] = h["ident"].map(instrument)
    h["eu_ccy"] = h["ccy"].isin(EU_CCY)
    txt = h["ident"] + " " + h["other_dims"].fillna("")
    h["eu_borrower"] = txt.str.contains(COUNTRY) | h["ident"].str.contains(LEGAL_EU)
    h["key"] = h["ident"].map(norm_key)
    h["manager"] = h["name"].map(manager)
    h["dl_bdc"] = ~h["name"].str.contains(NON_DL)

    # ---- 5. exchange rates and prices in loan currency
    ccys = sorted(set(h["ccy"]) - {"USD", ""})
    if args.fx_csv:
        fx = pd.read_csv(args.fx_csv, parse_dates=["date"])
    else:
        fx = fred_rates(ccys, str(h["month_end"].min().date() - pd.Timedelta(days=10)),
                        str(h["month_end"].max().date()), args.user_agent)
    fx.to_csv(out / "fx_quarter_end.csv", index=False)
    fx = fx.sort_values("date")
    h = h.sort_values("ddate")
    h = pd.merge_asof(h, fx.rename(columns={"date": "fx_date"}), left_on="ddate", right_on="fx_date",
                      left_by="ccy", right_by="ccy", direction="backward", tolerance=pd.Timedelta(days=10))
    h.loc[h["ccy"].isin(["USD", ""]), "usd_per_ccy"] = 1.0
    h["fv_local"] = h["fv"] / h["usd_per_ccy"]
    h["price"] = h["fv_local"] / h["principal"] * 100
    missing_fx = h["usd_per_ccy"].isna()
    if missing_fx.any():
        print(f"No exchange rate for {missing_fx.sum():,} holdings in: {sorted(h.loc[missing_fx, 'ccy'].unique())}")
    h["unfunded"] = h["fv"].le(0) | h["price"].lt(1) | h["ident"].str.contains(r"Undrawn|Unfunded", case=False)
    h.drop(columns=["segments", "is_prefix", "subtotal", "equity"]).to_parquet(out / "bdc_holdings.parquet", index=False)

    # ---- positions: BDC x key x currency x quarter-end
    v = h[~h["unfunded"] & h["price"].between(1, 150)].copy()
    v["rate_w"] = v["rate"] * v["principal"]
    pos = v.groupby(["cik", "name", "manager", "dl_bdc", "month_end", "key", "ccy"], as_index=False).agg(
        par=("principal", "sum"), fv_usd=("fv", "sum"), fv_local=("fv_local", "sum"), cost_usd=("cost", "sum"),
        rate_w=("rate_w", "sum"), rate_par=("rate", lambda x: v.loc[x.index, "principal"][x.notna()].sum()),
        instrument=("instrument", lambda x: x.mode().iat[0]), eu_ccy=("eu_ccy", "max"),
        eu_borrower=("eu_borrower", "max"), n_tranches=("ident", "size"), ident=("ident", "first"))
    pos["price"] = pos["fv_local"] / pos["par"] * 100
    pos["coupon"] = np.where(pos["rate_par"] > 0, pos["rate_w"] / pos["rate_par"], np.nan)
    pos["coupon"] = np.where(pos["coupon"] < 1, pos["coupon"] * 100, pos["coupon"])    # decimal -> percent
    pos = pos.drop(columns=["rate_w", "rate_par"])
    pos.to_parquet(out / "bdc_positions.parquet", index=False)

    # ---- summary
    q = pos[pos["month_end"].dt.month.isin([3, 6, 9, 12]) & pos["dl_bdc"]]
    def summ(df: pd.DataFrame) -> pd.DataFrame:
        g = df.groupby("month_end")
        s = g.agg(positions=("key", "size"), bdcs=("cik", "nunique"), managers=("manager", "nunique"),
                  fv_usd_bn=("fv_usd", lambda x: x.sum() / 1e9), median_price=("price", "median"),
                  median_coupon=("coupon", "median"))
        mv = df.groupby(["month_end", "manager"])["fv_usd"].sum()
        s["largest_manager_share"] = mv.groupby(level=0).max() / mv.groupby(level=0).sum()
        return s
    print("\n=== Direct lending BDCs, all debt positions, calendar quarter-ends ===")
    print(summ(q).round(3).to_string())
    print("\n=== Loans in European currencies (EUR, GBP, CHF, SEK, NOK, DKK, PLN) ===")
    eu = q[q["eu_ccy"]]
    print(summ(eu).round(3).to_string())
    print("\nBy currency (fair value, USD bn, latest quarter):")
    last = eu[eu["month_end"] == eu["month_end"].max()]
    print((last.groupby("ccy")["fv_usd"].sum() / 1e9).sort_values(ascending=False).round(2).to_string())
    print("\nBy instrument (fair value share, latest quarter):")
    print((last.groupby("instrument")["fv_usd"].sum() / last["fv_usd"].sum()).sort_values(ascending=False).round(3).to_string())
    print("\nManagers in the latest quarter:")
    print(last.groupby("manager").agg(positions=("key", "size"), fv_usd_bn=("fv_usd", lambda x: x.sum() / 1e9))
          .sort_values("fv_usd_bn", ascending=False).head(25).round(3).to_string())
    # tracking: share of positions found again in the next quarter (same BDC, key, currency)
    qq = sorted(eu["month_end"].unique())
    tr = []
    for a, b in zip(qq[:-1], qq[1:]):
        A = eu[eu["month_end"] == a]
        B = set(map(tuple, eu.loc[eu["month_end"] == b, ["cik", "key", "ccy"]].to_numpy()))
        rep = A["cik"].isin(eu.loc[eu["month_end"] == b, "cik"])
        tr.append((pd.Timestamp(a).date(), np.mean([tuple(x) in B for x in A.loc[rep, ["cik", "key", "ccy"]].to_numpy()])
                   if rep.any() else np.nan))
    print("\nTracking (European positions found again next quarter, if the BDC reports):")
    print(pd.DataFrame(tr, columns=["quarter", "share"]).round(3).to_string(index=False))
    print(f"\nSaved: {out}/bdc_holdings.parquet, bdc_positions.parquet, fx_quarter_end.csv")


if __name__ == "__main__":
    main()
