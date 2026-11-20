#!/usr/bin/env python3
"""
eu_export.py

Versioned public release of OpenDL Europe (BDC European Direct Lending Index), for Zenodo and loanfactors.org.

The script runs eu_index.py for the published specification and for the published sub-indices and variants,
then collects the results into one release folder:

    opendl_europe_returns.csv      quarterly returns of the main index (ew_managers), the value-weighted index
                                   (vw_all) and the value-weighted index without the largest manager
                                   (vw_ex_largest), with income, accretion, price, realized and unrealized returns
    opendl_europe_subindices.csv   value-weighted sub-indices: first lien only, EUR loans, GBP loans
    opendl_europe_variants.csv     main and value-weighted index under the documented alternatives (repayment
                                   threshold 80; observed coupons only)
    opendl_europe_barometer.csv    loans marked below 80 and below 90 (% of estimated cost), trailing four-quarter
                                   realized and unrealized returns of the value-weighted index
    opendl_europe_universe.csv     positions, BDCs, managers, market value, median price and coupon, currency mix,
                                   share of the largest manager
    metadata.json, README.md, SHA256SUMS.txt

Published specification: loans in European currencies held by direct lending BDCs (XBRL schedules of investments),
no revolvers, delayed-draw tranches, bonds, equipment finance or structured finance; returns in loan currency;
repayment threshold 95, distress threshold 80, recovery 70.8% of par, non-accrual below 70; main index
equal-weighted across managers with at least 10 positions; returns from Q2 2023.

Usage
    python eu_export.py --version 2026.12 --esdi lincoln_esdi_quarterly.csv --base-csv eu_robustness\\base\\base_rates.csv --zip
"""

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

BASE_ARGS = ["--min-positions", "10"]
RUNS = {
    "main": [],
    "first_lien": ["--first-lien-only"],
    "eur": ["--ccy", "EUR"],
    "gbp": ["--ccy", "GBP"],
    "repayment_80": ["--repay-price", "80"],
    "observed_coupons": ["--no-imputed"],
}
COMP = {"total": "total", "income": "income", "accretion": "accretion", "price_ret": "price",
        "realized_cost": "realized", "unrealized_cost": "unrealized"}


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_ix(d: Path, name: str) -> pd.DataFrame:
    return pd.read_csv(d / f"index_{name}.csv", index_col=0, parse_dates=True)


def ann(s: pd.Series) -> float:
    s = s.dropna()
    return ((1 + s).prod() ** (4 / len(s)) - 1) * 100 if len(s) else np.nan


def main() -> None:
    ap = argparse.ArgumentParser(description="Release of OpenDL Europe")
    ap.add_argument("--version", required=True)
    ap.add_argument("--bdc-dir", default="bdc_out")
    ap.add_argument("--work-dir", default="eu_release_work")
    ap.add_argument("--out", default="releases")
    ap.add_argument("--esdi", default=None)
    ap.add_argument("--base-csv", default=None)
    ap.add_argument("--user-agent", default="Research name@example.com")
    ap.add_argument("--doi", default="")
    ap.add_argument("--zip", action="store_true")
    ap.add_argument("--skip-runs", action="store_true", help="reuse the results in --work-dir")
    args = ap.parse_args()

    work = Path(args.work_dir)
    work.mkdir(exist_ok=True)
    out = Path(args.out) / f"opendl_europe_v{args.version}"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    # ---- runs of eu_index.py
    logs = {}
    for name, extra in RUNS.items():
        d = work / name
        if not args.skip_runs:
            cmd = [sys.executable, "eu_index.py", "--out-dir", str(d), "--user-agent", args.user_agent] + BASE_ARGS + extra
            if args.base_csv:
                cmd += ["--base-csv", args.base_csv]
            if args.esdi:
                cmd += ["--esdi", args.esdi]
            print(f"--- {name}")
            res = subprocess.run(cmd, capture_output=True, text=True)
            if res.returncode != 0:
                raise SystemExit(res.stderr[-1500:])
            (d / "log.txt").write_text(res.stdout, encoding="utf-8")
        logs[name] = (d / "log.txt").read_text(encoding="utf-8") if (d / "log.txt").exists() else ""

    main_dir = work / "main"
    codes = {"ew_managers": "EW managers", "vw_all": "VW all", "vw_ex_largest": "VW ex largest"}

    # ---- returns of the published indices
    rows = []
    for code, label in codes.items():
        ix = read_ix(main_dir, label.replace(" ", "_").lower())
        t = pd.DataFrame({dst: ix[src] if src in ix else np.nan for src, dst in COMP.items()})
        if code == "ew_managers":
            t[["accretion", "realized", "unrealized"]] = np.nan        # split meaningful with value weights only
        t["positions"] = ix.get("positions")
        t["managers"] = ix.get("managers", np.nan)
        t["index"] = code
        rows.append(t)
    r = pd.concat(rows).reset_index().rename(columns={"month_end": "date"})
    r["date"] = pd.to_datetime(r["date"]).dt.date
    for c in ["positions", "managers"]:
        r[c] = pd.to_numeric(r[c], errors="coerce").round().astype("Int64")
    r = r[["date", "index", "total", "income", "accretion", "price", "realized", "unrealized", "positions", "managers"]]
    r.sort_values(["index", "date"]).to_csv(out / "opendl_europe_returns.csv", index=False, float_format="%.6f")

    # ---- sub-indices (value-weighted)
    sub = []
    for name in ["first_lien", "eur", "gbp"]:
        ix = read_ix(work / name, "vw_all")
        sub.append(pd.DataFrame({"date": ix.index.date, "series": f"vw_{name}", "total": ix["total"],
                                 "income": ix["income"], "price": ix["price_ret"], "positions": ix["positions"]}))
    pd.concat(sub).to_csv(out / "opendl_europe_subindices.csv", index=False, float_format="%.6f")

    # ---- variants
    var = []
    for name in ["repayment_80", "observed_coupons"]:
        for code, label in [("ew_managers", "EW managers"), ("vw_all", "VW all")]:
            ix = read_ix(work / name, label.replace(" ", "_").lower())
            var.append(pd.DataFrame({"date": ix.index.date, "variant": name, "index": code, "total": ix["total"],
                                     "income": ix["income"], "price": ix["price_ret"]}))
    pd.concat(var).to_csv(out / "opendl_europe_variants.csv", index=False, float_format="%.6f")

    # ---- barometer
    b = pd.read_csv(main_dir / "credit_health_barometer.csv", index_col=0, parse_dates=True)
    keep = {"marked < 80 % cost": "marked_below_80_pct", "marked < 90 % cost": "marked_below_90_pct",
            "marked < 90 % cost (ex largest)": "marked_below_90_pct_ex_largest",
            "T4Q realized (cost) % (VW)": "realized_t4q_pct", "T4Q unrealized % (VW)": "unrealized_t4q_pct"}
    b = b[[c for c in keep if c in b]].rename(columns=keep)
    b.index = b.index.date
    b.index.name = "date"
    b.round(4).to_csv(out / "opendl_europe_barometer.csv")

    # ---- universe statistics (same filters as the index)
    p = pd.read_parquet(Path(args.bdc_dir) / "bdc_positions.parquet")
    p = p[p["dl_bdc"] & p["eu_ccy"] & p["month_end"].dt.month.isin([3, 6, 9, 12]) & p["price"].between(1, 150)
          & ~p["instrument"].isin(["bond", "equipment", "revolver", "delayed_draw"]) & (p["month_end"] >= "2023-03-31")]
    g = p.groupby("month_end")
    u = pd.DataFrame({"positions": g.size(), "bdcs": g["cik"].nunique(), "managers": g["manager"].nunique(),
                      "market_value_usd_bn": g["fv_usd"].sum() / 1e9, "median_price": g["price"].median(),
                      "median_coupon_pct": g["coupon"].median()})
    for c in ["EUR", "GBP"]:
        u[f"share_{c.lower()}"] = p[p["ccy"] == c].groupby("month_end")["fv_usd"].sum().reindex(u.index, fill_value=0) / g["fv_usd"].sum()
    mv = p.groupby(["month_end", "manager"])["fv_usd"].sum()
    u["largest_manager_share"] = mv.groupby(level=0).max() / mv.groupby(level=0).sum()
    u.index = u.index.date
    u.index.name = "date"
    u.round(4).to_csv(out / "opendl_europe_universe.csv")

    # ---- validation statistics (summary only, no third-party data)
    val = {}
    if args.esdi:
        e = pd.read_csv(args.esdi, parse_dates=["quarter"]).set_index("quarter")["total"].dropna()
        e.index = e.index + pd.offsets.QuarterEnd(0)
        series = {"ew_managers": read_ix(main_dir, "ew_managers")["total"], "vw_all": read_ix(main_dir, "vw_all")["total"],
                  "vw_first_lien": read_ix(work / "first_lien", "vw_all")["total"]}
        for k, s in series.items():
            j = pd.concat([s * 100, e], axis=1, sort=True).dropna()
            val[k] = {"quarters": int(len(j)), "corr_esdi": round(float(j.iloc[:, 0].corr(j.iloc[:, 1])), 4),
                      "diff_esdi_pp_pa": round(float(ann(j.iloc[:, 0] / 100) - ann(j.iloc[:, 1] / 100)), 3)}
    for f, k in [("loanlevel_pairs_nport_bdc.csv", "same_loan_nport_vs_bdc_same_manager"),
                 ("loanlevel_pairs_bdc.csv", "same_borrower_different_managers")]:
        fp = Path("eu_out") / f
        if fp.exists():
            q = pd.read_csv(fp)
            if "same_manager" in q:
                q = q[q["same_manager"]]
            if "absdiff" not in q:
                q["absdiff"] = (q["p_nport"] - q["p_bdc"]).abs() if "p_nport" in q else (q["p1"] - q["p2"]).abs()
            if len(q):
                val[k] = {"pairs": int(len(q)), "median_abs_diff": round(float(q["absdiff"].median()), 3),
                          "within_1pt": round(float((q["absdiff"] <= 1).mean()), 3)}

    main_ix = {c: read_ix(main_dir, l.replace(" ", "_").lower()) for c, l in codes.items()}
    summary = {c: {"annualized_total_pct": round(float(ann(ix["total"])), 2),
                   "annualized_income_pct": round(float(ix["income"].mean() * 400), 2),
                   "volatility_pct_pa": round(float(ix["total"].std() * 200), 2)} for c, ix in main_ix.items()}
    first, last = r["date"].min(), r["date"].max()
    largest = "BLACKSTONE"
    for line in logs.get("main", "").splitlines():
        if line.startswith("Largest manager:"):
            largest = line.split(":", 1)[1].strip()
    meta = {
        "name": "BDC European Direct Lending Index", "short_name": "OpenDL Europe", "version": args.version,
        "doi": args.doi, "created": date.today().isoformat(), "frequency": "quarterly (calendar quarter-ends)",
        "first_return_quarter": str(first), "last_return_quarter": str(last),
        "source": "SEC Financial Statement and Notes data sets: XBRL-tagged schedules of investments of business "
                  "development companies (us-gaap:InvestmentIdentifierAxis)",
        "specification": {
            "universe": "loans in EUR, GBP, CHF, SEK, NOK, DKK, PLN held by direct lending BDCs; revolvers, delayed-draw "
                        "tranches, bonds, equipment finance and structured finance excluded",
            "returns": "in loan currency (fair values converted with quarter-end Federal Reserve H.10 rates)",
            "coupon": "tagged interest rate; else rate stated in the identifier; else 3-month base rate plus stated "
                      "spread; else median of the BDC, currency and quarter",
            "repayment_threshold": 95, "distress_threshold": 80, "recovery_pct_of_par": 70.8,
            "non_accrual": "described as non-accrual or valued below 70 (BDCs do not tag non-accrual status)",
            "main_index": "equal-weighted across managers with at least 10 positions; value-weighted within managers",
            "largest_manager": largest.title(),
        },
        "summary": summary, "validation": val,
        "open_items": ["PIK: include the XBRL fact InvestmentInterestRatePaidInKind before the next update"],
    }
    (out / "metadata.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    readme = f"""# OpenDL Europe: BDC European Direct Lending Index (v{args.version})

Quarterly return index of European direct lending (middle market loans in European currencies), constructed
entirely from public SEC filings: the XBRL-tagged schedules of investments of US business development companies
(BDCs). {('DOI: https://doi.org/' + args.doi) if args.doi else ''}

Return quarters {first} to {last}. Author: Thomas Mählmann. Website: https://loanfactors.org

## What the index measures

European direct lending as held by the BDCs of US and global managers (for example Blackstone, Apollo, HPS,
Goldman Sachs, Blue Owl, Oaktree). European lenders that do not file with the SEC are not covered. Returns are in
the currency of each loan, gross of fees and unlevered, and reflect fund valuations, not transaction prices.

## Files

| File | Content |
|---|---|
| `opendl_europe_returns.csv` | Quarterly returns (decimal) of the main index `ew_managers` (equal-weighted across managers with at least 10 positions), `vw_all` and `vw_ex_largest`, with income, accretion, price, realized and unrealized components |
| `opendl_europe_subindices.csv` | Value-weighted sub-indices: first lien only, EUR loans, GBP loans |
| `opendl_europe_variants.csv` | Main and value-weighted index with a repayment threshold of 80 (upper bound) and with observed coupons only |
| `opendl_europe_barometer.csv` | Loans marked below 80 and below 90 (% of estimated cost), trailing four-quarter realized and unrealized returns |
| `opendl_europe_universe.csv` | Positions, BDCs, managers, market value, median price and coupon, currency mix, share of the largest manager |
| `metadata.json` | Specification, summary and validation statistics |

## Method in brief

Holdings are taken from the XBRL facts InvestmentOwnedAtFairValue, InvestmentOwnedAtCost,
InvestmentOwnedBalancePrincipalAmount (whose unit gives the loan currency) and InvestmentInterestRate. Subtotals,
equity, cash, revolvers, delayed-draw tranches, bonds and structured finance are removed; mislabeled currencies are
corrected from the ratio of cost to principal; positions are followed from quarter to quarter by normalized
identifiers, with renamed positions linked by the distinctive words of the borrower name. Returns, exits and the
estimated cost basis follow OpenDL US (Registered Fund Direct Lending Index).

## Validation (see metadata.json)

The same loans valued by the same manager in a registered fund (Form N-PORT) and in a BDC differ by a median of
less than 0.2 points. Compared with the S&P Lincoln European Senior Debt Index, the first-lien sub-index differs by
about 0.25 percentage points per year. No third-party index data are included in this release.

## Open items

- Payment-in-kind interest: the XBRL fact InvestmentInterestRatePaidInKind will be included from the next update.

## License

CC BY 4.0. Please cite this release by its DOI.
"""
    (out / "README.md").write_text(readme, encoding="utf-8")
    files = sorted(x for x in out.iterdir() if x.is_file() and x.name != "SHA256SUMS.txt")
    (out / "SHA256SUMS.txt").write_text("".join(f"{sha256(x)}  {x.name}\n" for x in files), encoding="utf-8")
    if args.zip:
        shutil.make_archive(str(out), "zip", out)
    print(f"\nRelease written to: {out}")
    print(json.dumps({"summary": summary, "validation": val}, indent=1))


if __name__ == "__main__":
    main()
