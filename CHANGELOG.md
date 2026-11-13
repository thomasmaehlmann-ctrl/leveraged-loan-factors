# Changelog

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
