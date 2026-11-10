# Methodology

This document describes how the factor database is constructed from SEC Form N-PORT filings.
It complements the README and the methods paper.

## 1. Data source

US registered investment companies (mutual funds, ETFs, closed-end and interval funds) file
Form N-PORT monthly. The SEC publishes the filings as quarterly data sets
(https://www.sec.gov/data-research/sec-markets-data/form-n-port-data-sets), with data from
October 2019 onwards. A quarterly data set contains the filings *submitted* in that quarter.
Historically, only the filing for the last month of each fund's fiscal quarter is public.

Tables used: `FUND_REPORTED_HOLDING` (holdings, notional, fair value, asset category, fair value
level), `IDENTIFIERS` (ISIN and other identifiers), `DEBT_SECURITY` (maturity, coupon type,
annualized rate, default and PIK flags), `SUBMISSION`, `FUND_REPORTED_INFO`, `REGISTRANT`.

## 2. Holdings and prices

- Holdings with asset category `LON` (loan), unit `PA` (principal amount), long positions and USD.
- Price = fair value / notional × 100, plausible between 1 and 150.
- Tranches flagged as delayed draw, unfunded or revolver (text patterns) are excluded.
- Amendments: per fund and report date only the most recently filed version is kept.
- Monthly loan price = median across reporting funds.

## 3. Loan identification

Funds report the same loan with different identifiers. The pipeline
1. extracts LoanX IDs from N-PORT identifier fields and from issuer names and titles,
2. discards placeholder CUSIPs,
3. maps US and Canadian ISINs to CUSIPs,
4. builds a crosswalk from CUSIP / non-US ISIN / FIGI to LoanX IDs from holdings that report both,
5. assigns keys in the order LoanX ID > CUSIP > ISIN > FIGI > name and maturity.

Holdings without any identifier whose name or title contains long loan numbers or platform
patterns (consumer and small-business platform loans) are excluded. The factor universe uses
identified loans only (no name keys).

## 4. Returns

- Coupon c: annualized rate reported in N-PORT (median across funds).
- Total return: TR_t = (P_t − P_{t−1} + c_{t−1}/12) / P_{t−1}, only for consecutive months.
- Excess return: TR_t − b_{t−1}/12, where b is the 90-day average SOFR (FRED `SOFR90DAYAVG`),
  plus 26.161 bp until June 2023 (ISDA spread adjustment, proxy for 3M USD LIBOR).
- Monthly returns above 50% in absolute value are treated as outliers.
- Repayment assumption: a loan that permanently leaves the sample (last observation at least six
  months before the end of the data) with a last price in [95, 105], last held by at least two
  funds and without a default flag is assumed to be repaid at par in the following month.
  Exits of loans held by a single fund are ambiguous (sale or repayment) and receive no assumption.

## 5. Investable universe

At formation date t: price between min(20th percentile of prices in month t, 80) and 105,
remaining maturity above 120 days, plausible margin, loan held by at least two funds in at least
one month. The lower price bound drops below 80 only in stress periods (as in Mählmann and Reck,
2024). Loans falling below the bound during the holding period stay in the portfolio.

## 6. Signals

| Signal | Definition |
|---|---|
| Margin | coupon − base rate of the previous month |
| STM | margin + (100 − P) / T, T = remaining maturity capped at 3 years (min. 0.25) |
| Spread duration | modified duration of the assumed cash flows, discounted at base rate + STM |
| Momentum | sum of monthly excess returns t−3 to t−1 |
| Illiquidity | −(number of reporting funds + 0.99 × percentile rank of held notional) |
| IVOL / BAB | 12-month rolling regression of the loan's excess return on the market return at t and t−1 (min. 8 observations); IVOL = residual standard deviation, BAB = sum of the two betas (Dimson beta); market = equal-weighted universe of the prior month |
| Default probability (PD) | logit model with L2 penalty on price, margin, PIK flag, log number of funds, fair value level 3 and remaining maturity; target = default flag within the next 12 months; re-estimated at each quarter-end with an expanding window using only observations whose 12-month outcome was known; first estimation once 100 defaulted loans are in the window |
| Value (PD) | STM / PD |
| Quality (PD) | PD (low preferred) |
| Carry | STM |
| Low Risk | spread duration (low preferred) |
| Combi | equal-weighted average of the signed, cross-sectionally standardized (±3 capped) signals of the eight factors; at least six available |

## 7. Portfolios

- Each month, loans with an available signal are sorted into quintiles.
- `LS` = preferred quintile minus opposite quintile; `BM` = all sorted loans (same weighting).
- Holding period h > 1: overlapping cohorts formed in months t−h ... t−1 (Jegadeesh and Titman, 1993);
  strategy return = equal-weighted average of cohort returns; weights fixed at formation and
  renormalized if a loan's return is missing.
- Implementation lag l: a cohort formed at t is held from t+1+l to t+h+l.
- Weightings: `ew` equal; `vw` 12-month average market value of fund holdings; `vw_cap` the same,
  capped at the monthly 80th percentile.

## 8. Statistics

`factor_summary.csv` reports annualized means and volatilities, Sharpe ratios, outperformance
against the benchmark, information ratios, CAPM alphas and betas against the benchmark, and Dimson
(1979) alphas with the benchmark at t, t−1 and t−2, which account for delayed price reactions.
t-statistics use Newey-West standard errors with three lags.

## 9. Validation

The equal-weighted market index (total return, universe as above) has a monthly correlation of
0.995 and a tracking error of 0.6% p.a. with the Morningstar LSTA US Leveraged Loan Index
(2019-10 to 2026-04). The lagged index beta is close to zero, i.e. the fund fair values do not lag
the index.

## 10. Versioning

Each release has a version (year.month), a full set of files with checksums, and a DOI on Zenodo.
Because the SEC data sets are revised and extended over time (late filings, amendments), returns
in earlier months can change slightly between releases. Always cite the release you use.
