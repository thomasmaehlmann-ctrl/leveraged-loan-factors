#!/usr/bin/env python3
"""
dl_export.py

Builds a versioned public release of the direct lending index (for Zenodo and loanfactors.org).

The script recomputes the index from dl_out/dl_positions.parquet with the published specification
(functions of dl_index.py), so that the release does not depend on earlier test runs.

Files of a release (releases/<prefix>_v<version>/)
    dl_index_returns.csv          quarterly returns of the indices with their components
    dl_credit_barometer.csv       credit health barometer per quarter-end
    dl_universe_stats.csv         positions, borrowers, funds, managers, market value, median price and coupon
    dl_index_variants.csv         quarterly returns of the sensitivity variants (main and value-weighted index)
    dl_robustness.csv             annualized results of the sensitivity variants (if dl_out/robustness.csv exists)
    metadata.json                 version, sample, specification, recovery estimate, validation statistics
    README.md                     description, methodology in brief, interpretation notes, limitations
    SHA256SUMS.txt                checksums

Published index series
    ew_managers      main index: equal-weighted average of manager returns (managers with >= 10 positions)
    vw_all           value-weighted over all positions
    vw_ex_largest    value-weighted without the largest manager by market value

The release contains no third-party index data. Validation statistics against the Cliffwater Direct Lending
Index (correlations, differences) are computed locally from --cdli / --cdli-annual and reported only as
summary statistics.

Usage
    python dl_export.py --version 2026.12 --cdli cdli_quarterly_clean.csv --cdli-annual cdli_annual_clean.csv
                        --ll-release releases/loanfactors_v2026.12 --doi 10.5281/zenodo.xxxxx --zip
"""

import argparse
import hashlib
import json
import shutil
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

import dl_index as di

INDEX_NAMES = {"EW managers": "ew_managers", "VW all": "vw_all", "VW ex largest": "vw_ex_largest"}
COMPONENTS = {"total": "total", "income": "income", "accretion": "accretion", "price_ret": "price",
              "realized_cost": "realized", "unrealized_cost": "unrealized"}


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser(description="Release of the direct lending index")
    ap.add_argument("--version", required=True)
    ap.add_argument("--dir", default="dl_out")
    ap.add_argument("--out", default="releases")
    ap.add_argument("--prefix", default="dlindex")
    ap.add_argument("--name", default="Registered Fund Direct Lending Index")
    ap.add_argument("--start", default="2021-12-31")
    ap.add_argument("--min-positions", type=int, default=10)
    ap.add_argument("--cdli", default=None)
    ap.add_argument("--cdli-annual", default=None)
    ap.add_argument("--ll-release", default=None)
    ap.add_argument("--doi", default="")
    ap.add_argument("--zip", action="store_true")
    args = ap.parse_args()

    out = Path(args.out) / f"{args.prefix}_v{args.version}"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    # ---- recompute with the published specification
    pos = pd.read_parquet(Path(args.dir) / "dl_positions.parquet")
    pos["month_end"] = pd.to_datetime(pos["month_end"])
    pos = pos[pos["price"].between(1, 150)]
    pos = di.add_cost_basis(pos)
    rec = di.estimate_recovery(pos)
    ret = di.position_returns(pos, 0.0, rec, 80.0)
    ret = ret[ret["exit"] | ret["distress"] | (ret["total"].abs() <= 0.5)]
    ret = ret[ret["month_end"] > pd.Timestamp(args.start)]
    largest = ret.groupby("manager")["v0"].sum().idxmax()
    ix = di.build_indices(ret, args.min_positions, largest)

    # ---- index returns (decimal returns per quarter)
    rows = []
    for k, code in INDEX_NAMES.items():
        dfi = ix[k].copy()
        for src, dst in COMPONENTS.items():
            v = dfi[src] if src in dfi else np.nan
            if k == "EW managers" and src in ("accretion", "realized_cost", "unrealized_cost"):
                v = np.nan        # the split is meaningful only with value weights
            dfi[dst] = v
        dfi["index"] = code
        dfi["managers"] = dfi["managers"] if "managers" in dfi else np.nan
        rows.append(dfi[["index"] + list(COMPONENTS.values()) + ["positions", "managers"]])
    ret_tab = pd.concat(rows).reset_index().rename(columns={"month_end": "date"})
    ret_tab["date"] = pd.to_datetime(ret_tab["date"]).dt.date
    ret_tab = ret_tab.sort_values(["index", "date"])
    for c in ["positions", "managers"]:
        ret_tab[c] = pd.to_numeric(ret_tab[c], errors="coerce").round().astype("Int64")
    ret_tab.to_csv(out / "dl_index_returns.csv", index=False, float_format="%.6f")

    # ---- barometer
    bar = di.credit_barometer(pos, ix, largest, args.start)
    keep = {"non-accrual % cost": "non_accrual_pct", "marked < 90 % cost": "marked_below_90_pct",
            "PIK % par": "pik_pct", "amended PIK % par": "amended_pik_pct",
            "non-accrual % cost (ex largest)": "non_accrual_pct_ex_largest",
            "marked < 90 % cost (ex largest)": "marked_below_90_pct_ex_largest",
            "T4Q realized (cost) % (VW)": "realized_t4q_pct", "T4Q unrealized % (VW)": "unrealized_t4q_pct"}
    b = bar[[c for c in keep if c in bar]].rename(columns=keep)
    b.index = pd.to_datetime(b.index).date
    b.index.name = "date"
    b.round(4).to_csv(out / "dl_credit_barometer.csv")

    # ---- universe statistics
    u = pos[pos["month_end"] >= pd.Timestamp(args.start)]
    us = u.groupby("month_end").agg(positions=("par", "size"), borrowers=("borrower", "nunique"),
                                    funds=("FUND_KEY", "nunique"), managers=("manager", "nunique"),
                                    market_value_usd_bn=("value", lambda x: x.sum() / 1e9),
                                    median_price=("price", "median"), median_coupon_pct=("coupon", "median"))
    lm = u.groupby(["month_end", "manager"])["value"].sum()
    us["largest_manager_share"] = lm.groupby(level=0).max() / lm.groupby(level=0).sum()
    if "interval_fund" in u:
        iv = u[u["interval_fund"].astype(str).str.upper().isin(["TRUE", "Y", "1"])]
        us["interval_fund_share"] = iv.groupby("month_end")["value"].sum() / u.groupby("month_end")["value"].sum()
    us.index = pd.to_datetime(us.index).date
    us.index.name = "date"
    us.round(4).to_csv(out / "dl_universe_stats.csv")

    # ---- quarterly series of the sensitivity variants (main index and value-weighted index)
    variants = {"recovery_60": dict(recovery=60.0), "recovery_50": dict(recovery=50.0),
                "min_positions_5": dict(min_pos=5), "min_positions_20": dict(min_pos=20),
                "repayment_90": dict(repay=90.0), "repayment_97": dict(repay=97.0),
                "distress_70": dict(distress=70.0), "distress_90": dict(distress=90.0),
                "interval_funds_only": dict(interval=True)}
    vrows = []
    for vname, v in variants.items():
        p = pos
        if v.get("interval"):
            if "interval_fund" not in pos.columns:
                continue
            p = pos[pos["interval_fund"].astype(str).str.upper().isin(["TRUE", "Y", "1"])]
        di.REPAY_MIN_PRICE = v.get("repay", 95.0)
        rv = di.position_returns(p, 0.0, v.get("recovery", rec), v.get("distress", 80.0))
        rv = rv[rv["exit"] | rv["distress"] | (rv["total"].abs() <= 0.5)]
        rv = rv[rv["month_end"] > pd.Timestamp(args.start)]
        lg = rv.groupby("manager")["v0"].sum().idxmax()
        ixv = di.build_indices(rv, v.get("min_pos", args.min_positions), lg)
        for k, code in [("EW managers", "ew_managers"), ("VW all", "vw_all")]:
            dv = ixv[k][["total", "income", "price_ret"]].rename(columns={"price_ret": "price"})
            dv["variant"], dv["index"] = vname, code
            vrows.append(dv)
    di.REPAY_MIN_PRICE = 95.0
    if vrows:
        vt = pd.concat(vrows).reset_index().rename(columns={"month_end": "date"})
        vt["date"] = pd.to_datetime(vt["date"]).dt.date
        vt[["date", "variant", "index", "total", "income", "price"]].sort_values(["variant", "index", "date"]).to_csv(
            out / "dl_index_variants.csv", index=False, float_format="%.6f")

    rob = Path(args.dir) / "robustness.csv"
    if rob.exists():
        shutil.copy(rob, out / "dl_robustness.csv")

    # ---- validation statistics (summary only; no third-party data in the release)
    val = {}
    if args.cdli:
        c = pd.read_csv(args.cdli, parse_dates=["quarter"]).set_index("quarter").sort_index()
        c.index = c.index + pd.offsets.QuarterEnd(0)
        for k, code in INDEX_NAMES.items():
            j = pd.concat([ix[k]["total"] * 100, c["total"]], axis=1, sort=True).dropna()
            ji = pd.concat([(ix[k]["income"] + ix[k].get("accretion", 0) * (k != "EW managers")) * 100,
                            c["income"]], axis=1, sort=True).dropna()
            val[code] = {"quarters": int(len(j)), "corr_total": round(float(j.iloc[:, 0].corr(j.iloc[:, 1])), 4),
                         "mean_diff_total_pp_per_quarter": round(float((j.iloc[:, 0] - j.iloc[:, 1]).mean()), 3),
                         "corr_income": round(float(ji.iloc[:, 0].corr(ji.iloc[:, 1])), 4) if len(ji) >= 4 else None}
    if args.cdli_annual:
        ca = pd.read_csv(args.cdli_annual).set_index("year")["total"]
        for k, code in INDEX_NAMES.items():
            t = ix[k]["total"]
            full = t.groupby(t.index.year).filter(lambda x: len(x) == 4)
            yr = ((1 + full).groupby(full.index.year).prod() - 1) * 100
            dd = (yr - ca.reindex(yr.index)).dropna()
            val.setdefault(code, {})["mean_abs_diff_calendar_year_pp"] = round(float(dd.abs().mean()), 3)
    if args.ll_release:
        fr = pd.read_csv(Path(args.ll_release) / "factor_returns.csv", parse_dates=["date"])
        mkt = fr.query("portfolio == 'MKT' and weighting == 'ew' and holding == 1 and lag == 0 "
                       "and return_type == 'total'").drop_duplicates("date").set_index("date")["ret"].sort_index()
        llq = (1 + mkt).groupby(mkt.index + pd.offsets.QuarterEnd(0)).prod() - 1
        for k, code in INDEX_NAMES.items():
            dm = di.dimson(ix[k]["total"], llq)
            val.setdefault(code, {})["dimson_beta_on_leveraged_loan_market"] = round(float(dm.get("dimson_beta", np.nan)), 3)

    first = ret_tab["date"].min()
    last = ret_tab["date"].max()
    summ = {code: {"annualized_total_pct": round(float(((1 + ix[k]["total"]).prod() ** (4 / len(ix[k])) - 1) * 100), 2),
                   "volatility_pct_pa": round(float(ix[k]["total"].std() * 200), 2)} for k, code in INDEX_NAMES.items()}
    meta = {
        "name": args.name, "short_name": "OpenDL US", "version": args.version, "doi": args.doi, "created": date.today().isoformat(),
        "frequency": "quarterly (calendar quarter-ends)", "first_return_quarter": str(first),
        "last_return_quarter": str(last),
        "source": "SEC Form N-PORT (registered closed-end funds filing Form N-2; advisers from Form N-CEN)",
        "specification": {
            "universe": "loans without a valid identifier, fair value level 3, funded, corporate, closed-end funds",
            "position": "fund x normalized borrower; tranches of the same borrower in the same fund combined",
            "income": "average coupon of the two quarter-ends / 4 / price; zero in default or non-accrual",
            "repayment_rule": "exit with last mark >= 95 and not in default: repaid at par, half a quarter's coupon",
            "distressed_exits": "default flag, zero coupon or mark < 80: recovery (capped at last mark); others at last mark",
            "recovery_estimate_pct_of_par": round(float(rec), 1),
            "cost_basis": "first mark for new positions, par for positions held before the data begin; add-ons at average mark",
            "ew_min_positions_per_manager": args.min_positions,
            "largest_manager_excluded_in_vw_ex_largest": largest.title(),
        },
        "summary": summ, "validation": val,
    }
    (out / "metadata.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    readme = f"""# {args.name} (v{args.version})

Quarterly return index of US direct lending (middle market corporate loans), constructed entirely from public
SEC Form N-PORT filings of US registered closed-end funds (interval, tender offer and listed credit funds).
{('DOI: https://doi.org/' + args.doi) if args.doi else ''}

Sample: return quarters {first} to {last}. Author: Thomas Mählmann. Website: https://loanfactors.org

## Files

| File | Content |
|---|---|
| `dl_index_returns.csv` | Quarterly returns (decimal) of the indices `ew_managers` (main index), `vw_all` and `vw_ex_largest`, with the components income, accretion, price, realized and unrealized, and the number of positions and managers |
| `dl_credit_barometer.csv` | Credit health indicators per quarter-end (in %): non-accrual share and share marked below 90 (weighted by estimated cost, also without the largest manager), PIK and amended-PIK shares (by par), trailing four-quarter realized and unrealized returns |
| `dl_universe_stats.csv` | Positions, borrowers, funds, managers, market value, median price and coupon, share of the largest manager and of interval funds |
| `dl_index_variants.csv` | Quarterly returns (total, income, price) of the main and value-weighted index under alternative assumptions: recovery rate 60 / 50, minimum positions per manager 5 / 20, repayment threshold 90 / 97, distress threshold 70 / 90, interval funds only |
| `dl_robustness.csv` | Annualized results of the sensitivity variants (if included) |
| `metadata.json` | Specification, recovery estimate, summary and validation statistics |

## Methodology in brief

- **Universe:** loans reported without a valid identifier (LoanX ID, CUSIP, ISIN or FIGI), valued at fair value
  level 3, funded, corporate (real estate, asset-based, consumer and fund finance excluded), held by closed-end funds.
- **Positions:** fund x borrower, all tranches of a borrower in a fund combined; prices are market value per 100 of par.
- **Returns:** income = average coupon of the two quarter-ends / 4 / price at the start of the quarter (zero in
  default or non-accrual); price return = change in price. Exits with a last mark of at least 95 are treated as
  repayments at par; distressed exits are realized at a recovery rate estimated from the data
  ({rec:.1f}% of par: median mark in the first non-accrual quarter), capped at the last mark.
- **Components (value-weighted indices):** realized losses relative to an estimated cost basis; gains over cost at
  repayment are shown as accretion (BDCs accrete purchase discounts through income).
- **Main index:** equal-weighted across managers (advisers from Form N-CEN) with at least {args.min_positions}
  positions; within a manager, positions are weighted by market value.

## Interpretation notes

- Returns reflect fund valuations (fair values), not transaction prices. They are smoothed and dampened relative
  to traded credit: the Dimson beta on the leveraged loan market is about 0.4.
- One manager ({largest.title()}) holds a large share of the market value; the main index weights managers
  equally, and `vw_ex_largest` excludes this manager.
- Income excludes fees not reported in N-PORT (e.g. prepayment fees).
- Returns are gross of fees and unlevered.

## Validation

Correlation of quarterly total returns with the Cliffwater Direct Lending Index (CDLI) and differences are
reported in `metadata.json`. No CDLI data are included in this release. "Cliffwater Direct Lending Index" and
"CDLI" are trademarks of Cliffwater LLC; this index is independent of and not endorsed by Cliffwater.

## License

CC BY 4.0. Please cite this release by its DOI.
"""
    (out / "README.md").write_text(readme, encoding="utf-8")

    files = sorted(p for p in out.iterdir() if p.is_file() and p.name != "SHA256SUMS.txt")
    (out / "SHA256SUMS.txt").write_text("".join(f"{sha256(p)}  {p.name}\n" for p in files), encoding="utf-8")
    if args.zip:
        shutil.make_archive(str(out), "zip", out)
    print(f"\nRelease written to: {out}")
    print(json.dumps({"summary": summ, "validation": val}, indent=1))


if __name__ == "__main__":
    main()
