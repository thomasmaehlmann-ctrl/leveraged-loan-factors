#!/usr/bin/env python3
"""
make_nport_common.py

Restricts the N-PORT data to loans that also appear in the Markit data (USD term loans with the same
LoanX ID), for the comparison on identical loans. Writes a folder in the format expected by
loan_characteristics.py. The default probabilities are taken from the full N-PORT run, because the
default model cannot be re-estimated reliably on the smaller sample.

Outputs in --out
    loan_monthly_stm_cer.parquet, loan_price_panel_v2.parquet   N-PORT data, common loans only
    nport_pd.parquet                                             model PD from the full N-PORT run

Usage
    python make_nport_common.py --markit-dir markit_common --out nport_common
"""

import argparse
from pathlib import Path

import pandas as pd


def main() -> None:
    ap = argparse.ArgumentParser(description="N-PORT data restricted to loans also in Markit")
    ap.add_argument("--nport-dir", default="nport_out")
    ap.add_argument("--markit-dir", default="markit_common", help="output of markit_to_panel.py --common-with")
    ap.add_argument("--out", default="nport_common")
    args = ap.parse_args()

    src, out = Path(args.nport_dir), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    keys = set(pd.read_parquet(Path(args.markit_dir) / "loan_price_panel_v2.parquet", columns=["LOAN_KEY"])["LOAN_KEY"])

    monthly = pd.read_parquet(src / "loan_monthly_stm_cer.parquet")
    monthly = monthly[monthly["LOAN_KEY"].isin(keys)]
    monthly.to_parquet(out / "loan_monthly_stm_cer.parquet", index=False)
    panel = pd.read_parquet(src / "loan_price_panel_v2.parquet")
    panel[panel["LOAN_KEY"].isin(keys)].to_parquet(out / "loan_price_panel_v2.parquet", index=False)
    pdf = pd.read_parquet(src / "loan_characteristics_M.parquet", columns=["LOAN_KEY", "MONTH_END", "pd_hat"])
    pdf = pdf[pdf["LOAN_KEY"].isin(keys)].rename(columns={"pd_hat": "pd"}).dropna()
    pdf.to_parquet(out / "nport_pd.parquet", index=False)
    print(f"{out}: {monthly['LOAN_KEY'].nunique():,} loans, {len(monthly):,} loan-months")


if __name__ == "__main__":
    main()
