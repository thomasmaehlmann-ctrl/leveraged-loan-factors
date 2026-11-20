# OpenDL Europe (BDC European Direct Lending Index): methodology

Quarterly return index of European direct lending from the XBRL-tagged schedules of investments of US business
development companies (BDCs). Returns, exits, recoveries and weighting follow OpenDL US
([DIRECT_LENDING.md](DIRECT_LENDING.md)); this document describes what is specific to the BDC data.

## 1. Data

- **Source:** SEC Financial Statement and Notes data sets (`sub`, `num`, `dim`). Quarterly files up to 2025 Q3,
  monthly files from October 2025. Newer files store dimensions in `dim.tsv` (hash in `num.tsv`); older files in
  the `segments` column. Both formats are read (`bdc_pilot.read_zip`).
- **Holdings:** facts with the axis `InvestmentIdentifier` (us-gaap:InvestmentIdentifierAxis):
  `InvestmentOwnedAtFairValue` (USD), `InvestmentOwnedAtCost` (USD), `InvestmentOwnedBalancePrincipalAmount` (unit =
  loan currency), `InvestmentInterestRate`. Latest filing per BDC and balance-sheet date.
- **Coverage:** holding-level tags from Q3 2022 (large BDCs), all BDCs from Q1 2023. The index starts with returns
  for Q2 2023.

## 2. Cleaning (`bdc_panel.py`, `bdc_link.py`)

| Step | Rule |
|---|---|
| Subtotals | identifier is the beginning of another identifier of the filing and has no principal; or its fair value equals the sum of the lowest-level positions below it; or it starts with Total / Cash / Net Assets |
| Equity, cash | identifier mentions equity, shares, units, warrants etc. without debt terms; money market funds |
| Instruments excluded | revolvers, delayed-draw tranches, bonds and notes, equipment finance, CLO tranches and structured finance |
| BDCs excluded | real estate, infrastructure, asset-based, venture and SBA lenders (by name) |
| Currency correction | cost (USD, historical rates) / principal ≈ USD value of one unit of the true currency; if the tagged currency is off by more than 15% and another fits within 8%, the currency is replaced |
| Prices | fair value / quarter-end exchange rate (Federal Reserve H.10 via FRED) / principal × 100 |
| Temporary collapses | a price below 60% of the previous and of a later price of the same position is dropped (repeatedly) |

## 3. Positions and linking

- **Key:** identifier without volatile parts (rates, spreads, reference-rate names, percentages, dates,
  maturities), headings (currency groups, affiliation notes such as "Non-Affiliated Issuer"), link remnants and
  trailing tranche numbers (digits or words). Tranches with the same key, BDC and currency are combined.
- **Linking:** a position without exact match in the next quarter is linked to the most similar unmatched position
  of the same BDC and currency if (a) the distinctive words of the keys (words occurring in few keys of the
  BDC-quarter) overlap by at least 75%, or the string similarity is at least 0.85, and (b) the principal changed by
  less than a factor of two (factor five for delayed-draw tranches or identical names).
- **Tracking:** about 86% of positions are found again in the next quarter from 2023 on.

## 4. Returns (`eu_index.py`)

- **Coupon:** tagged rate; else the rate stated in the identifier; else 3-month base rate of the currency (OECD
  interbank rates via FRED) plus the stated spread; else the median of the BDC, currency and quarter (about 19% of
  positions). Implied spreads (coupon minus base rate) are 5–6% p.a.
- **Distress:** BDCs do not tag non-accrual status. Loans described as non-accrual or valued below 70 earn no
  income. Distressed exits are realized at 70.8% of par (recovery estimated from N-PORT for OpenDL US), capped at the
  last valuation.
- **Exits:** as for OpenDL US (repayment at par if the last valuation is at least 95). Borrowers still held by the
  same BDC in the next quarter (matched by distinctive words) are not exits. BDC-quarters in which fewer than half
  of at least five positions are found again are treated as identifier changes (no exits).
- **Principal jumps:** no return for quarters in which the principal more than doubled or halved.
- **Indices:** main index equal-weighted across managers with at least 10 positions; value-weighted index; without
  the largest manager; sub-indices for first lien, EUR and GBP.

## 5. Validation

| Check | Result (v2026.12) |
|---|---|
| Same loans, same manager, N-PORT vs. BDC data | 311 pairs, median difference 0.18 points, 88% within 1 point |
| Same borrower, different managers (BDC data) | 3,009 pairs; 71% within 1 point at 98 and above; 16% within 1 point at 90–95 |
| S&P Lincoln European Senior Debt Index, first-lien sub-index | correlation 0.83, –0.25 pp p.a. |
| S&P Lincoln European Senior Debt Index, value-weighted index | correlation 0.80, –0.84 pp p.a. |
| Robustness | 9.3–10.4% p.a. across variants; repayment threshold 80: up to +1.6 pp p.a. (published as upper bound) |

## 6. Limitations and open items

- European direct lending held by BDCs of US and global managers; European lenders not filing with the SEC are not
  covered.
- Free-text identifiers: normalization and linking are imperfect.
- **Open item:** payment-in-kind interest (`InvestmentInterestRatePaidInKind`) will be added to `bdc_panel.py`
  before the next update; until then the barometer contains no PIK measure.
