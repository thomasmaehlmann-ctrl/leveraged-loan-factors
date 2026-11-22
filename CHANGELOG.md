# Changelog

## v2026.12.3
- OpenDL Europe v2026.12.1 (data release): corrections of version 2026.12
  - `bdc_link.py`: a USD tag is replaced only if cost exceeds principal by more than 15% (version 2026.12 moved USD loans with low cost-to-principal ratios to other currencies)
  - `eu_index.py`: weights in US dollars (principal at the exchange rate of the first quarter-end of each position)
  - `bdc_link.py`: linking compares each BDC with its own previous filing; distinctive words per currency group; inverted index for candidate pairs (all currencies feasible)
- `eu_index.py --region us`: index of USD loans of BDCs, comparison with the CDLI (`--cdli`); incomplete last quarter-ends dropped
- `eu_export.py`: validation text from the metadata, release notes per version
- `website/loanfactors.org/`: static pages of the website

## v2026.12.2
- OpenDL Europe (BDC European Direct Lending Index): BDC holdings from the SEC Financial Statement and Notes data sets (`bdc_panel.py`, `bdc_link.py`), index, diagnostics, robustness, loan-level validation and release export (`eu_*.py`)
- `pipeline/nport_loans.py`: option `--europe` (non-USD loans and USD loans of European borrowers, with country and exchange rate)
- `website/make_dl_web.py`: data and charts for OpenDL Europe and the overview of both indices
- OpenDL US: short name in the release metadata
- Documentation: `docs/OPENDL_EUROPE.md`

## v2026.12.1
- New folder `direct_lending/`: Registered Fund Direct Lending Index (N-CEN advisers, position panel, index, robustness, loan-level validation, release export)
- `website/make_dl_web.py`: data and charts for the direct lending section of loanfactors.org
- Documentation: `docs/DIRECT_LENDING.md`
- Methods paper on SSRN added to README, CITATION.cff and the release README template
- New validation script `validation/momentum_by_price.py` (momentum among loans below and near par)
- `loan_characteristics.py`: pandas FutureWarnings removed (results unchanged)

## v2026.12
- Data: SEC data set 2026 Q3 added; sample extended to July 2026 (data release doi:10.5281/zenodo.24202315)
- `loan_characteristics.py`: options `--pd-file` (external default probability) and `--cer-stm-file` (external spread-to-maturity for the CER)
- `export_database.py`: README note on interpreting the low-risk factors; code checksums independent of the working directory
- New folder `validation/`: index comparison, comparison with IHS Markit dealer quotes, alpha by horizon, descriptive statistics
- New folder `website/`: scripts for the data, charts and release information of loanfactors.org

## v2026.11 (first release)
- Factors: Value (PD), Momentum, Illiquidity, Quality (PD), Low Risk, Carry, IVOL, BAB, Combi, plus market index
- Specifications: weighting ew / vw / vw_cap; holding 1, 3, 6, 12 months; implementation lag 0 / 1 month;
  excess and total returns
- Sample: 2019-10 to 2026-04
- Base rate: 90-day average SOFR (FRED SOFR90DAYAVG), +26.161 bp until 2023-06
