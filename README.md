# Leveraged Loan Factors

[![Data DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.24113424.svg)](https://doi.org/10.5281/zenodo.24113424)

Open-source pipeline and data releases of **factor returns for US leveraged loans**, built
entirely from public **SEC Form N-PORT** filings of US registered investment funds.

Leveraged loans are private, over-the-counter instruments, and loan-level prices are usually only
available from commercial data vendors. US registered funds, however, report every loan they hold,
with notional and fair value, to the SEC. Aggregating these reports across funds yields a monthly
price panel that tracks the Morningstar LSTA US Leveraged Loan Index with a monthly return
correlation of 0.995 (2019-10 to 2026-04). This repository turns these public filings into a
factor database in the spirit of [JKP Factors](https://jkpfactors.com).

- **Data releases:** Zenodo, [doi:10.5281/zenodo.24113424](https://doi.org/10.5281/zenodo.24113424) (all versions, resolves to the latest release); current release v2026.11: [doi:10.5281/zenodo.24113425](https://doi.org/10.5281/zenodo.24113425)
- **Author:** Thomas Mählmann
- **Licenses:** code MIT, data CC BY 4.0

## Factors

| Code | Name | Signal | Preferred |
|---|---|---|---|
| `value` | Value (PD) | Spread-to-maturity / model-implied default probability | high |
| `momentum` | Momentum | Cumulative excess return t-3 to t-1 | high |
| `illiquidity` | Illiquidity | Fewer funds holding the loan | high |
| `quality` | Quality (PD) | Model-implied 12-month default probability | low |
| `low_risk` | Low Risk | Spread duration | low |
| `carry` | Carry | Spread-to-maturity | high |
| `ivol` | IVOL | Idiosyncratic volatility (12-month market model) | low |
| `bab` | BAB | Dimson beta (12-month market model) | low |
| `combi` | Combi | Equal-weighted z-scores of the eight factors | high |
| `market` | Market | All loans in the investable universe | — |

Factor definitions follow Mählmann and Sukonnik (2022, *Financial Analysts Journal*) and Mählmann
and Reck (2024, *Journal of Portfolio Management*), adapted to the information available in N-PORT.
For low-risk factors (IVOL, BAB, Quality) the anomaly appears in risk-adjusted terms (alpha), not
necessarily in the raw long-short spread.

## Pipeline

```
SEC N-PORT data sets ─► nport_loans.py ─► nport_rekey.py ─► nport_loan_returns.py
                     ─► loan_characteristics.py ─► export_database.py ─► release
```

| Step | Script | What it does |
|---|---|---|
| 1 | `nport_loans.py` | Downloads the quarterly SEC data sets, extracts loan holdings, builds a first price panel |
| 2 | `nport_rekey.py` | Merges identifiers of the same loan (LoanX ID, CUSIP, ISIN, FIGI), removes consumer/platform loans |
| 3 | `nport_loan_returns.py` | Margin, spread-to-maturity, spread duration, total and excess returns |
| 4 | `loan_characteristics.py` | Investable universe, repayment assumption, default model, all factor signals |
| 5 | `export_database.py` | Portfolio returns for the full specification grid, summary statistics, release files |

Analysis and validation (optional):

| Script | Purpose |
|---|---|
| `factor_portfolios.py` | Factor tables, Dimson alphas and panel regressions for a single specification |
| `alpha_by_horizon.py` | Alpha by month after portfolio formation |
| `benchmark_validation.py` | Comparison of the N-PORT benchmark with the LSTA index (index levels must be provided by the user) |

## Quick start

Requirements: Python 3.10 or later, about 8 GB RAM, about 20 GB free disk space during step 1.

```bash
pip install -r requirements.txt

# Linux / macOS
./run_pipeline.sh "Your Name your.email@example.org" 2026q2 2026.11

# Windows PowerShell
.\run_pipeline.ps1 -UserAgent "Your Name your.email@example.org" -EndQuarter 2026q2 -Version 2026.11
```

The SEC requires a user agent with name and e-mail address for automated downloads. Step 1 takes
several hours on first run; it can be interrupted and restarted at any time (finished quarters are
skipped). The release is written to `releases/loanfactors_v<version>/`.

## Release contents

| File | Content |
|---|---|
| `factor_returns.csv` | Monthly returns of all portfolios (Q1–Q5, LS, BM) and the market index |
| `factor_summary.csv` | Statistics per factor and specification, incl. CAPM and Dimson alphas |
| `universe_stats.csv` | Universe size, signal coverage, imputed repayments per month |
| `characteristics_distribution.csv` | Cross-sectional distribution of each signal per month |
| `portfolio_counts.csv` | Number of loans per portfolio at formation |
| `factor_definitions.csv` | Codes, signals, preferred side, sources |
| `metadata.json` | Version, sample, settings, code checksums |

Specification grid: weighting (`ew`, `vw`, `vw_cap`) × holding period (1, 3, 6, 12 months) ×
implementation lag (0, 1 month) × return type (`excess`, `total`).

## Methodology in brief

- **Prices:** fair values reported by funds, median across reporting funds; USD loans, long positions.
- **Identification:** LoanX IDs from N-PORT fields and from issuer names/titles; ISIN mapped to CUSIP;
  crosswalk from CUSIP/ISIN/FIGI to LoanX ID.
- **Universe:** identified loans held by at least two funds at least once; price between
  min(20th percentile, 80) and 105; remaining maturity above 120 days.
- **Returns:** total return from price change and coupon; excess return over the 90-day average SOFR
  (+26.161 bp ISDA spread adjustment until June 2023 as proxy for 3M LIBOR).
- **Exits:** loans that leave the sample with a last price in [95, 105], held by at least two funds
  and not in default, are assumed to be repaid at par in the following month.
- **Portfolios:** quintiles; overlapping cohorts for longer holding periods (Jegadeesh and Titman,
  1993) with weights fixed at formation; value weights based on the 12-month average market value
  of fund holdings.
- **Default model:** logit model on public loan characteristics, expanding window, used for the
  Value (PD) and Quality (PD) signals.

See `docs/METHODOLOGY.md` and the methods paper for details and known limitations.

## Known limitations

- Fair values are vendor or model marks, not transaction prices.
- Funds disclose holdings publicly only at fiscal quarter-ends; the monthly cross-section therefore
  varies with the set of reporting funds.
- N-PORT data are published with a delay of about 60 days (use the `lag = 1` series for
  implementable strategies).
- The sample starts in late 2019; signals with estimation windows start later.
- Loan-level data are not published because some identifiers (LoanX IDs, CUSIPs) are proprietary;
  they can be reproduced from the SEC data with this pipeline.

## Citation

Please cite the data release you use and the methods paper:

> Mählmann, T. (2026). *Leveraged Loan Factors* (Version 2026.11) [Data set]. Zenodo.
> https://doi.org/10.5281/zenodo.24113425

To always refer to the latest release, use the concept DOI https://doi.org/10.5281/zenodo.24113424.
For the software, see `CITATION.cff` ("Cite this repository" on GitHub).
