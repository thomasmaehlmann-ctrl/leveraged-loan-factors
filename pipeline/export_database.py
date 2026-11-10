#!/usr/bin/env python3
"""
export_database.py

Builds a versioned public release of the leveraged loan factor database from
loan_characteristics_M.parquet (output of loan_characteristics.py).

Release folder:  <out-root>/loanfactors_v<version>/
    factor_returns.csv               long-format returns of all factor and quintile portfolios
    factor_summary.csv               performance statistics per factor and specification
    universe_stats.csv               monthly universe size and signal coverage
    characteristics_distribution.csv monthly cross-sectional distribution of each signal
    portfolio_counts.csv             number of loans per portfolio at formation
    factor_definitions.csv           factor codes, signals, preferred side, sources
    metadata.json                    version, sample, settings, data and code provenance
    README.md                        description, citation, license, known limitations
    SHA256SUMS.txt                   checksums of all files

Specification grid
    weighting    ew | vw | vw_cap   (vw: 12-month average market value of fund holdings,
                                     vw_cap: vw capped at the monthly 80th percentile)
    holding      1 | 3 | 6 | 12 months (overlapping cohorts, Jegadeesh/Titman)
    lag          0 | 1 month         (implementation lag between signal and first return month)
    return_type  excess | total      (excess over the free base rate | total return)

No loan-level data are published (identifier licensing). Everything can be reproduced from the
SEC Form N-PORT data sets with the open-source pipeline.

Usage
    python export_database.py --version 2026.11 --base-rate "90-day average SOFR (FRED SOFR90DAYAVG), \
+26.161 bp until 2023-06"
    python export_database.py --version 2026.11 --previous releases/loanfactors_v2026.08
"""

import argparse
import hashlib
import json
import shutil
import warnings
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from factor_portfolios import nw, portfolio_returns, stats

warnings.filterwarnings("ignore", message="invalid value encountered in sqrt")

# code -> (column, preferred direction, name, signal description, source)
FACTORS = {
    "value":       ("value_pd", 1, "Value (PD)",
                    "Spread-to-maturity divided by model-implied 12-month default probability",
                    "Maehlmann & Reck (2024), JPM; PD estimated from public loan data"),
    "momentum":    ("mom_3m_skip", 1, "Momentum",
                    "Cumulative excess return over months t-3 to t-1 (skipping month t)",
                    "Maehlmann & Sukonnik (2022), FAJ; Maehlmann & Reck (2024), JPM"),
    "illiquidity": ("illiq_funds", 1, "Illiquidity",
                    "Fewer reporting funds holding the loan (ties broken by held par amount)",
                    "Maehlmann & Reck (2024), JPM; bid-ask spread replaced by fund-count proxy"),
    "quality":     ("pd_hat", -1, "Quality (PD)",
                    "Model-implied 12-month default probability (low preferred)",
                    "Maehlmann & Reck (2024), JPM; PD estimated from public loan data"),
    "low_risk":    ("low_risk", -1, "Low Risk",
                    "Spread duration (low preferred)", "Maehlmann & Reck (2024), JPM"),
    "carry":       ("carry", 1, "Carry", "Spread-to-maturity", "Maehlmann & Reck (2024), JPM"),
    "ivol":        ("ivol", -1, "IVOL",
                    "Idiosyncratic volatility from a 12-month market model with one lag (low preferred)",
                    "Low-risk literature; market = equal-weighted loan universe"),
    "bab":         ("bab_beta", -1, "BAB",
                    "Dimson beta from a 12-month market model with one lag (low preferred)",
                    "Frazzini & Pedersen (2014); market = equal-weighted loan universe"),
    "combi":       ("combi_jpm", 1, "Combi",
                    "Equal-weighted average of cross-sectional z-scores of the eight factors above",
                    "Maehlmann & Reck (2024), JPM, extended by IVOL and BAB"),
}
WEIGHTINGS = ["ew", "vw", "vw_cap"]
HOLDINGS = [1, 3, 6, 12]
LAGS = [0, 1]
RETURN_TYPES = {"excess": "ret", "total": "tr"}
QUANTILES = 5
PPY, NW_LAGS = 12, 3


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def load(base: Path, exit_mode: str) -> pd.DataFrame:
    df = pd.read_parquet(base / "loan_characteristics_M.parquet")
    df["MONTH_END"] = pd.to_datetime(df["MONTH_END"])
    if exit_mode == "none" and "exit_row" in df:
        df = df[~df["exit_row"].fillna(False).astype(bool)]
    if "tr" not in df:
        raise SystemExit("Column 'tr' missing: please rerun loan_characteristics.py (current version).")
    df["_all"] = 1.0
    return df.sort_values(["LOAN_KEY", "MONTH_END"]).reset_index(drop=True)


def build_returns(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    specs = [(w, h, l, rt) for w in WEIGHTINGS for h in HOLDINGS for l in LAGS for rt in RETURN_TYPES]
    for i, (w, h, l, rt) in enumerate(specs, 1):
        print(f"  [{i}/{len(specs)}] weighting={w} holding={h} lag={l} return_type={rt}")
        for code, (col, direction, *_rest) in FACTORS.items():
            if col not in df or not df.loc[df["universe"], col].notna().any():
                continue
            pr = portfolio_returns(df, col, QUANTILES, 1, h, RETURN_TYPES[rt], l, w)
            if pr.empty or QUANTILES not in pr or 1 not in pr:
                continue
            best, worst = (QUANTILES, 1) if direction == 1 else (1, QUANTILES)
            pr = pr.rename(columns={c: f"Q{c}" for c in range(1, QUANTILES + 1)})
            pr["LS"] = pr[f"Q{best}"] - pr[f"Q{worst}"]
            long = pr.reset_index().melt(id_vars="date", var_name="portfolio", value_name="ret").dropna()
            long["factor"] = code
            long[["weighting", "holding", "lag", "return_type"]] = [w, h, l, rt]
            rows.append(long)
        # market index: all loans in the universe (no signal)
        if h == 1:
            pr = portfolio_returns(df, "_all", 1, 1, 1, RETURN_TYPES[rt], l, w)
            m = pr[["BM"]].rename(columns={"BM": "ret"}).reset_index()
            m["portfolio"], m["factor"] = "MKT", "market"
            m[["weighting", "holding", "lag", "return_type"]] = [w, h, l, rt]
            rows.append(m)
    out = pd.concat(rows, ignore_index=True)
    out["date"] = pd.to_datetime(out["date"]).dt.strftime("%Y-%m-%d")
    cols = ["date", "factor", "portfolio", "weighting", "holding", "lag", "return_type", "ret"]
    return out[cols].sort_values(cols[:-1]).reset_index(drop=True)


def build_summary(fr: pd.DataFrame) -> pd.DataFrame:
    rows = []
    ex = fr[fr["return_type"] == "excess"].copy()
    ex["date"] = pd.to_datetime(ex["date"])
    for (code, w, h, l), g in ex[ex["factor"] != "market"].groupby(["factor", "weighting", "holding", "lag"]):
        p = g.pivot(index="date", columns="portfolio", values="ret")
        direction = FACTORS[code][1]
        best = f"Q{QUANTILES}" if direction == 1 else "Q1"
        if best not in p or "BM" not in p:
            continue
        s = stats(p[best], p["BM"], PPY, NW_LAGS)
        ls = p["LS"].dropna()
        rows.append({
            "factor": code, "weighting": w, "holding": h, "lag": l,
            "start": p.index.min().strftime("%Y-%m"), "end": p.index.max().strftime("%Y-%m"),
            "months": int(s["Periods"]),
            "ls_mean_pa_bp": ls.mean() * PPY * 1e4, "ls_t": nw(ls, None, NW_LAGS).tvalues[0],
            "long_mean_pa_bp": s["Return p.a. (bp)"], "long_vol_pa_bp": s["Volatility p.a. (bp)"],
            "long_sharpe": s["Sharpe ratio"], "bm_sharpe": stats(p["BM"], p["BM"], PPY, NW_LAGS)["Sharpe ratio"],
            "outperformance_pa_bp": s["Outperformance p.a. (bp)"], "outperformance_t": s["t outperformance"],
            "information_ratio": s["Information ratio"],
            "capm_alpha_pa_bp": s["Alpha p.a. (bp)"], "capm_alpha_t": s["t alpha"], "capm_beta": s["Beta"],
            "dimson_alpha_pa_bp": s["Dimson alpha p.a. (bp)"], "dimson_alpha_t": s["t Dimson alpha"],
            "dimson_beta": s["Dimson beta (sum)"],
        })
    return pd.DataFrame(rows).round(4)


def build_universe_stats(df: pd.DataFrame) -> pd.DataFrame:
    u = df[df["universe"]]
    g = u.groupby("MONTH_END")
    out = pd.DataFrame({
        "n_loans": g.size(),
        "n_loans_next_return": g["ret_next"].apply(lambda s: s.notna().sum()),
        "median_price": g["price"].median(),
        "median_stm_pct": g["stm"].median(),
    })
    for code, (col, *_r) in FACTORS.items():
        if col in u:
            out[f"coverage_{code}"] = g[col].apply(lambda s: s.notna().mean())
    exits = df[df.get("exit_row", False) == True].groupby("MONTH_END").size() if "exit_row" in df else None
    if exits is not None:
        out["n_imputed_repayments"] = exits.reindex(out.index).fillna(0).astype(int)
    out.index = out.index.strftime("%Y-%m-%d")
    return out.rename_axis("date").reset_index().round(4)


def build_distribution(df: pd.DataFrame) -> pd.DataFrame:
    u = df[df["universe"]]
    rows = []
    for code, (col, *_r) in FACTORS.items():
        if col not in u:
            continue
        g = u.groupby("MONTH_END")[col]
        d = pd.DataFrame({"n": g.count(), "mean": g.mean(), "p10": g.quantile(0.10), "p25": g.quantile(0.25),
                          "p50": g.median(), "p75": g.quantile(0.75), "p90": g.quantile(0.90)})
        d = d[d["n"] > 0]
        d["factor"] = code
        rows.append(d)
    out = pd.concat(rows).rename_axis("date").reset_index()
    out["date"] = out["date"].dt.strftime("%Y-%m-%d")
    return out[["date", "factor", "n", "mean", "p10", "p25", "p50", "p75", "p90"]].round(6)


def build_counts(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for code, (col, *_r) in FACTORS.items():
        d = df[df["universe"] & df[col].notna()]
        if d.empty:
            continue
        pct = d.groupby("MONTH_END")[col].rank(pct=True, method="first")
        port = np.ceil(pct * QUANTILES).clip(1, QUANTILES).astype(int)
        c = d.assign(portfolio="Q" + port.astype(str)).groupby(["MONTH_END", "portfolio"]).size().rename("n_loans")
        c = c.reset_index().assign(factor=code)
        rows.append(c)
    out = pd.concat(rows).rename(columns={"MONTH_END": "formation_date"})
    out["formation_date"] = out["formation_date"].dt.strftime("%Y-%m-%d")
    return out[["formation_date", "factor", "portfolio", "n_loans"]]


def build_definitions(fr: pd.DataFrame) -> pd.DataFrame:
    first = fr.groupby("factor")["date"].min()
    rows = [{"factor": "market", "name": "Market", "signal": "All loans in the investable universe",
             "preferred": "", "source": "Benchmark index of this database",
             "available_from": first.get("market", "")}]
    for code, (col, direction, name, signal, source) in FACTORS.items():
        rows.append({"factor": code, "name": name, "signal": signal,
                     "preferred": f"Q{QUANTILES}" if direction == 1 else "Q1",
                     "source": source, "available_from": first.get(code, "")})
    return pd.DataFrame(rows)


README = """# Leveraged Loan Factors — release v{version}

The first publicly available factor database for US leveraged loans, built entirely from
public SEC Form N-PORT filings of US registered investment funds.

Author: Thomas Mählmann. Data release: {created}. Sample: {start} to {end}.

## Files
| File | Content |
|---|---|
| `factor_returns.csv` | Monthly returns of factor long-short (LS), quintile (Q1–Q5) and benchmark (BM) portfolios; market index (factor `market`, portfolio `MKT`) |
| `factor_summary.csv` | Performance statistics per factor and specification (excess returns) |
| `universe_stats.csv` | Monthly universe size, signal coverage and imputed repayments |
| `characteristics_distribution.csv` | Monthly cross-sectional distribution of each signal |
| `portfolio_counts.csv` | Number of loans per portfolio at formation |
| `factor_definitions.csv` | Factor codes, signals, preferred side and sources |
| `metadata.json` | Version, sample, settings and provenance |

## Specifications
Every series is identified by `factor`, `portfolio`, `weighting` (ew, vw, vw_cap), `holding`
(1, 3, 6, 12 months), `lag` (0 or 1 month implementation lag) and `return_type` (excess, total).
`LS` is the preferred quintile minus the opposite quintile; the preferred side is listed in
`factor_definitions.csv`. `BM` is the equal- or value-weighted average of all loans sorted for
the respective factor. Returns are decimal monthly returns; `date` is the end of the return month.

**Interpreting the low-risk factors.** For IVOL, BAB and Quality the preferred quintile is Q1
(low volatility, low beta, low default probability). Their `LS` returns are often negative: riskier
loans earn higher raw returns. The anomaly lies in risk-adjusted terms: the low-risk quintile earns
more than its low market exposure implies, which shows up as a positive alpha against the benchmark
in `factor_summary.csv` (see Frazzini and Pedersen, 2014). Please evaluate these factors by alpha,
not by the raw long-short spread.

## Methodology (short)
- Prices: fair values reported by funds in Form N-PORT (median across reporting funds).
- Universe: identified loans (LoanX ID, CUSIP, ISIN or FIGI), price between min(20th percentile, 80)
  and 105, remaining maturity above 120 days.
- Excess returns: total return minus {base_rate}.
- Loans that leave the sample with a last price between 95 and 105, held by at least two funds and
  not flagged in default, are assumed to be repaid at par in the following month.
- Holding periods above one month use overlapping cohorts (Jegadeesh and Titman, 1993) with
  weights fixed at formation.
- Value-weighted portfolios use the 12-month average market value of fund holdings, not the total
  facility size.

## Known limitations
- Fair values are model or vendor marks, not transaction prices.
- Funds disclose holdings publicly only at their fiscal quarter-ends, so the monthly cross-section
  varies with the set of reporting funds.
- N-PORT data are published with a delay of about 60 days; the `lag = 1` series approximate an
  implementable strategy.
- The sample starts in late 2019; signals requiring estimation windows start later
  (see `available_from`).

## Validation
The equal-weighted market index has a monthly correlation of {corr} with the Morningstar LSTA US
Leveraged Loan Index over {corr_period}.

## Citation and license
Please cite: Mählmann, T., Leveraged Loan Factors, release v{version} ({year}), {doi}.
Data: CC BY 4.0. Code: MIT License, {repo}.
"""


def main() -> None:
    ap = argparse.ArgumentParser(description="Export a versioned release of the leveraged loan factor database")
    ap.add_argument("--dir", default="nport_out", help="pipeline output folder")
    ap.add_argument("--out-root", default="releases", help="folder for releases")
    ap.add_argument("--version", default=date.today().strftime("%Y.%m"))
    ap.add_argument("--base-rate", required=True,
                    help='description of the base rate used in nport_loan_returns.py, e.g. '
                         '"90-day average SOFR (FRED SOFR90DAYAVG), +26.161 bp until 2023-06"')
    ap.add_argument("--exit", choices=["impute", "none"], default="impute")
    ap.add_argument("--index-corr", default="n/a", help="correlation with the LSTA index from benchmark_validation.py")
    ap.add_argument("--index-corr-period", default="n/a")
    ap.add_argument("--doi", default="DOI to be assigned")
    ap.add_argument("--repo", default="GitHub repository to be announced")
    ap.add_argument("--previous", default=None, help="previous release folder for plausibility checks")
    ap.add_argument("--zip", action="store_true", help="also write a ZIP archive")
    args = ap.parse_args()

    base = Path(args.dir)
    rel = Path(args.out_root) / f"loanfactors_v{args.version}"
    if rel.exists():
        shutil.rmtree(rel)
    rel.mkdir(parents=True)
    print(f"Building release {rel}")

    df = load(base, args.exit)
    print("Portfolio returns ...")
    fr = build_returns(df)
    fr.to_csv(rel / "factor_returns.csv", index=False, float_format="%.8f")
    print("Summary statistics ...")
    summ = build_summary(fr)
    summ.to_csv(rel / "factor_summary.csv", index=False)
    build_universe_stats(df).to_csv(rel / "universe_stats.csv", index=False)
    build_distribution(df).to_csv(rel / "characteristics_distribution.csv", index=False)
    build_counts(df).to_csv(rel / "portfolio_counts.csv", index=False)
    defs = build_definitions(fr)
    defs.to_csv(rel / "factor_definitions.csv", index=False)

    scripts = ["nport_loans.py", "nport_rekey.py", "nport_loan_returns.py", "loan_characteristics.py",
               "factor_portfolios.py", "export_database.py"]
    here = Path(__file__).resolve().parent
    code_hashes = {s: sha256(here / s)[:16] for s in scripts if (here / s).exists()}
    start, end = fr["date"].min(), fr["date"].max()
    meta = {
        "name": "Leveraged Loan Factors", "version": args.version, "created": date.today().isoformat(),
        "author": "Thomas Mählmann", "license_data": "CC BY 4.0", "license_code": "MIT",
        "doi": args.doi, "repository": args.repo,
        "source": "SEC Form N-PORT data sets (https://www.sec.gov/data-research/sec-markets-data/form-n-port-data-sets)",
        "sample_start": start, "sample_end": end,
        "n_loans_universe": int(df.loc[df["universe"], "LOAN_KEY"].nunique()),
        "base_rate": args.base_rate,
        "settings": {
            "quantiles": QUANTILES, "weightings": WEIGHTINGS, "holdings_months": HOLDINGS, "lags_months": LAGS,
            "return_types": list(RETURN_TYPES), "universe": "identified loans; price in [min(p20, 80), 105]; "
            "remaining maturity > 120 days", "exit_rule": args.exit,
            "exit_assumption": "repayment at par if last price in [95, 105], >= 2 funds, no default flag",
            "vw_weights": "12-month average market value of fund holdings; vw_cap capped at monthly 80th percentile",
            "newey_west_lags": NW_LAGS,
        },
        "validation": {"corr_with_morningstar_lsta_lli": args.index_corr, "period": args.index_corr_period},
        "code_sha256_prefix": code_hashes,
    }
    (rel / "metadata.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    (rel / "README.md").write_text(README.format(
        version=args.version, created=meta["created"], start=start, end=end, base_rate=args.base_rate,
        corr=args.index_corr, corr_period=args.index_corr_period, year=date.today().year,
        doi=args.doi, repo=args.repo), encoding="utf-8")

    with open(rel / "SHA256SUMS.txt", "w", encoding="utf-8") as fh:
        for f in sorted(rel.iterdir()):
            if f.name != "SHA256SUMS.txt":
                fh.write(f"{sha256(f)}  {f.name}\n")

    # ---- plausibility checks
    print("\n=== Plausibility checks ===")
    print(f"Rows in factor_returns.csv: {len(fr):,} | factors: {fr['factor'].nunique()} | "
          f"sample: {start} to {end}")
    main_spec = summ[(summ["weighting"] == "ew") & (summ["holding"] == 1) & (summ["lag"] == 0)]
    print("\nMain specification (ew, holding 1, lag 0):")
    print(main_spec[["factor", "start", "months", "ls_mean_pa_bp", "ls_t", "dimson_alpha_pa_bp",
                     "dimson_alpha_t"]].to_string(index=False))
    if args.previous:
        prev = Path(args.previous) / "factor_returns.csv"
        if prev.exists():
            old = pd.read_csv(prev)
            key = ["date", "factor", "portfolio", "weighting", "holding", "lag", "return_type"]
            m = fr.merge(old, on=key, suffixes=("", "_prev"))
            chk = m[(m["portfolio"] == "LS") & (m["weighting"] == "ew") & (m["lag"] == 0)
                    & (m["return_type"] == "excess")].groupby(["factor", "holding"]).apply(
                lambda g: pd.Series({"corr": g["ret"].corr(g["ret_prev"]),
                                     "max_abs_diff_bp": (g["ret"] - g["ret_prev"]).abs().max() * 1e4}),
                include_groups=False)
            print("\nComparison with previous release (LS, ew, lag 0, overlapping months):")
            print(chk.round(3).to_string())
            flagged = chk[chk["corr"] < 0.95]
            if len(flagged):
                print("\nWARNING: correlation below 0.95 with the previous release for:", list(flagged.index))
        else:
            print(f"Previous release not found: {prev}")

    if args.zip:
        shutil.make_archive(str(rel), "zip", rel)
        print(f"\nZIP archive: {rel}.zip")
    print(f"\nRelease written to: {rel}")


if __name__ == "__main__":
    main()
