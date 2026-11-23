#!/usr/bin/env python3
"""
us_bdc_export.py

Versioned public release of OpenDL US BDC (BDC US Direct Lending Index), for Zenodo and loanfactors.org.

The script runs eu_index.py --region us for the published specification, the first-lien sub-index and the
documented variants, and collects the results into one release folder:

    opendl_us_bdc_returns.csv      quarterly returns of the main index (ew_managers), the value-weighted index
                                   (vw_all) and the value-weighted index without the largest manager
                                   (vw_ex_largest), with income, accretion, price, realized and unrealized returns
    opendl_us_bdc_subindices.csv   value-weighted first-lien sub-index
    opendl_us_bdc_variants.csv     main and value-weighted index with a repayment threshold of 80 (upper bound) and
                                   with observed coupons only
    opendl_us_bdc_barometer.csv    loans marked below 80 and below 90 (% of estimated cost), trailing four-quarter
                                   realized and unrealized returns
    opendl_us_bdc_universe.csv     positions, BDCs, managers, market value, median price and coupon, share of the
                                   largest manager
    metadata.json, README.md, SHA256SUMS.txt

Published specification: US dollar loans held by direct lending BDCs (XBRL schedules of investments), no revolvers,
delayed-draw tranches, bonds, equipment finance or structured finance; repayment threshold 95, distress threshold 80,
recovery 70.8% of par, non-accrual below 70; main index equal-weighted across managers with at least 10 positions;
returns from Q2 2023. Same procedure as OpenDL Europe.

Usage
    python us_bdc_export.py --version 2026.12 --cdli "..\\Loan Fund Data\\cdli_quarterly_clean.csv"
                            --base-csv eu_robustness\\base\\base_rates.csv --doi 10.5281/zenodo.<n> --zip
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

BASE_ARGS = ["--region", "us", "--min-positions", "10"]
RUNS = {"main": [], "first_lien": ["--first-lien-only"], "repayment_80": ["--repay-price", "80"],
        "observed_coupons": ["--no-imputed"]}
COMP = {"total": "total", "income": "income", "accretion": "accretion", "price_ret": "price",
        "realized_cost": "realized", "unrealized_cost": "unrealized"}
CHANGES: dict[str, list[str]] = {}


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
    ap = argparse.ArgumentParser(description="Release of OpenDL US BDC")
    ap.add_argument("--version", required=True)
    ap.add_argument("--bdc-dir", default="bdc_out")
    ap.add_argument("--work-dir", default="us_bdc_release_work")
    ap.add_argument("--out", default="releases")
    ap.add_argument("--cdli", default=None, help="CDLI quarterly returns in % (quarter, total, income, price)")
    ap.add_argument("--pairs", default="us_vehicles/pairs.csv", help="us_vehicles.py output for the same-manager check")
    ap.add_argument("--base-csv", default=None)
    ap.add_argument("--user-agent", default="Research name@example.com")
    ap.add_argument("--doi", default="")
    ap.add_argument("--zip", action="store_true")
    ap.add_argument("--skip-runs", action="store_true")
    args = ap.parse_args()

    work = Path(args.work_dir)
    work.mkdir(exist_ok=True)
    out = Path(args.out) / f"opendl_us_bdc_v{args.version}"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    logs = {}
    for name, extra in RUNS.items():
        d = work / name
        if not args.skip_runs:
            cmd = [sys.executable, "eu_index.py", "--out-dir", str(d), "--user-agent", args.user_agent] + BASE_ARGS + extra
            if args.base_csv:
                cmd += ["--base-csv", args.base_csv]
            print(f"--- {name}")
            res = subprocess.run(cmd, capture_output=True, text=True)
            if res.returncode != 0:
                raise SystemExit(res.stderr[-1500:])
            (d / "log.txt").write_text(res.stdout, encoding="utf-8")
        logs[name] = (d / "log.txt").read_text(encoding="utf-8") if (d / "log.txt").exists() else ""

    main_dir = work / "main"
    codes = {"ew_managers": "EW managers", "vw_all": "VW all", "vw_ex_largest": "VW ex largest"}
    rows = []
    for code, label in codes.items():
        ix = read_ix(main_dir, label.replace(" ", "_").lower())
        t = pd.DataFrame({dst: ix[src] if src in ix else np.nan for src, dst in COMP.items()})
        if code == "ew_managers":
            t[["accretion", "realized", "unrealized"]] = np.nan
        t["positions"] = ix.get("positions")
        t["managers"] = ix.get("managers", np.nan)
        t["index"] = code
        rows.append(t)
    r = pd.concat(rows).reset_index().rename(columns={"month_end": "date"})
    r["date"] = pd.to_datetime(r["date"]).dt.date
    for c in ["positions", "managers"]:
        r[c] = pd.to_numeric(r[c], errors="coerce").round().astype("Int64")
    r = r[["date", "index", "total", "income", "accretion", "price", "realized", "unrealized", "positions", "managers"]]
    r.sort_values(["index", "date"]).to_csv(out / "opendl_us_bdc_returns.csv", index=False, float_format="%.6f")

    ix = read_ix(work / "first_lien", "vw_all")
    pd.DataFrame({"date": ix.index.date, "series": "vw_first_lien", "total": ix["total"], "income": ix["income"],
                  "price": ix["price_ret"], "positions": ix["positions"]}) \
        .to_csv(out / "opendl_us_bdc_subindices.csv", index=False, float_format="%.6f")

    var = []
    for name in ["repayment_80", "observed_coupons"]:
        for code, label in [("ew_managers", "EW managers"), ("vw_all", "VW all")]:
            ix = read_ix(work / name, label.replace(" ", "_").lower())
            var.append(pd.DataFrame({"date": ix.index.date, "variant": name, "index": code, "total": ix["total"],
                                     "income": ix["income"], "price": ix["price_ret"]}))
    pd.concat(var).to_csv(out / "opendl_us_bdc_variants.csv", index=False, float_format="%.6f")

    b = pd.read_csv(main_dir / "credit_health_barometer.csv", index_col=0, parse_dates=True)
    keep = {"marked < 80 % cost": "marked_below_80_pct", "marked < 90 % cost": "marked_below_90_pct",
            "marked < 90 % cost (ex largest)": "marked_below_90_pct_ex_largest",
            "T4Q realized (cost) % (VW)": "realized_t4q_pct", "T4Q unrealized % (VW)": "unrealized_t4q_pct"}
    b = b[[c for c in keep if c in b]].rename(columns=keep)
    b.index = b.index.date
    b.index.name = "date"
    b.round(4).to_csv(out / "opendl_us_bdc_barometer.csv")

    p = pd.read_parquet(Path(args.bdc_dir) / "bdc_positions.parquet")
    p = p[p["dl_bdc"] & p["ccy"].eq("USD") & p["month_end"].dt.month.isin([3, 6, 9, 12]) & p["price"].between(1, 150)
          & ~p["instrument"].isin(["bond", "equipment", "revolver", "delayed_draw"]) & (p["month_end"] >= "2023-03-31")]
    n_q = p.groupby("month_end").size()
    thin = [q for i, q in enumerate(n_q.index) if i > 0 and n_q[q] < 0.5 * n_q.iloc[:i].tail(4).median()]
    p = p[~p["month_end"].isin(thin)]
    g = p.groupby("month_end")
    u = pd.DataFrame({"positions": g.size(), "bdcs": g["cik"].nunique(), "managers": g["manager"].nunique(),
                      "market_value_usd_bn": g["fv_usd"].sum() / 1e9, "median_price": g["price"].median(),
                      "median_coupon_pct": g["coupon"].median()})
    u["share_first_lien"] = p[p["instrument"] == "first_lien"].groupby("month_end")["fv_usd"].sum() \
        .reindex(u.index, fill_value=0) / g["fv_usd"].sum()
    mv = p.groupby(["month_end", "manager"])["fv_usd"].sum()
    u["largest_manager_share"] = mv.groupby(level=0).max() / mv.groupby(level=0).sum()
    u.index = u.index.date
    u.index.name = "date"
    u.round(4).to_csv(out / "opendl_us_bdc_universe.csv")

    val = {}
    if args.cdli:
        c = pd.read_csv(args.cdli)
        c[c.columns[0]] = pd.to_datetime(c[c.columns[0]]) + pd.offsets.QuarterEnd(0)
        c = c.set_index(c.columns[0])
        for k, name in [("ew_managers", "ew_managers"), ("vw_all", "vw_all")]:
            ix = read_ix(main_dir, name)
            j = pd.concat([ix["total"] * 100, c["total"]], axis=1, sort=True).dropna()
            rec = {"quarters": int(len(j)), "corr_cdli": round(float(j.iloc[:, 0].corr(j.iloc[:, 1])), 4),
                   "diff_cdli_pp_pa": round(float(ann(j.iloc[:, 0] / 100) - ann(j.iloc[:, 1] / 100)), 3)}
            for comp, mine in [("income", "income"), ("price", "price_ret")]:
                if comp in c:
                    jj = pd.concat([ix[mine] * 100, c[comp]], axis=1, sort=True).dropna()
                    if len(jj) >= 3:
                        rec[f"corr_{comp}"] = round(float(jj.iloc[:, 0].corr(jj.iloc[:, 1])), 4)
                        rec[f"{comp}_pa_index"] = round(float(jj.iloc[:, 0].mean() * 4), 3)
                        rec[f"{comp}_pa_cdli"] = round(float(jj.iloc[:, 1].mean() * 4), 3)
            val[k] = rec
    pp = Path(args.pairs)
    if pp.exists():
        q = pd.read_csv(pp)
        q = q[q["same_manager"]]
        if len(q):
            val["same_borrower_registered_fund_vs_bdc_same_manager"] = {
                "pairs": int(len(q)), "borrowers": int(q["borrower"].nunique()),
                "median_abs_diff": round(float(q["absdiff"].median()), 3),
                "within_1pt": round(float((q["absdiff"] <= 1).mean()), 3)}

    main_ix = {cd: read_ix(main_dir, l.replace(" ", "_").lower()) for cd, l in codes.items()}
    summary = {cd: {"annualized_total_pct": round(float(ann(ix["total"])), 2),
                    "annualized_income_pct": round(float(ix["income"].mean() * 400), 2),
                    "volatility_pct_pa": round(float(ix["total"].std() * 200), 2)} for cd, ix in main_ix.items()}
    first, last = r["date"].min(), r["date"].max()
    largest = "BLACKSTONE"
    for line in logs.get("main", "").splitlines():
        if line.startswith("Largest manager:"):
            largest = line.split(":", 1)[1].strip()
    meta = {
        "name": "BDC US Direct Lending Index", "short_name": "OpenDL US BDC", "version": args.version, "doi": args.doi,
        "created": date.today().isoformat(), "frequency": "quarterly (calendar quarter-ends)",
        "first_return_quarter": str(first), "last_return_quarter": str(last),
        "source": "SEC Financial Statement and Notes data sets: XBRL-tagged schedules of investments of business "
                  "development companies (us-gaap:InvestmentIdentifierAxis)",
        "specification": {
            "universe": "US dollar loans held by direct lending BDCs; revolvers, delayed-draw tranches, bonds, equipment "
                        "finance and structured finance excluded",
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

    vt = []
    vw = val.get("vw_all")
    if vw:
        vt.append(f"Compared with the Cliffwater Direct Lending Index (CDLI) over {vw['quarters']} common quarters, the "
                  f"value-weighted index has a correlation of {vw['corr_cdli']:.2f} and differs by "
                  f"{vw['diff_cdli_pp_pa']:+.2f} percentage points per year"
                  + (f"; price returns: {vw['price_pa_index']:.2f}% against {vw['price_pa_cdli']:.2f}% per year, income: "
                     f"{vw['income_pa_index']:.2f}% against {vw['income_pa_cdli']:.2f}%" if "price_pa_index" in vw else "")
                  + ". Both indices are built from the same filings, so the comparison validates the processing and the "
                    "return method; income is lower because the index uses contractual coupons, without fees and the "
                    "accretion of discounts.")
    sm = val.get("same_borrower_registered_fund_vs_bdc_same_manager")
    if sm:
        vt.append(f"Loans to the same borrowers held by the same manager in a registered fund (Form N-PORT) and in a BDC "
                  f"differ by a median of {sm['median_abs_diff']:.2f} points ({sm['within_1pt']:.0%} within one point).")
    validation_text = (" ".join(vt) + "\n\n") if vt else ""
    changes = CHANGES.get(args.version, [])
    changes_text = ("\n## Changes in version " + args.version + "\n\n" + "".join(f"- {c}\n" for c in changes)) if changes else ""
    readme = f"""# OpenDL US BDC: BDC US Direct Lending Index (v{args.version})

Quarterly return index of US direct lending (middle market loans in US dollars), constructed entirely from public
SEC filings: the XBRL-tagged schedules of investments of US business development companies (BDCs).
{('DOI: https://doi.org/' + args.doi) if args.doi else ''}

Return quarters {first} to {last}. Author: Thomas Mählmann. Website: https://loanfactors.org

## What the index measures

US direct lending as held by BDCs, which hold a large part of US middle market lending. Returns are gross of fees and
unlevered and reflect fund valuations, not transaction prices. OpenDL US BDC complements OpenDL US, which measures
the direct loans of registered closed-end funds from Form N-PORT, and OpenDL Europe, which applies the same procedure
to the European loans of BDCs.

## Files

| File | Content |
|---|---|
| `opendl_us_bdc_returns.csv` | Quarterly returns (decimal) of the main index `ew_managers` (equal-weighted across managers with at least 10 positions), `vw_all` and `vw_ex_largest`, with income, accretion, price, realized and unrealized components |
| `opendl_us_bdc_subindices.csv` | Value-weighted first-lien sub-index |
| `opendl_us_bdc_variants.csv` | Main and value-weighted index with a repayment threshold of 80 (upper bound) and with observed coupons only |
| `opendl_us_bdc_barometer.csv` | Loans marked below 80 and below 90 (% of estimated cost), trailing four-quarter realized and unrealized returns |
| `opendl_us_bdc_universe.csv` | Positions, BDCs, managers, market value, median price and coupon, share of first-lien loans, share of the largest manager |
| `metadata.json` | Specification, summary and validation statistics |

## Method in brief

As for OpenDL Europe: holdings from the XBRL facts InvestmentOwnedAtFairValue, InvestmentOwnedAtCost,
InvestmentOwnedBalancePrincipalAmount and InvestmentInterestRate; subtotals, equity, cash, revolvers, delayed-draw
tranches, bonds and structured finance removed; positions followed from quarter to quarter by normalized identifiers
and linked by the distinctive words of the borrower name. Annualized total returns compound quarterly returns;
annualized income and price components are arithmetic averages of quarterly components times four.

## Validation (see metadata.json)

{validation_text}No third-party index data are included in this release.
{changes_text}
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
