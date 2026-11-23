#!/usr/bin/env python3
"""
eu_robustness.py

Robustness of the European direct lending index: runs eu_index.py for a set of variants (each changes one
element of the base specification) and summarizes the results, including the comparison with the Lincoln
European Senior Debt Index (ESDI).

Base specification: European currencies, loans of direct lending BDCs (no revolvers, delayed-draw tranches,
bonds, structured finance), repayment threshold 95, distress threshold 80, recovery 70.8, non-accrual below 70,
at least 5 positions per manager, returns from Q2 2023.

Usage
    python eu_robustness.py --esdi lincoln_esdi_quarterly.csv --user-agent "Name name@university.edu"
Output
    eu_robustness/summary.csv and one folder per variant
"""

import argparse
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

VARIANTS = {
    "base": [],
    "min positions 10": ["--min-positions", "10"],
    "min positions 3": ["--min-positions", "3"],
    "repayment 90": ["--repay-price", "90"],
    "repayment 80": ["--repay-price", "80"],
    "recovery 60": ["--recovery", "60"],
    "recovery 50": ["--recovery", "50"],
    "non-accrual below 60": ["--nonaccrual-price", "60"],
    "non-accrual below 80": ["--nonaccrual-price", "80"],
    "distress 70": ["--distress-price", "70"],
    "EUR only": ["--ccy", "EUR"],
    "GBP only": ["--ccy", "GBP"],
    "first lien only": ["--first-lien-only"],
    "without Blackstone": ["--exclude-manager", "BLACKSTONE"],
    "European borrowers (any currency)": ["--borrower"],
    "no collapse filter": ["--no-collapse-filter"],
    "observed coupons only": ["--no-imputed"],
}


def stats(series: pd.Series, esdi: pd.Series | None) -> dict:
    t = series.dropna()
    out = {"quarters": len(t), "total p.a.": ((1 + t).prod() ** (4 / len(t)) - 1) * 100 if len(t) else np.nan,
           "vol p.a.": t.std() * 200, "worst quarter": t.min() * 100}
    if esdi is not None:
        j = pd.concat([t * 100, esdi], axis=1, sort=True).dropna()
        if len(j) >= 3:
            out["corr ESDI"] = j.iloc[:, 0].corr(j.iloc[:, 1])
            out["diff ESDI p.a."] = (((1 + j.iloc[:, 0] / 100).prod() ** (4 / len(j)))
                                     - ((1 + j.iloc[:, 1] / 100).prod() ** (4 / len(j)))) * 100
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Robustness of the European direct lending index")
    ap.add_argument("--esdi", default=None)
    ap.add_argument("--user-agent", default="Research name@example.com")
    ap.add_argument("--out-dir", default="eu_robustness")
    ap.add_argument("--only", nargs="*", default=None, help="run only these variants")
    ap.add_argument("--start", default="2023-03-31")
    ap.add_argument("--min-positions", default="10", help="loans per manager in the main index (base specification)")
    ap.add_argument("--base-csv", default=None, help="base rates file (otherwise fetched from FRED once)")
    args = ap.parse_args()
    out = Path(args.out_dir)
    out.mkdir(exist_ok=True)
    pd.set_option("display.width", 200)
    esdi = None
    if args.esdi:
        e = pd.read_csv(args.esdi, parse_dates=["quarter"]).set_index("quarter")["total"].dropna()
        e.index = e.index + pd.offsets.QuarterEnd(0)
        esdi = e

    base_csv = args.base_csv
    rows = []
    for name, extra in VARIANTS.items():
        if args.only and name not in args.only:
            continue
        vdir = out / name.replace(" ", "_").replace("(", "").replace(")", "")
        base_min = [] if "--min-positions" in extra else ["--min-positions", args.min_positions]
        cmd = [sys.executable, "eu_index.py", "--out-dir", str(vdir), "--user-agent", args.user_agent, "--start", args.start] + base_min + extra
        if base_csv:
            cmd += ["--base-csv", str(base_csv)]
        print(f"--- {name}")
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            print(res.stderr[-800:])
            continue
        if base_csv is None and (vdir / "base_rates.csv").exists():
            base_csv = vdir / "base_rates.csv"
        for idx in ["EW managers", "VW all"]:
            f = vdir / f"index_{idx.replace(' ', '_').lower()}.csv"
            if not f.exists():
                continue
            d = pd.read_csv(f, index_col=0, parse_dates=True)
            r = {"variant": name, "index": idx, **stats(d["total"], esdi)}
            if "managers" in d:
                r["managers (median)"] = d["managers"].median()
            rows.append(r)
    t = pd.DataFrame(rows).set_index(["variant", "index"])
    t.to_csv(out / "summary.csv")
    print("\n=== Robustness of the European index (returns in %) ===")
    print(t.round(2).to_string())


if __name__ == "__main__":
    main()
