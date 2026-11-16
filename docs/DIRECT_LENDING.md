# Registered Fund Direct Lending Index: methodology

Quarterly return index of US direct lending (middle market corporate loans), built from the holdings that US
registered closed-end funds report to the SEC in Form N-PORT. This document describes the construction in
the order of the scripts in `direct_lending/`.

## 1. Data

- **Form N-PORT** (quarterly SEC data sets, from 2019): individual loan holdings with principal, fair value,
  fair value level, coupon, coupon type, maturity, default and PIK flags. The leveraged loan pipeline
  (`pipeline/nport_loans.py`) extracts all loan holdings to `nport_out/holdings_v2`.
- **Form N-CEN** (annual census, `ncen_advisers.py`): investment adviser, fund type (Form N-2 vs. N-1A) and
  interval fund flag of each fund. Funds are matched by series ID and, for closed-end funds without a series ID,
  by the registrant's CIK. Sub-advisers are ignored; if the adviser changes, the latest one is used.

Funds publish the report for the last month of each fiscal quarter. About 95% of the direct lending value is
reported at calendar quarter-ends, which the index uses.

## 2. Universe (`dl_panel.py`)

A holding enters the panel if all of the following hold:

| Criterion | Rule |
|---|---|
| Filing | latest filing per fund and report date (amendments replace originals) |
| Identifier | no valid LoanX ID, CUSIP, ISIN or FIGI (same rules as `pipeline/nport_rekey.py`; placeholder CUSIPs such as 000000000 count as none) |
| Valuation | fair value level 3, plausible price |
| Size | principal of at least USD 250,000 |
| Funding | not flagged as unfunded or revolver; coupon of at least 2% (commitment fees excluded), unless the loan is in default or has a coupon of zero and a mark below 90 (non-accrual) |
| Type | text exclusions for real estate, mortgage, asset-based, consumer, equipment, trade finance, fund finance and NAV loans, revolvers, delayed-draw tranches, term loans B (syndicated), platform loan pools |
| Fund | closed-end fund registered on Form N-2 (open-end funds excluded unless `--all-fund-types`); fund names indicating real estate, municipal, infrastructure, impact or community development strategies excluded |

**Manager:** the adviser from N-CEN, grouped into families by the first word of the adviser name (two words
if the first is generic), e.g. the four Eagle Point advisers form one manager. Corrections can be supplied in
`manager_overrides.csv`.

**Positions:** all tranches of a borrower in a fund are combined (fund x borrower x quarter-end). Borrower
names are normalized: legal forms, facility words, dates, spreads and punctuation removed, truncated to 20
characters (some funds truncate names). Price = market value / principal x 100; coupon is principal-weighted.

## 3. Returns (`dl_index.py`)

For a position held at two consecutive quarter-ends by the same fund:

- **Income** = average coupon of the two quarter-ends / 4 / price at the start; zero if the loan is in default
  or non-accrual at the end. PIK interest is included: it increases principal but not price.
- **Price return** = (P(t) - P(t-1)) / P(t-1).

**Exits** (position gone while the fund still reports):

| Last mark | Treatment |
|---|---|
| at least 95, not in default | repaid at par, half a quarter's coupon |
| default flag, coupon zero or below 80 | realized at the recovery rate, capped at the last mark, no income |
| otherwise | realized at the last mark (sale) |

The **recovery rate** is estimated from the data: the median mark of positions in the first quarter with a
coupon of zero (non-accrual). The default flag alone is not used, because it mostly marks technical defaults
(median mark about 94).

**Cost basis** (N-PORT reports none): running average cost per position; first mark for new positions, par for
positions held in the fund's first reported quarter, add-ons at the average mark of the two quarter-ends.

**Components** (value-weighted indices only, as in BDC accounting): realized = (exit price - cost) for losses;
gains over cost at repayment are shown as accretion (BDCs accrete purchase discounts through income);
unrealized = remaining price return.

Quarterly position returns above 50% in absolute value are treated as data errors and dropped, except for
exits and loans in default or non-accrual.

## 4. Indices

| Series | Construction |
|---|---|
| `ew_managers` (main index) | within each manager value-weighted by market value at t-1; equal-weighted across managers with at least 10 positions in the quarter |
| `vw_all` | value-weighted across all positions |
| `vw_ex_largest` | value-weighted without the largest manager (Cliffwater) |

The index starts with returns for the first quarter of 2022; before, the segment is small and dominated by
other loan types.

## 5. Credit health barometer

Per quarter-end, weighted by estimated cost (or principal where noted): non-accrual share (coupon zero), share
marked below 90, PIK share and amended PIK share (PIK newly flagged while marked below 96 and still paying),
for all managers and without Cliffwater; trailing four-quarter realized and unrealized returns of the
value-weighted index.

## 6. Sensitivity and validation

- **Variants** (`dl_robustness.py`, `dl_index_variants.csv`): recovery 60% and 50%; minimum 5 and 20 positions
  per manager; repayment threshold 90 and 97; distress threshold 70 and 90; interval funds only.
- **Desmoothing:** Geltner (1993) on the price component only; the income return is an accrual.
- **Index level:** comparison with the Cliffwater Direct Lending Index (correlations and differences reported
  in the release metadata; no Cliffwater data in the releases).
- **Loan level** (`dl_crossmanager.py`): marks of the same borrower held by several managers (maturities within
  180 days; pairs differing by more than 20 points are treated as different instruments).

## 7. Limitations

- Fund valuations, not transaction prices; returns are smoothed and dampened relative to traded credit.
- Income excludes fees not reported in N-PORT (e.g. prepayment fees).
- Business development companies do not file N-PORT; the index covers registered funds only.
- Loans are followed by normalized names, not identifiers; tracking from quarter to quarter is about 90%.
- Gross of fees, unlevered.
