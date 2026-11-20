# Leveraged Loan Factors

[![Data DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.24113424.svg)](https://doi.org/10.5281/zenodo.24113424)
[![Software DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.24114954.svg)](https://doi.org/10.5281/zenodo.24114954)

Open-source pipeline and data releases of **factor returns for US leveraged loans**, built
entirely from public **SEC Form N-PORT** filings of US registered investment funds.

Leveraged loans are private, over-the-counter instruments, and loan-level prices are usually only
available from commercial data vendors. US registered funds, however, report every loan they hold,
with notional and fair value, to the SEC. Aggregating these reports across funds yields a monthly
price panel that tracks the Morningstar LSTA US Leveraged Loan Index with a monthly return
correlation of 0.995 (2019-10 to 2026-07). This repository turns these public filings into a
factor database in the spirit of [JKP Factors](https://jkpfactors.com).

- **Data releases:** Zenodo, [doi:10.5281/zenodo.24113424](https://doi.org/10.5281/zenodo.24113424) (all versions, resolves to the latest release); current release v2026.12: [doi:10.5281/zenodo.24202315](https://doi.org/10.5281/zenodo.24202315)
- **Software (this repository):** Zenodo, [doi:10.5281/zenodo.24114954](https://doi.org/10.5281/zenodo.24114954) (all versions, resolves to the latest release)
- **Methods paper:** [Leveraged Loan Factors from Public Data](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=7704758) (SSRN)
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

Analysis (optional), in `pipeline/`:

| Script | Purpose |
|---|---|
| `factor_portfolios.py` | Factor tables, Dimson alphas and panel regressions for a single specification |

Validation and paper tables, in `validation/` (run from the repository root):

| Script | Purpose |
|---|---|
| `benchmark_validation.py` | N-PORT benchmark vs. the Morningstar LSTA US Leveraged Loan Index (index levels must be provided by the user) |
| `markit_to_panel.py`, `make_nport_common.py`, `markit_comparison.py` | Comparison with IHS Markit dealer quotes at the loan, benchmark and factor level (requires licensed Markit data) |
| `alpha_by_horizon.py` | Alpha by month after portfolio formation |
| `describe_panel.py` | Descriptive statistics of the loan panel |

Website, in `website/`:

| Script | Purpose |
|---|---|
| `make_web_data.py` | Data files for the analysis page, "Factors to watch" and release information of loanfactors.org |
| `make_web_charts.py` | Charts of loanfactors.org |

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

See `docs/METHODOLOGY.md` and the [methods paper](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=7704758) for details and known limitations.

## Known limitations

- Fair values are vendor or model marks, not transaction prices.
- Funds disclose holdings publicly only at fiscal quarter-ends; the monthly cross-section therefore
  varies with the set of reporting funds.
- N-PORT data are published with a delay of about 60 days (use the `lag = 1` series for
  implementable strategies).
- The sample starts in late 2019; signals with estimation windows start later.
- Loan-level data are not published because some identifiers (LoanX IDs, CUSIPs) are proprietary;
  they can be reproduced from the SEC data with this pipeline.

## Direct lending: OpenDL US (Registered Fund Direct Lending Index)

The folder `direct_lending/` builds a quarterly return index of US direct lending from the same N-PORT data:
middle market loans held by US registered closed-end funds (interval, tender offer and listed credit funds).
Methodology: [docs/DIRECT_LENDING.md](docs/DIRECT_LENDING.md) and https://loanfactors.org/dl-methodology.html.
Data release: Zenodo, [doi:10.5281/zenodo.24280967](https://doi.org/10.5281/zenodo.24280967) (all versions); v2026.12: [doi:10.5281/zenodo.24280968](https://doi.org/10.5281/zenodo.24280968).

| Script | Purpose |
|---|---|
| `ncen_advisers.py` | Investment adviser and fund type of each fund from the SEC Form N-CEN data sets |
| `dl_feasibility.py` | Feasibility analysis: size, ownership and concentration of candidate direct loans |
| `dl_panel.py` | Panel of direct lending positions (fund x borrower x calendar quarter-end) |
| `dl_index.py` | Position returns, indices, components and credit health barometer; comparison with external benchmarks (optional) |
| `dl_robustness.py` | Sensitivity variants and desmoothing |
| `dl_crossmanager.py` | Loan-level validation: the same loan valued by different managers |
| `dl_export.py` | Versioned data release (CSV files, metadata, README, checksums) |

Run from the repository root after the leveraged loan pipeline (`nport_out/holdings_v2` is required):

```
python direct_lending/ncen_advisers.py --user-agent "Name name@university.edu"
python direct_lending/dl_panel.py
python direct_lending/dl_index.py
python direct_lending/dl_robustness.py
python direct_lending/dl_export.py --version 2026.12 --zip
python website/make_dl_web.py --release releases/dlindex_v2026.12 --site loanfactors.org
```

Comparisons with the Cliffwater Direct Lending Index (`--cdli`, `--cdli-annual`) require index data that users
must obtain themselves; they are not part of this repository or the data releases. "Cliffwater Direct Lending
Index" and "CDLI" are trademarks of Cliffwater LLC; the index is independent of and not endorsed by Cliffwater.

## Direct lending: OpenDL Europe (BDC European Direct Lending Index)

OpenDL Europe measures European direct lending (loans in EUR, GBP and other European currencies) from the
XBRL-tagged schedules of investments of US business development companies (BDCs), published by the SEC in the
Financial Statement and Notes data sets. Data release: Zenodo,
[doi:10.5281/zenodo.24396813](https://doi.org/10.5281/zenodo.24396813) (all versions). Methodology:
[docs/OPENDL_EUROPE.md](docs/OPENDL_EUROPE.md) and https://loanfactors.org/dl-methodology.html#europe.

| Script (in `direct_lending/`) | Purpose |
|---|---|
| `bdc_pilot.py` | Reads the Financial Statement and Notes data sets (old and new format); pilot counts of European holdings |
| `bdc_samples.py` | Sample of position identifiers per BDC (for developing the parser) |
| `bdc_panel.py` | Holdings of all BDCs: subtotals, equity and cash removed; instrument, currency, position key, FX conversion |
| `bdc_link.py` | Re-keying, subtotal check, currency correction, coupon and spread from identifiers, linking of renamed positions |
| `bdc_tracking.py` | Diagnostics: positions found again in the next quarter |
| `eu_index.py` | OpenDL Europe: returns, exits, recoveries, weighting, barometer, comparison with an external benchmark (optional) |
| `eu_diag.py`, `eu_exits.py` | Diagnostics: low prices, extreme returns, exits checked against other managers |
| `eu_robustness.py` | Sensitivity variants |
| `eu_loanlevel.py` | Loan-level validation: different managers; same loans in N-PORT and BDC data |
| `eu_export.py` | Versioned data release |
| `eu_feasibility.py` | Feasibility of European indices from N-PORT (registered funds) |

Run from a working folder that contains the scripts of `direct_lending/` and the data sets in `fsn_data/`
(quarterly files up to 2025 Q3, monthly files afterwards):

```
python bdc_panel.py --user-agent "Name name@university.edu"
python bdc_link.py
python eu_index.py --min-positions 10
python eu_export.py --version 2026.12 --zip
python website/make_dl_web.py --release releases/dlindex_v2026.12 --eu-release releases/opendl_europe_v2026.12 --site loanfactors.org
```

Comparisons with the S&P Lincoln European Senior Debt Index (`--esdi`) require index returns that users must
compile themselves; they are not part of this repository or the data releases.

## Citation

Please cite the methods paper:

> Mählmann, T. (2026). Leveraged Loan Factors from Public Data. Working paper, SSRN.
> https://papers.ssrn.com/sol3/papers.cfm?abstract_id=7704758

and the data release you use:

> Mählmann, T. (2026). *Leveraged Loan Factors* (Version 2026.12) [Data set]. Zenodo.
> https://doi.org/10.5281/zenodo.24202315

To always refer to the latest release, use the concept DOI https://doi.org/10.5281/zenodo.24113424.
If you use or adapt the pipeline, please also cite the software:

> Mählmann, T. (2026). *Leveraged Loan Factors* (Version v2026.12) [Computer software]. Zenodo.
> https://doi.org/10.5281/zenodo.24114954

The "Cite this repository" button on GitHub (from `CITATION.cff`) provides APA and BibTeX formats.


For the direct lending indices:

> Mählmann, T. (2026). Direct Lending Returns from Public Data: An Open Index and What It Reveals about Private
> Credit Valuations. Working paper, SSRN. https://ssrn.com/abstract=7733980

> Mählmann, T. (2026). *OpenDL US: Registered Fund Direct Lending Index* (Version 2026.12) [Data set]. Zenodo.
> https://doi.org/10.5281/zenodo.24280968

> Mählmann, T. (2026). *OpenDL Europe: BDC European Direct Lending Index* (Version 2026.12) [Data set]. Zenodo.
> https://doi.org/10.5281/zenodo.24396814
