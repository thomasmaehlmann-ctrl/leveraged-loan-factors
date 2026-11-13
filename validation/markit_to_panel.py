#!/usr/bin/env python3
"""
markit_to_panel.py

Converts the IHS Markit loan quotes (data_2018_full.rds) into the panel format of the N-PORT
pipeline, so that exactly the same code computes returns, signals and factor portfolios.

Steps
    1. Read the .rds file once and cache it as Parquet (markit_raw.parquet), later runs use the cache.
    2. Keep USD term loans (loan types starting with "TL", without delayed-draw tranches),
       drop revolvers, equity, warrants and claims.
    3. Month-end values: last quote of each loan in a month (pricing_asof). The incomplete last month
       of the data is dropped.
    4. Map to the panel columns of nport_loan_returns.py:
           price_median  = Markit mid price (preis)
           coupon_median = base rate of the previous month + initial spread (Markit has no coupon)
           n_funds       = number of quote sources (dealers), the Markit counterpart of the fund count
           par_total     = initial facility size, value_total = par_total x price / 100
    5. Write the Markit 12-month PD (x12_month) to a separate file for loan_characteristics.py --pd-file.

Outputs in --out
    loan_price_panel_v2.parquet   panel in the N-PORT format
    markit_pd.parquet             LOAN_KEY, MONTH_END, pd
    markit_stm.parquet            LOAN_KEY, MONTH_END, stm_cer (Markit spread-to-maturity in % p.a.), for the CER

Usage
    python markit_to_panel.py --rds data_2018_full.rds --out markit_out
    python markit_to_panel.py --rds data_2018_full.rds --out markit_common --common-with nport_out/loan_monthly_stm_cer.parquet
    python markit_to_panel.py --rds data_2018_full.rds --out markit_swap --common-with nport_out/loan_monthly_stm_cer.parquet \\
        --nport-signals nport_out/loan_characteristics_M.parquet
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

import sys
from pathlib import Path as _P
sys.path.insert(0, str(_P(__file__).resolve().parent.parent / "pipeline"))   # pipeline modules (repository layout)

from nport_loan_returns import load_base

KEEP_CCY = {"USD", "USD_assumed"}


def month_end(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s).dt.normalize() + pd.offsets.MonthEnd(0)


def load_raw(rds: Path, cache: Path) -> pd.DataFrame:
    if cache.exists():
        print(f"Reading cache {cache}")
        return pd.read_parquet(cache)
    import pyreadr
    print(f"Reading {rds} (once; cached afterwards) ...")
    d = next(iter(pyreadr.read_r(str(rds)).values()))
    d.to_parquet(cache, index=False)
    return d


def main() -> None:
    ap = argparse.ArgumentParser(description="Markit quotes -> panel in the N-PORT pipeline format")
    ap.add_argument("--rds", default="data_2018_full.rds")
    ap.add_argument("--out", default="markit_out")
    ap.add_argument("--base-source", choices=["tbill", "sofr"], default="sofr")
    ap.add_argument("--base-csv", default=None)
    ap.add_argument("--common-with", default=None,
                    help="optional: N-PORT monthly panel; keep only loans whose LoanX ID also appears there")
    ap.add_argument("--nport-signals", default=None,
                    help="optional: N-PORT loan_characteristics_M.parquet; use the N-PORT fund count and model PD "
                         "instead of the Markit dealer count and Markit PD (prices stay Markit)")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    d = load_raw(Path(args.rds), Path(args.rds).with_name("markit_raw.parquet"))
    n0 = len(d)

    lt = d["loan_type"].astype(str)
    term = lt.str.startswith("TL") & ~lt.str.contains("DL", case=False)
    d = d[term & d["ccy"].isin(KEEP_CCY) & d["loan_x_id"].notna()].copy()
    print(f"Quotes: {n0:,} -> {len(d):,} USD term loans ({d['loan_x_id'].nunique():,} loans)")

    d["date"] = pd.to_datetime(d["pricing_asof"], errors="coerce")
    d = d.dropna(subset=["date", "preis"]).sort_values(["loan_x_id", "date"])
    d["MONTH_END"] = month_end(d["date"])
    last_day = d["date"].max()
    if last_day < last_day + pd.offsets.MonthEnd(0) - pd.Timedelta(days=3):
        d = d[d["MONTH_END"] < last_day + pd.offsets.MonthEnd(0)]
        print(f"Incomplete last month dropped (data end {last_day.date()})")
    m = d.groupby(["loan_x_id", "MONTH_END"], as_index=False).tail(1).reset_index(drop=True)

    if args.common_with:
        nport = pd.read_parquet(args.common_with, columns=["LOAN_KEY", "key_type"])
        ids = set(nport.loc[nport["key_type"] == "LX", "LOAN_KEY"].str.replace("LX:", "", regex=False))
        m = m[m["loan_x_id"].isin(ids)]
        print(f"Restricted to LoanX IDs that also appear in N-PORT: {m['loan_x_id'].nunique():,} loans")

    base = load_base(args.base_csv, args.base_source)
    base_lag = (m["MONTH_END"] - pd.offsets.MonthEnd(1)).map(base)
    panel = pd.DataFrame({
        "LOAN_KEY": "LX:" + m["loan_x_id"].astype(str),
        "MONTH_END": m["MONTH_END"],
        "price_median": m["preis"],
        "coupon_median": base_lag + m["initial_spread"] / 100,
        "n_funds": m["quote_sources"].fillna(0).astype(int),
        "maturity": pd.to_datetime(m["maturity_date"], errors="coerce"),
        "issuer_name": m["company_name"],
        "issue_title": m["facility_name"],
        "loanx_id": m["loan_x_id"],
        "key_type": "LX",
        "any_default": False,
        "any_pik": False,
        "par_total": m["initial_size"] * 1e6,
        "fv_level_mode": "2",
    })
    panel["value_total"] = panel["par_total"] * panel["price_median"] / 100
    panel.to_parquet(out / "loan_price_panel_v2.parquet", index=False)

    pdf = pd.DataFrame({"LOAN_KEY": panel["LOAN_KEY"], "MONTH_END": panel["MONTH_END"], "pd": m["x12_month"]})
    if args.nport_signals:
        sig = pd.read_parquet(args.nport_signals, columns=["LOAN_KEY", "MONTH_END", "n_funds", "pd_hat"])
        sig["MONTH_END"] = month_end(sig["MONTH_END"])
        sig = sig.drop_duplicates(["LOAN_KEY", "MONTH_END"])
        panel = panel.drop(columns="n_funds").merge(sig[["LOAN_KEY", "MONTH_END", "n_funds"]],
                                                    on=["LOAN_KEY", "MONTH_END"], how="left")
        # months without an N-PORT report keep no fund count (signal missing instead of "zero funds")
        pdf = sig.rename(columns={"pd_hat": "pd"})[["LOAN_KEY", "MONTH_END", "pd"]]
        print("Signals: N-PORT fund count and N-PORT model PD (Markit prices)")
        panel.to_parquet(out / "loan_price_panel_v2.parquet", index=False)
    pdf.dropna().to_parquet(out / "markit_pd.parquet", index=False)
    stm = pd.DataFrame({"LOAN_KEY": "LX:" + m["loan_x_id"].astype(str), "MONTH_END": m["MONTH_END"],
                        "stm_cer": m["spread_to_maturity"] / 100})         # Markit STM in % p.a.
    stm.dropna().to_parquet(out / "markit_stm.parquet", index=False)

    print(f"Panel: {len(panel):,} loan-months, {panel['LOAN_KEY'].nunique():,} loans, "
          f"{panel['MONTH_END'].min():%Y-%m} to {panel['MONTH_END'].max():%Y-%m}")
    print(f"Median loans per month: {panel.groupby('MONTH_END').size().median():.0f}; "
          f"share with Markit PD: {m['x12_month'].notna().mean():.1%}; "
          f"median quote sources: {panel['n_funds'].median():.0f}")
    print(f"Written to {out}")


if __name__ == "__main__":
    main()
