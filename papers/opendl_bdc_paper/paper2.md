# Private Credit Valuations from Public BDC Filings: An Open European Index and Evidence on Manager Differences

Thomas Mählmann\*

Catholic University of Eichstätt-Ingolstadt

December 2026

\* Catholic University of Eichstätt-Ingolstadt, Department of Finance and Banking. E-mail: thomas.maehlmann@ku.de. Data and code:
https://loanfactors.org.

## Abstract

Business development companies (BDCs) report every loan they hold in machine-readable form, but these data have not
been used to construct open benchmarks. We develop an open procedure that turns the XBRL schedules of investments of
all BDCs into a loan-level panel and validate it in two ways. Applied to their US dollar loans (OpenDL US BDC), it tracks the
Cliffwater Direct Lending Index with a quarterly correlation of 0.97 and practically identical price returns; loans
to the same borrowers held by the same manager in a registered fund and in a BDC are valued alike in both sources. We use the
procedure to construct OpenDL Europe, an open quarterly index of European direct lending held by US BDCs, which covered
about 700 loans and USD 21 billion as of June 2026 and returned 9.9% per year from 2023 to 2026 under conservative
assumptions on exits. The data also show how private
loans are valued. For the holdings we can match, a manager values a borrower alike in its registered funds and its BDCs,
while different managers disagree on troubled loans and mark them down at different times. The weaker markdowns of
registered funds in early 2026 reflect mainly the loans they held and the practice of their largest manager. The index,
the panel construction and the code are publicly available.

*JEL classification:* G11, G12, G23

*Keywords:* direct lending, private credit, business development companies, valuation, Europe, XBRL

## 1. Introduction

Private credit has become one of the largest segments of corporate lending, with assets of about USD 2.7 trillion at
the end of 2025, more than half of them in direct lending (Morgan Stanley Investment Management, 2026). Europe is its
fastest-growing region. European direct lending assets under management reached a record of about USD 380 billion in June
2024, more than 70% above their pre-pandemic average (Pemberton and Saïd Business School, 2025), and European private debt funds raised USD 79 billion in 2025 (PitchBook,
2026). Yet nonbank lenders still account for a much smaller share of corporate financing in Europe than in the US,
which suggests substantial room for further growth (Apollo, 2025).

The returns of private credit rest on valuations that are rarely inspected. Direct loans do not trade; the
funds that hold them report fair values based on their own models and inputs, and the established benchmarks
aggregate these valuations with data and procedures that are not public. For Europe, the main benchmark, the S&P
Lincoln European Senior Debt Index, rests on valuations of loans that are not disclosed.

Business development companies offer an alternative. These closed-end investment companies hold a large part of
US direct lending and a growing book of European loans, and since 2022 and 2023 they must tag their financial
statements, including the schedules of investments, in Inline XBRL (SEC, 2020). Each schedule lists every loan with
its fair value, cost, principal and, for most BDCs, its interest rate. The data are public, but they are not easy to
use: identifiers are free text that changes from quarter to quarter, subtotals are tagged like positions, and the
currency of a loan is visible only in the unit of its principal.

This paper makes three contributions. First, we develop and publish a procedure that turns these filings into a
loan-level panel: subtotals are removed, mislabeled currencies corrected, identifiers normalized and positions linked
across quarters, coupons recovered from tags, identifiers or spreads, and returns computed with the method of OpenDL
US (Mählmann, 2026b). We validate the procedure against an established benchmark built from the same filings: applied
to the US dollar loans of BDCs, it yields OpenDL US BDC, which tracks the Cliffwater Direct Lending Index (CDLI) with a quarterly correlation of
0.97, and its price component, which depends on valuations, linking, exits and recoveries, almost coincides with that
of the CDLI. Income is 0.7 percentage points per year lower, because we measure contractual coupons rather than income
statements. A second validation uses loans that the same manager holds in registered funds, which report in Form
N-PORT, and in BDCs: valuations computed independently from the two sources differ by a median of 0.18 points for
European and 0.01 points for US loans.

Second, we construct OpenDL Europe, an open quarterly index of European direct lending. US BDCs held about 700 loans in
European currencies with a value of USD 21 billion in mid-2026, mostly in euro and sterling, held by 58 BDCs of 34
managers. From the second quarter of 2023 to the second quarter of 2026, the index returned 9.9% per year, with
quarterly returns between 1.8% and 3.6%. Euro loans earned less than sterling loans, reflecting base rates rather than
spreads, and the share of loans valued below 90 rose to 11% at the end of 2025 before easing in 2026. Compared with the
Lincoln index, the value-weighted index has a correlation of 0.84; its level is lower, partly because it measures
income by coupons and contains junior loans. The index covers European direct lending as held by the BDCs of US and
global managers, not lenders that do not file with the SEC.

Third, the data show how private loans are valued. When the same manager holds loans to the same borrower in a
registered fund and in a BDC, the two valuations are practically identical: for the matched holdings, valuations
appear to be specific to the manager rather than to the vehicle.
Different managers agree on performing loans but disagree on troubled ones, in Europe as in the US, and they mark
loans down at different times. In the US, registered funds marked their direct loans down much less than BDCs in the
first quarter of 2026 (Mählmann, 2026b). On loans to the same borrowers, the difference is small and concentrated in the largest
registered fund manager, which values troubled loans 3.6 points above the median BDC and followed BDC markdowns in
only 29% of cases; other registered fund managers value and mark down the shared loans like BDCs. Most of the
difference between the vehicles arises on loans held by only one of them. The immediate effect on reported values is
small (about 0.06% of net asset value), but the timing of markdowns shifts returns between periods and between
investors who subscribe or redeem in between.

Together with OpenDL US (Mählmann, 2026b), the two indices introduced here form a family of open direct lending
indices built from public filings with one method: OpenDL Europe and OpenDL US BDC from the schedules of investments
of BDCs, and OpenDL US from the Form N-PORT holdings of registered closed-end funds. All three measure returns in loan
currency, weight managers equally, report the same components and credit indicators, and are updated quarterly with
open data and code. The common method is what allows the comparisons in this paper: of the same borrowers across vehicles
and data sources, of managers within and across vehicles, and of European and US direct lending (Table 10).

The paper relates to three strands of research. A first strand studies the growth and economics of private credit
and BDCs, for example why firms borrow from nonbanks (Chernenko, Erel and Prilmeier, 2022), the capital of BDCs
relative to banks (Chernenko, Ialenti and Scharfstein, 2025) and the practices of private debt funds (Block, Jang,
Kaplan and Schulze, 2024). A second strand measures the returns of private credit; Erel, Flanagan and Weisbach (2024)
find that the risk-adjusted returns of private debt funds are close to zero after fees. These studies rely on fund
cash flows or proprietary data; we provide open, loan-level return indices for Europe and the US. A third strand
studies the valuation of private loans. Dogaru (2026) shows that BDCs relying more on payment-in-kind income report
higher values for the same loans, and Anadu and Wasner (2026) that valuations of the same loan are more positively
related to leverage at non-traded than at traded BDCs. Industry analyses find little variance in BDC valuations of
identical loans on average, but more for underperforming loans (KBRA, 2024). We add the comparison across vehicles
and data sources, the timing of markdowns, and the decomposition of differences between vehicles into effects of
the loans held and of the managers.

The paper proceeds as follows. Section 2 describes the data, Section 3 the construction of positions and returns, and
Section 4 the validation. Section 5 presents OpenDL Europe, Section 6 the evidence on vehicles and managers. Section 7
describes the database and concludes.


## 2. Data

### 2.1 Schedules of investments of business development companies

Business development companies (BDCs) are closed-end investment companies that lend to US and, increasingly,
non-US middle market firms. Unlike registered funds, they do not file Form N-PORT. They report their holdings in
the schedules of investments of their quarterly and annual reports, which list every position with its fair value,
cost, principal and interest rate. Since the SEC's reform of the offering rules for closed-end funds, these schedules
must be tagged in Inline XBRL (SEC, 2020): from August 2022 for BDCs eligible for the short-form registration
statement, typically the largest, and from February 2023 for all others. Each position is a context with the axis `InvestmentIdentifierAxis`, whose member is the
free-text description of the position; the facts attached to it include `InvestmentOwnedAtFairValue` (in US
dollars), `InvestmentOwnedAtCost` (in US dollars at historical exchange rates),
`InvestmentOwnedBalancePrincipalAmount` (in the currency of the loan, given by the unit of the fact) and, for many
BDCs, `InvestmentInterestRate`.

The SEC publishes all XBRL facts of all filings in its Financial Statement and Notes data sets, quarterly up to
the third quarter of 2025 and monthly since. We read the data sets from the fourth quarter of 2022 onward. Tagged
holdings first appear for the September 2022 balance sheets of the largest BDCs (21 BDCs) and, in line with the
compliance dates, cover essentially all BDCs from March 2023 (104 BDCs, 208 by mid-2026; of these, 58 direct lending BDCs held loans in European currencies in June 2026). Earlier data sets contain no holding-level facts. Our sample
therefore starts with the balance sheets of September 2022, and our indices with returns for the second quarter of
2023, when coverage is complete.

Three features of the data shape the construction. First, the identifier is free text: it may contain the borrower,
the industry, the instrument, the reference rate, the spread, the coupon and the maturity in any order, and it
changes from quarter to quarter when rates reset or headings are rearranged. Second, BDCs also tag subtotals
(by industry, country or asset class) with the same axis, some of them with a principal amount. Third, the
currency of a loan is given only by the unit of its principal amount, while fair value and cost are reported in US
dollars.

### 2.2 The European book of BDCs

US BDCs hold a substantial and growing book of European loans. Loans in European currencies held by direct
lending BDCs grew from 184 positions and USD 5.5 billion at the end of March 2023 to 697 positions and USD 20.9
billion in June 2026, held by 58 BDCs of 34 managers (Table 1). About 53% of the value is in euro and 41% in
sterling; the rest is in Swiss francs and Nordic currencies. The largest holders are the non-traded BDCs of
Blackstone, Apollo and HPS; the share of the largest manager fell from 49% to 34%. Median prices are between 97 and
99, and median coupons rose from 9.7% to 10.6% in 2023 and 2024 before falling to 8.2% with base rates.

**Table 1. Loans in European currencies held by direct lending BDCs**

| Quarter-end | Positions | BDCs | Managers | Market value (USD bn) | Median price | Median coupon (%) | Share EUR | Share GBP | Share of largest manager |
|---|---|---|---|---|---|---|---|---|---|
| Mar 2023 | 184 | 23 | 18 | 5.5 | 97.3 | 9.7 | 48% | 44% | 49% |
| Dec 2023 | 288 | 39 | 22 | 8.2 | 99.0 | 10.6 | 48% | 47% | 38% |
| Dec 2024 | 500 | 51 | 28 | 14.4 | 99.0 | 9.5 | 53% | 44% | 38% |
| Dec 2025 | 660 | 59 | 36 | 20.3 | 99.2 | 8.0 | 51% | 43% | 35% |
| Jun 2026 | 697 | 58 | 34 | 20.9 | 98.8 | 8.2 | 53% | 41% | 34% |

*Notes:* Positions are BDC × borrower × instrument × currency after cleaning (Section 3). Market value in US dollars.
The largest manager is Blackstone. Source: opendl_europe_universe.csv (OpenDL Europe v2026.12.1).

The European book is the book of US and global managers. This is a substantial part of the market: private credit
funds managed from the euro area held only about EUR 100 billion in 2025 (Cera et al., 2026), a fraction of European private
credit, much of which is managed from the United Kingdom and the United States. European direct lenders that do not
file with the SEC are not covered, and the index measures European direct lending as held by these managers, not the European market
as a whole. Within this scope, the data are rich: they contain several hundred borrowers per quarter, many of them
held by more than one manager, and a part of them is also held by registered funds that report in Form N-PORT,
which allows the validation in Section 4.2.

### 2.3 Registered funds and the US benchmark

For the US, we use two further data sets. The positions of registered closed-end funds in direct loans are those
of OpenDL US (Mählmann, 2026b, 2026c): about 2,000 loans per quarter reported in Form N-PORT. The quarterly returns
of the Cliffwater Direct Lending Index (CDLI), which is constructed from the filings of BDCs, are compiled from
Cliffwater's public reports and presentations (Cliffwater, 2023, 2024, 2026a, 2026b), as in Mählmann (2026b). For Europe, the returns of the S&P Lincoln
European Senior Debt Index (ESDI) are taken from Lincoln International's public quarterly reports; they are
available for eleven quarters of our sample.

## 3. From filings to positions

The construction follows OpenDL US wherever possible. This section describes what is specific to the BDC data.

### 3.1 Cleaning

We keep the latest filing of each BDC for each balance-sheet date and remove four kinds of entries. Subtotals are
identified in two ways: an identifier without principal that is the beginning of other identifiers of the same
filing, and an identifier with principal whose fair value equals the sum of the lowest-level positions below it
(1,451 such subtotals). Cash, money market funds and equity are identified by keywords. Revolvers, delayed-draw
tranches, bonds, equipment finance, CLO tranches and structured finance are excluded, because their valuations or
cash flows differ from those of term loans; for revolvers and delayed-draw tranches, some BDCs report the commitment
as principal and only the drawn amount as fair value. Finally, BDCs focused on real estate, infrastructure,
asset-based, venture or SBA lending are excluded.

### 3.2 Currencies and prices

Prices are computed in the currency of the loan: fair value is converted with the quarter-end exchange rate of the
Federal Reserve (H.10) and divided by principal. A number of positions carry a wrong currency unit, for example US
dollar loans tagged as sterling or Swedish krona loans tagged as sterling. We correct them using cost: because cost
is reported in US dollars at historical rates and principal in the loan currency, the ratio of cost to principal is
close to the dollar value of one unit of the true currency. If the tagged currency is inconsistent with this ratio
by more than 15% and another currency fits within 8%, the currency is replaced. A US dollar tag is replaced only if
cost exceeds principal by more than 15%, because low ratios are common for dollar loans bought at a discount or
partially drawn. 1,493 holdings are corrected, mostly sterling, euro and Swiss franc loans tagged as US dollars and
the reverse.

A second correction removes temporary collapses: a price below 60% of both the previous and a later price of the
same position is treated as a reporting error, typically a tranche reported without fair value in one quarter
(24 observations in the European sample, 751 in the US sample). The rule uses later valuations and is applied
retrospectively when the index is constructed; it is not a real-time signal. Section 4.4 reports the index without it.

### 3.3 Positions and linking

We combine all tranches of a borrower and instrument held by a BDC into one position. The key of a position is its
identifier without the parts that change over time: rates, spreads, names of reference rates, percentages, dates,
maturities, headings such as currency groups and affiliation notes, and trailing tranche numbers. Positions whose
key changes from one quarter to the next are linked by the distinctive words of the key (words occurring in few
identifiers of the BDC in that quarter, typically the borrower name) or, failing that, by string similarity, if the
principal changed by less than a factor of two. Each BDC is compared with its own previous filing.

With these rules, about 85% of European and 90% of US dollar positions are found again in the following quarter
from 2023 on (European positions 78% to 91% per quarter, US dollar positions 89% to 94%). The remaining positions are
mostly exits. Two further rules protect the index against false exits: a borrower that the same BDC still holds in
the next quarter, under another identifier, tranche or currency, is not counted as an exit, and in the few
BDC-quarters in which fewer than half of at least five positions are found again, missing positions are treated as
in a fund that does not report.

### 3.4 Coupons, exits and returns

The coupon is the tagged interest rate where available (71% of European and 80% of US dollar positions); else the
rate stated in the identifier; else the three-month base rate of the currency plus the spread stated in the
identifier (8% and 5%); else the median coupon of the BDC, currency and quarter (20% and 13%). Coupons minus base
rates give implied spreads of 5.1% to 6.1% for euro loans, 5.4% to 6.0% for sterling loans and 4.9% to 5.8% for dollar
loans over 2022 to 2026, peaking in 2023 and narrowing since, in line with market evidence on direct lending spreads.

BDCs do not tag non-accrual status. Loans described as non-accrual in the identifier or valued below 70 earn no
income, and distressed exits are realized at a recovery of 70.8% of par, the estimate from the N-PORT data of
OpenDL US. Exits with a last valuation of at least 95 are repayments at par. Quarters in which the principal of a
position more than doubled or halved do not enter the return calculation, because price changes then mostly reflect
draws or partial repayments.

Returns are in the currency of each loan. Weights are in US dollars: principal is converted at the exchange rate of
the first quarter-end of each position, so that exchange rate movements do not appear as draws or repayments. As in
OpenDL US, the main index weights managers equally (managers with at least ten loans in the quarter) and positions by
value within managers; we also report the value-weighted index, the value-weighted index without the largest
manager and, for Europe, sub-indices for first-lien, euro and sterling loans.

Quarterly total returns are the sum of the income and price components. Annualized total returns compound the
quarterly returns; annualized income and price components are arithmetic averages of the quarterly components times
four, as in Mählmann (2026b). The annualized components therefore do not add up to the annualized total return; the
difference is the effect of compounding, about 0.3 to 0.4 percentage points per year at the return levels in our
sample.

## 4. Validation

### 4.1 Replicating the CDLI

The CDLI is built from the same filings as our data, but with Cliffwater's own processing. Applying our method to the
US dollar loans of BDCs, which we publish as OpenDL US BDC, therefore tests the method against an established
benchmark. Over the thirteen quarters
from the second quarter of 2023 to the second quarter of 2026, the value-weighted index has a quarterly correlation
of 0.97 with the CDLI (Table 2). The price component, which depends on valuations, linking, exits and recoveries,
almost coincides: −1.38% per year against −1.49% for the CDLI, with a correlation of 0.98. Income is lower by 0.7
percentage points per year (9.73% against 10.43%). The CDLI measures income from the income statements of BDCs,
including fees and the accretion of original issue discounts; our index uses contractual coupons. The resulting gap
in total returns is 0.9 percentage points per year (9.24% against 10.13%). In the last three quarters of the sample,
both series are nearly identical, including the low return of the first quarter of 2026 (1.16% against 1.12%).

Because both indices are built from the same filings, the comparison validates the processing of the data and the
return method, not the valuations themselves: it shows that our procedure reproduces the aggregate return pattern of
an established benchmark constructed from the same underlying information. With thirteen quarters, the comparison is
also short.

**Table 2. OpenDL US BDC compared with the Cliffwater Direct Lending Index (CDLI), Q2 2023 to Q2 2026**

| Quarter | OpenDL US BDC, value-weighted | CDLI |
|---|---|---|
| Q2 2023 | 2.65 | 2.81 |
| Q3 2023 | 2.78 | 3.17 |
| Q4 2023 | 2.50 | 2.95 |
| Q1 2024 | 2.69 | 3.02 |
| Q2 2024 | 2.33 | 2.63 |
| Q3 2024 | 2.19 | 2.65 |
| Q4 2024 | 2.22 | 2.57 |
| Q1 2025 | 2.03 | 2.13 |
| Q2 2025 | 2.31 | 2.34 |
| Q3 2025 | 2.20 | 2.41 |
| Q4 2025 | 2.12 | 2.08 |
| Q1 2026 | 1.16 | 1.12 |
| Q2 2026 | 1.86 | 1.89 |
| Total, % p.a. | 9.24 | 10.13 |
| Income, % p.a. | 9.73 | 10.43 |
| Price, % p.a. | −1.38 | −1.49 |
| Correlation total / income / price | 0.97 / 0.91 / 0.98 | |

*Notes:* Returns in % per quarter. The equal-weighted main index has a correlation of 0.93 with the CDLI.

### 4.2 The same borrowers in two data sources

Several managers hold loans to the same borrowers in registered funds, which report in Form N-PORT, and in BDCs. For these
holdings, prices are computed independently from the two sources: in N-PORT with the exchange rates reported by the funds, in
the BDC data with our exchange rates, currency corrections, keys and links. If the processing of the BDC data is
correct, the same manager should report the same valuation in both vehicles. Holdings are matched by borrower,
currency and quarter-end; different tranches of the same borrower cannot always be distinguished, which, if anything,
works against agreement.

This is the case (Table 3). For European loans, 312 pairs of the same manager (52 borrowers; Apollo, Blackstone,
Carlyle and Oaktree) differ by a median of 0.18 points, and 88% lie within one point. The remaining differences are
consistent with small differences in exchange rates and valuation dates. For US dollar loans, 7,773 pairs of the same
manager (639 borrowers) differ by a median of 0.01 points, and 91% lie within one point. A stricter matching that keeps
only BDC positions with a single tranche and borrowers matched to a single position per BDC reduces the risk of
comparing different tranches; with it, 92% of 185 European pairs and 95% of 4,859 US pairs lie within one point, and
all European pairs within two points.

**Table 3. Valuations of the same borrowers by the same manager in registered funds (N-PORT) and BDCs (XBRL)**

| | Europe | US |
|---|---|---|
| Pairs (borrowers) | 312 (52) | 7,773 (639) |
| Mean absolute difference | 0.55 | 0.46 |
| Median absolute difference | 0.18 | 0.01 |
| Within 1 point | 88% | 91% |
| Within 2 points | 97% | 96% |

*Notes:* Pairs of a registered fund and a BDC of the same manager holding the same borrower at the same quarter-end. Europe: loans in European currencies, Q1 2023 to Q2 2026; US: US dollar loans, Q3 2022 to Q2 2026. Differences in points of par.

### 4.3 OpenDL Europe and the Lincoln index

Over the eleven quarters for which ESDI returns are available, the value-weighted OpenDL Europe has a correlation
of 0.84 with the ESDI and the main index 0.71. The levels differ: the value-weighted index is 1.7 percentage points
per year below the ESDI over these quarters, the first-lien sub-index 0.8 points (correlation 0.67). Three
differences between the indices contribute. First, income: the replication of the CDLI suggests that measuring
income by contractual coupons understates income by about 0.7 percentage points per year relative to benchmarks that
include fees and discount accretion, which accounts for most of the gap of the first-lien sub-index. Second,
seniority: the ESDI contains only senior loans, while OpenDL Europe also contains second-lien, unsecured and
unspecified loans. Third, the portfolios and valuers differ: the ESDI reflects Lincoln's valuations of the loans of
its clients, OpenDL Europe the valuations of US managers for their own European loans.

### 4.4 Robustness

The construction of OpenDL Europe requires assumptions that cannot be verified directly from the filings: when an exit
is a repayment, at what value a distressed loan leaves the portfolio, when a loan stops paying interest, and which
loans and managers the index includes. Table 4 reports the main index and the value-weighted index when each of these
assumptions is changed in turn.

**Exits.** The treatment of exits matters most. In the base specification, a loan that leaves a BDC's portfolio is
treated as repaid at par if its last valuation was 95 or higher, and as sold at its last valuation (or at the recovery
rate, if it was in distress) otherwise. Lowering the threshold to 90 raises the value-weighted index by 0.32 percentage
points per year and the main index by 0.37 points; lowering it to 80 raises them by 1.06 and 1.56 points. The sensitivity is larger than for OpenDL US because exits with last
valuations between 80 and 95 are more frequent: 112 of 495 European exits (23%), against fewer than one in ten in the
registered fund data. Two explanations are possible. These exits may be sales or restructurings of loans that were
worth less than par, in which case the base specification is right. Or the low valuations may be specific to the
exiting BDC, which valued the loan lower than the market did before it was refinanced or repaid at or near par, in
which case the lower threshold is right.

The valuations of other managers allow us to distinguish the two explanations. For each exit with a last valuation
between 80 and 95, we look for the same borrower in BDCs of other managers at the same quarter-end; BDCs of the same
manager are excluded, because they are valued by the same team. If the exiting BDC's low valuation reflected a
genuine impairment, the other managers should value the loan similarly; if it was specific to that BDC, they should
value it near par. We compare the result with two benchmarks: exits valued at 95 or above, and loans valued between
80 and 95 that remain in the portfolio. Of the 112 exits with a low last valuation, nine have a counterpart, a small and selective sample. In all
nine, the other managers valued the borrower at 97 or above and at least three points higher than the exiting BDC
(median 99.8 against 89.0); they concern loans to Ardonagh (held by two BDCs), Artemis Bidco, Bamboo US Bidco,
Excelitas Technologies, Nelipak, Stonegate Pub Company (second lien) and Tango Bidco (in two quarters). For the 75 continuing loans valued between 80 and 95 with a counterpart, this holds in 49%
of cases, and other managers' valuations are within three points in 37%. For exits valued at 95 or above, other
managers' valuations are within three points in 89% of the 64 cases with a counterpart.

The cross-check therefore points to the second explanation for the exits that can be checked: their low valuations
were specific to one manager, and the loans most likely left the portfolio at or near par. The evidence is limited,
however. Only nine of the 112 exits have a counterpart, and the remaining exits, concentrated in a few BDCs, cannot be
checked. We therefore keep the threshold of 95 as a conservative base specification and publish the variant with a
threshold of 80 as an upper bound. The return of European direct lending held by BDCs lies between the two, and the
checked exits suggest that it lies closer to the upper bound.

The comparison with the Lincoln index shows why the threshold should not be chosen on the basis of an external
benchmark. With a threshold of 80, the value-weighted index comes within 0.7 percentage points per year of the ESDI,
against 1.7 points in the base specification. Choosing the threshold for this reason would calibrate the index to the
benchmark against which it is validated.

**Recoveries and distress.** Lower recovery rates for distressed exits, 60% and 50% of par instead of 70.8%, reduce the
value-weighted index by 0.06 and 0.18 percentage points per year and the main index by 0.16 and 0.41 points; the main
index reacts more because smaller managers with more distressed exits carry equal weight. Treating loans as
non-accrual below 60 or below 80 instead of below 70, or using a distress threshold of 70 instead of 80, changes either
index by at most 0.18 points. These assumptions matter little because distressed exits are rare in a portfolio that is
mostly repaid at par.

**Data cleaning.** Without the filter for temporary collapses of prices (Section 3.2), the indices are 0.12 to 0.13
points lower; the filter thus removes a small number of reporting errors without changing the picture. Restricting the
index to positions whose coupon is observed rather than imputed raises the main index by 0.13 points and the
value-weighted index by 0.60 points. The positions with imputed coupons belong to BDCs that do not tag interest rates;
their exits are more often valued below par, which suggests that their identifiers are also less stable, and the
restricted index has fewer managers (seven in the median quarter).

**Universe.** The first-lien sub-index returns 9.84% per year on a value-weighted basis, 0.75 points more than the index
of all loans, and 11.12% with equal manager weights, based on six managers in the median quarter; junior and
unspecified loans reduced returns over the sample. Euro loans return 7.77% and sterling loans 10.44% per year; Section
5.2 shows that the difference reflects mostly base rates. Excluding the largest manager changes the value-weighted index
by 0.03 points if it is excluded from the weights (Table 5) and by −0.04 points if it is removed from the universe; the
index is not driven by Blackstone. Defining European loans by the domicile of the borrower instead of the
loan currency, which adds US dollar loans to European borrowers and removes euro and sterling tranches of US
borrowers, gives 8.76% per year.

**Managers in the main index.** The main index weights managers equally if they hold at least ten loans in a quarter.
With a threshold of five loans, it returns 9.79% per year with a volatility of 1.7%; with a threshold of three, 8.83%
with a volatility of 2.0%, because managers with very few loans add noise without adding information. With ten loans,
the main index returns 9.88% with a volatility of 1.1% and nine managers in the median quarter.

Overall, the main index lies between 9.5% and 11.4% per year and the value-weighted index between 8.9% and 10.2% across
the variants that change the method. Apart from the minimum number of loans per manager, only two assumptions move
either index by more than half a percentage point: the treatment of exits, for which we report both bounds, and the
restriction to observed coupons, which also changes the set of BDCs.

**Table 4. Robustness of OpenDL Europe under alternative assumptions, Q2 2023 to Q2 2026**

| Variant | Main index, % p.a. | Difference, pp | Value-weighted, % p.a. | Difference, pp |
|---|---|---|---|---|
| Base specification | 9.88 | | 9.09 | |
| Repayment threshold 90 | 10.25 | +0.37 | 9.41 | +0.32 |
| Repayment threshold 80 | 11.44 | +1.56 | 10.15 | +1.06 |
| Recovery 60% | 9.72 | −0.16 | 9.03 | −0.06 |
| Recovery 50% | 9.47 | −0.41 | 8.91 | −0.18 |
| Non-accrual below 60 | 9.93 | +0.05 | 9.10 | +0.01 |
| Non-accrual below 80 | 9.70 | −0.18 | 8.96 | −0.13 |
| Distress threshold 70 | 9.97 | +0.09 | 9.10 | +0.01 |
| No filter for temporary collapses | 9.75 | −0.13 | 8.97 | −0.12 |
| Observed coupons only | 10.01 | +0.13 | 9.69 | +0.60 |
| Minimum 5 loans per manager | 9.79 | −0.09 | – | – |
| Minimum 3 loans per manager | 8.83 | −1.05 | – | – |
| First lien only | 11.12 | +1.24 | 9.84 | +0.75 |
| Euro loans only | 7.76 | −2.12 | 7.77 | −1.32 |
| Sterling loans only | 10.16 | +0.28 | 10.44 | +1.35 |
| Largest manager excluded from the universe | 9.73 | −0.15 | 9.05 | −0.04 |
| European borrowers, any currency | 8.88 | −1.00 | 8.76 | −0.33 |

*Notes:* Each variant changes one element of the base specification (Section 3); the main index weights managers with at
least ten loans equally. Returns in loan currency. Excluding the largest manager from the universe removes its loans
before the construction of cost bases and exits; the published value-weighted index without the largest manager
(Table 5, 9.12%) excludes it only from the weights. The value-weighted index does not depend on the minimum number of
loans per manager.

## 5. European direct lending

### 5.1 Returns

From the second quarter of 2023 to the second quarter of 2026, OpenDL Europe returned 9.88% per year (Table 5).
Income averaged 8.51% and the price component 1.03% per year (arithmetic averages; Section 3.4); quarterly returns
ranged from 1.75% to 3.55%, and the annualized volatility was 1.1%. The value-weighted index returned 9.09% per year, with income of 8.21%. In calendar
years, the main index returned 9.98% in 2024 and 8.74% in 2025, the value-weighted index 9.73% and 7.89%.

The low volatility should not be read as a measure of risk. The returns rest on quarterly fair values, not on
transaction prices, and valuations of illiquid loans are smoothed; for OpenDL US, Mählmann (2026b) shows that
valuations of direct loans move with traded loans but with less than half of their amplitude. The sample covers
thirteen quarters without a full default cycle. The return of 9.88% per year also rests on the conservative treatment
of exits; with the upper-bound treatment, it would be higher (Section 4.4).

**Table 5. OpenDL Europe: returns, Q2 2023 to Q2 2026**

| | Main index | Value-weighted | Value-weighted ex largest | Largest manager |
|---|---|---|---|---|
| Total return, % p.a. | 9.88 | 9.09 | 9.12 | 9.07 |
| Income, % p.a. | 8.51 | 8.21 | 8.11 | 8.38 |
| Volatility, % p.a. | 1.13 | 0.96 | 1.26 | 0.92 |
| Worst quarter, % | 1.75 | 1.55 | 1.29 | 1.41 |
| 2024, % | 9.98 | 9.73 | 9.80 | 9.73 |
| 2025, % | 8.74 | 7.89 | 7.87 | 7.95 |

*Notes:* Returns in loan currency, gross of fees and unlevered. Main index: equal-weighted across managers with at
least ten loans. The largest manager is Blackstone.

Constructed with the same method, the US dollar loans of BDCs returned 9.24% per year over the same quarters on a
value-weighted basis (Section 4.1). European loans thus earned a similar total return, but with a different mix:
income was about 1.5 percentage points lower, reflecting lower euro base rates, and the price component was positive
rather than negative. Part of the positive price component reflects the recovery of valuations from early 2023,
when median prices of European loans stood at 97.3, to 99 in 2024.

Realized losses of European loans were 1.45% per year on a cost basis, offset by unrealized gains of similar size.
This pattern is typical for loans that are written down before they leave the portfolio: the markdown appears first
as an unrealized loss and later, when the loan is sold or restructured, as a realized loss with an offsetting
reversal of the unrealized loss. It is stronger in Europe than in the US (0.62% per year on a cost basis), and it is
sensitive to the treatment of exits valued between 80 and 95 (Section 4.4).

### 5.2 Euro and sterling

Euro loans returned 7.8% per year and sterling loans 10.4% (value-weighted). Implied spreads over the respective
base rates were similar, between 5.1% and 6.1% for euro and between 5.4% and 6.0% for sterling loans (Section 3.4).
Most of the difference therefore reflects base rates: sterling three-month rates exceeded euro rates by roughly 1.5 to
2 percentage points over the sample. For investors, the comparison is a reminder that unhedged European direct
lending returns combine credit and rate exposures that differ by currency; the index reports returns in the
currency of each loan, excluding exchange-rate movements. They should be interpreted as currency-neutral loan returns
rather than as realized or hedged returns in a common investor currency, which would add the interest rate differential
and the costs of hedging. The euro and sterling sub-indices allow the two markets to be followed separately.

### 5.3 Credit health

The share of European loans valued below 90 (weighted by estimated cost) was mostly between 4% and 7% from mid-2023
to mid-2025, with a spike to 9.4% in September 2023, rose to 8.8% in September 2025 and 10.9% in December 2025, and
eased to 7.8% in June 2026 (Figure 1). The share valued below 80 was highest at the start of the sample (5.1% in March
2023) and again at the end of 2025 (4.7%). For the US dollar loans of BDCs, the share below 90 rose later
and further, to 11.0% in June 2026, with the share below 80 increasing to 5.3%.

{{FIGURE1}}

Lincoln International's European Private Market Index, which covers more than 450 private companies valued by
Lincoln, points in the same direction: its covenant default rate peaked at 3.7% to 3.9% in 2025, the use of
payment-in-kind interest rose to 16.7% of companies in the second quarter of 2026, and the share of companies that
switched from cash to payment-in-kind interest reached 8.1% (Lincoln International, 2026). The two sources differ in
coverage and definitions, so we do not compare levels; both show that stress in European middle market lending built
up in 2025 and had not dissipated by mid-2026.

### 5.4 Managers disagree on troubled loans

European loans are often held by several managers. For 2,910 pairs of BDCs of different managers holding the same
borrower in the same currency at the same quarter-end (31 managers), valuations agree closely for performing loans
and diverge for troubled ones (Table 6). For loans valued at 98 or above on average, the mean absolute difference is
0.85 points and 72% of pairs lie within one point. For loans valued between 90 and 95, the mean absolute difference
is 8.1 points and only 10% lie within one point. Quarterly changes of the two valuations have a correlation of 0.22,
and when one manager marks a loan down by two points or more, the other marks it down by at least one point in the
same quarter in only 29% of cases.

These patterns match those for US registered funds (Mählmann, 2026b), where the corresponding figures are 0.70 points
and 76% for performing loans, 4.8 points and 25% for loans valued below 95, a correlation of 0.29 and 25%. Comparing each
manager's valuation with the median valuation of the other managers holding the same borrower, no manager deviates
clearly from the others. Blackstone, the largest holder, values shared European loans 0.65 points higher on average
(t = 2.0, with standard errors clustered by borrower), and one other manager 1.1 points lower (t = −2.0); for both, the median deviation is close to zero, so that
the averages are driven by a few loans. Unlike in the US (Section 6.2), there is no manager whose valuations of
troubled loans differ persistently from those of the others.

**Table 6. Valuations of the same borrower by different managers: European loans held by BDCs**

| Average valuation | Pairs | Mean absolute difference | Median absolute difference | Within 1 point | Within 2 points |
|---|---|---|---|---|---|
| 98 and above | 2,296 | 0.85 | 0.50 | 72% | 92% |
| 95 to below 98 | 443 | 1.97 | 0.77 | 56% | 75% |
| 90 to below 95 | 152 | 8.10 | 8.39 | 10% | 16% |
| Below 90 | 19 | 11.93 | 18.38 | 11% | 16% |
| All | 2,910 | 1.47 | 0.58 | 66% | 85% |

*Notes:* Pairs of BDCs of different managers holding the same borrower in the same currency at the same quarter-end, Q1 2023 to Q2 2026; pairs differing by more than 20 points excluded. Points of par.

## 6. Vehicles and managers

The US data allow a question that our earlier study of registered funds could only raise (Mählmann, 2026b): in the first quarter of 2026,
registered funds marked their direct loans down much less than BDCs. Is this a difference between vehicles, between
managers or between loans? Many US loans are held both by registered funds, which report in Form N-PORT, and by BDCs.
Matching the two data sets by borrower and quarter-end yields 100,693 pairs for 1,825 borrowers from September 2022
to June 2026.

### 6.1 The same manager values the same borrower alike in both vehicles

When the same manager holds loans to the same borrower in a registered fund and in a BDC, the two valuations are practically identical
(Table 7): for 7,773 pairs and 639 borrowers, the median absolute difference is 0.01 points, 91% of pairs lie within
one point and 96% within two. The agreement holds across price buckets; only for loans valued between 90 and 95 is
the registered fund's valuation slightly higher on average (1.4 points), with a median difference close to zero. With
the stricter matching of Section 4.2, the agreement is even closer (95% of 4,859 pairs within one point; 0.9 points
on average for loans valued between 90 and 95).
For the matched holdings, valuations thus appear to be specific to the manager and its valuation process rather than
to the vehicle. This does not imply that the vehicle is irrelevant for valuation in general: governance, valuation
committees and external valuation providers may differ between vehicles, and the managers that hold loans to the same
borrowers in both vehicles are a selected group.

### 6.2 Different managers disagree on troubled loans

For each loan of a registered fund, we compare its valuation with the median valuation of the same borrower by BDCs
of other managers (10,762 position-quarters; a median of four BDCs per loan). Using the median rather than all pairs
prevents borrowers held by many BDCs from dominating the comparison. For performing loans valued at 98 or above on
average, the registered fund's valuation is 0.19 points below the BDC median (median difference −0.05). For troubled
loans, valuations diverge: for loans valued between 90 and 95, the registered fund's valuation exceeds the BDC median
by 2.0 points on average (median 1.1), for loans valued between 80 and 90 by 1.3 points (Table 7).

**Table 7. Valuations of the same borrowers by registered funds and BDCs, Q3 2022 to Q2 2026**
| Average valuation | Same manager: pairs | Same manager: median absolute difference | Same manager: within 1 point | Different managers: loans | Different managers: mean difference (fund − BDC median) | Different managers: median difference |
|---|---|---|---|---|---|---|
| Below 80 | 87 | 0.02 | 76% | 113 | +0.41 | 0.00 |
| 80 to below 90 | 173 | 0.01 | 83% | 149 | +1.27 | +0.71 |
| 90 to below 95 | 439 | 0.02 | 74% | 406 | +2.02 | +1.14 |
| 95 to below 98 | 1,228 | 0.01 | 85% | 1,548 | +0.07 | −0.01 |
| 98 and above | 5,846 | 0.01 | 94% | 8,546 | −0.19 | −0.05 |
| All | 7,773 | 0.01 | 91% | 10,762 | −0.04 | −0.03 |

*Notes:* Same manager: pairs of a registered fund and a BDC of the same manager holding the same borrower at the same quarter-end. Different managers: each loan of a registered fund compared with the median valuation of the same borrower by BDCs of other managers (position-quarters). Points of par.

The difference is concentrated in one manager. Cliffwater, which holds about three quarters of the direct loans of
registered funds and has no BDC, values troubled loans 3.6 points above the BDC median on average. For the other
registered fund managers, the average difference is zero (−0.05 points). With the stricter matching, the excess valuation of
troubled loans is smaller but has the same pattern: 1.4 points for loans valued between 90 and 95, 2.8 points for
Cliffwater and −0.4 points for the other registered fund managers. Over time, the excess valuation of troubled
loans by registered funds ranged from 1.1 to 3.4 points per quarter between September 2024 and June 2026, while the
average over all shared loans stayed within ±0.13 points.

Two features of the data qualify the comparison. Loans are matched by borrower, so that a registered fund holding a
senior tranche and a BDC holding a junior tranche of the same borrower could produce differences; restricting the BDC
side to positions identified as first lien leaves the results essentially unchanged. Differences between first-out
and last-out tranches of unitranche loans are rarely visible in the identifiers and cannot be ruled out.

### 6.3 The first quarter of 2026

For the 962 loans of registered funds that were also held by BDCs of other managers at the end of 2025 and in March
2026, the registered fund marked the loan down by 0.55 points on average and the median BDC by 0.69 points (Table 8).
When the median BDC marked a loan down by two points or more, the registered fund followed with a markdown of at
least one point in 41% of cases; when the registered fund marked down by two points or more, the BDC median followed
in 64%. The asymmetry is driven by Cliffwater (29% against 60%; average markdowns 0.46 against 0.71 points). For the
other registered fund managers, the follow rates are 57% and 68% and the average markdowns are identical (0.66 and
0.67 points). With the stricter matching (819 loans), the pattern is the same: registered funds marked down by 0.50
points and the median BDC by 0.65 points, Cliffwater followed BDC markdowns in 23% of cases against 54% in the reverse
direction, and the other managers in 56% against 64%.

For all loans held in both quarters, the value-weighted price change was −0.50% for registered funds and −1.22% for
BDCs, a difference of 0.72 percentage points (Table 9). On loans to the same borrowers, BDCs marked down by 0.14 points more than
the registered funds (equal-weighted, median BDC), about a fifth of the difference. Weighted by value, the share
rises to about 40%, because large BDC positions in shared borrowers were marked down more. With the stricter matching,
the shared loans make up only 18% of the value of BDCs, and their contribution falls to 0.08 points; the same-borrower
difference of 0.14 to 0.15 points (equal-weighted) is unchanged. The larger part of the
difference therefore arises on loans held by only one of the two vehicles: BDCs held more loans that were marked down
in early 2026, and the valuation practice of the dominant registered fund manager cannot be compared on loans without
a counterpart.

**Table 8. The same borrowers in Q4 2025 and Q1 2026: registered fund loans compared with the median BDC of other managers**

| | Loans | Mean change, registered fund | Mean change, BDC median | BDC down 2+: fund follows | Fund down 2+: BDC follows |
|---|---|---|---|---|---|
| All registered funds | 962 | −0.55 | −0.69 | 41% (99) | 64% (58) |
| Cliffwater | 536 | −0.46 | −0.71 | 29% (55) | 60% (30) |
| Other managers | 426 | −0.66 | −0.67 | 57% (44) | 68% (28) |

*Notes:* Loans held by a registered fund and by BDCs of other managers at both quarter-ends. Follow rates: share of markdowns of two points or more in one vehicle that are matched by a markdown of at least one point in the other in the same quarter (number of markdowns in parentheses). Changes in points of par.

**Table 9. Value-weighted price changes of continuing loans, Q4 2025 to Q1 2026**

| | Share of value in shared loans | Shared loans | Other loans | All loans |
|---|---|---|---|---|
| Registered funds | 50% | −0.38% | −0.62% | −0.50% |
| of which Cliffwater | 49% | −0.38% | −0.74% | −0.56% |
| of which other managers | 51% | −0.40% | −0.11% | −0.26% |
| BDCs (all positions) | 43% | −1.03% | −1.37% | −1.22% |
| BDCs (first lien only) | 45% | −1.02% | −1.06% | −1.04% |

*Notes:* Price changes of loans held at both quarter-ends, weighted by value at the end of 2025. Shared loans: borrowers held by both vehicles; the comparison of the same loans at the position level is in Table 8.

### 6.4 Implications

Three implications follow. First, the divergence between registered funds and BDCs in early 2026 does not appear to be
a difference between vehicles: a manager values loans to the same borrower alike in both, and registered fund managers
other than the largest value and mark down shared borrowers like the BDCs. It reflects, to a smaller part, the
valuation practice of the manager that dominates the direct lending of registered funds and, to a larger part,
differences in the loans held. The two cannot be fully separated: for loans without a counterpart, a manager effect
and a portfolio effect are observationally equivalent. Indices of registered funds therefore
partly measure the practice of one valuer, which motivates the equal weighting across managers in OpenDL US and
OpenDL Europe.

Second, the immediate effect on reported values is small. Had the registered funds valued their shared loans at the
median BDC valuation in March 2026, the value of these loans would have been 0.13% lower (0.16% with the stricter matching), or about 0.06% of
their net asset value. Troubled loans make up only about 7% of the shared loans, and performing loans are valued slightly
lower by registered funds. The disagreement matters more for timing than for levels: markdowns that one manager makes
in one quarter and another a quarter later shift returns between periods and between investors who subscribe or
redeem in between. This complements Dogaru (2026), who shows that BDCs relying more on payment-in-kind income report
higher values for the same loans; our evidence points to differences between managers rather than between vehicles,
and to the timing of markdowns as a main channel.

Third, the same disagreement on troubled loans appears in Europe, where it affects the comparison of benchmarks built
by different valuers. The level of a direct lending index is not only a property of the loans; it also depends on
whose valuations it aggregates. Open indices built from public filings make this dependence visible and allow it to
be measured.

## 7. Database, limitations and conclusion

### 7.1 Database

OpenDL Europe and OpenDL US BDC are published as versioned open databases on Zenodo under a Creative Commons
license (Mählmann, 2026d, 2026f). OpenDL Europe contains the quarterly returns of the main index, the value-weighted index and the value-weighted index without the largest
manager with their components, sub-indices for first-lien, euro and sterling loans, documented variants, a credit
health barometer and universe statistics. The code for the construction of the BDC panel, the indices and all
validations is available on GitHub under an MIT license (Mählmann, 2026e); the website loanfactors.org presents the
indices together with OpenDL US. The CDLI and Lincoln returns used for validation are compiled from public reports and
are not part of the published data. The indices are updated quarterly.

**Table 10. The OpenDL indices**

| | OpenDL Europe | OpenDL US BDC | OpenDL US |
|---|---|---|---|
| Loans | European currencies | US dollar | US dollar |
| Vehicles | BDCs | BDCs | Registered closed-end funds |
| Source | XBRL schedules of investments | XBRL schedules of investments | Form N-PORT |
| Returns from | Q2 2023 | Q2 2023 | Q1 2022 |
| Loans per quarter (mid-2026) | about 700 | about 20,000 | about 2,500 |
| Main benchmark | S&P Lincoln European Senior Debt Index (ESDI) | Cliffwater Direct Lending Index (CDLI) | Cliffwater Direct Lending Index (CDLI) |
| Data | Mählmann (2026d) | Mählmann (2026f) | Mählmann (2026c) |

*Notes:* Loans are positions as defined in Section 3 (BDCs) and in Mählmann (2026b) (registered funds), at the end of
June 2026. All indices report returns in loan currency, gross of fees and unlevered; main indices are equal-weighted
across managers. Code: Mählmann (2026e).

### 7.2 Limitations

The European index covers the European book of BDCs, that is, of US and global managers; European lenders that do not
file with the SEC are not included, and the index should not be read as a measure of the whole European market.
Identifiers are free text, and their normalization and linking are imperfect; about 15% of European positions are not
found again in the following quarter, most of them exits. BDCs do not tag non-accrual status, so distress is inferred
from identifiers and prices, and recoveries are taken from the N-PORT data of OpenDL US. The XBRL filings contain the
payment-in-kind rate of many positions (InvestmentInterestRatePaidInKind), which we do not yet process; it will be
included from the next update. Income is measured by contractual coupons, which
understates income relative to income statements. Finally, all returns rest on valuations, not transaction prices;
the evidence in Section 6 shows that these valuations depend on the manager.

### 7.3 Extensions

Three extensions are natural. The XBRL fact for payment-in-kind interest allows a direct measure of PIK usage and an
analysis of PIK as an early warning signal. The BDC panel can be linked to the outcomes of loans, such as defaults,
restructurings and recoveries, to assess how well valuations anticipate losses. And with OpenDL US BDC published alongside OpenDL US,
both vehicle types can be followed with the same method over time, so that differences in their valuations become
visible as they arise.

### 7.4 Conclusion

The schedules of investments of BDCs are a public, loan-level record of private credit. This paper shows that they can
be turned into reliable open benchmarks: applied to US loans, the procedure reproduces the established BDC-based
index, and applied to European loans, it yields OpenDL Europe, an open index of European direct lending. The same data
show that private loan valuations are a property of the manager rather than the vehicle, that managers disagree on
troubled loans and on the timing of markdowns, and that the level of any valuation-based index depends on whose
valuations it aggregates. Open data make this visible.

## Data availability

The SEC Financial Statement and Notes data sets and Form N-PORT filings are publicly available from the US Securities
and Exchange Commission. OpenDL Europe (Mählmann, 2026d), OpenDL US BDC (Mählmann, 2026f), OpenDL US (Mählmann, 2026c)
and the code (Mählmann, 2026e) are archived on Zenodo. The CDLI and Lincoln returns used for comparison were compiled from public reports; they are not
part of the published data.

## References

Anadu, K., and Wasner, J. (2026). Non-traded business development companies: Illiquid assets, valuation discretion,
and flow-performance sensitivity. Supervisory Research and Analysis Working Paper SRA 26-03, Federal Reserve Bank of
Boston, November 18, 2026.

Apollo (2025). Europe's private credit moment. White paper, Apollo Global Management, June 2025.

Block, J., Jang, Y. S., Kaplan, S. N., and Schulze, A. (2024). A survey of private debt funds. *Review of Corporate
Finance Studies*, 13(2), 335–383. https://doi.org/10.1093/rcfs/cfae001

Cera, K., Dieckelmann, D., Nikolov, K., Schepens, G., and Schwartz Blicke, O. (2026). Stress in global private credit
markets and its implications for euro area financial stability. Special feature D, *Financial Stability Review*, May
2026, European Central Bank.

Chernenko, S., Erel, I., and Prilmeier, R. (2022). Why do firms borrow directly from nonbanks? *Review of Financial
Studies*, 35(11), 4902–4947. https://doi.org/10.1093/rfs/hhac016

Chernenko, S., Ialenti, R., and Scharfstein, D. S. (2025). Bank capital and the growth of private credit. Working
paper, SSRN No. 5097437. https://doi.org/10.2139/ssrn.5097437

Cliffwater (2023). 2022 Q4 Report on U.S. Direct Lending. Cliffwater LLC. https://www.cliffwater.com

Cliffwater (2024). 2023 Q4 Report on U.S. Direct Lending. Cliffwater LLC. https://www.cliffwater.com

Cliffwater (2026a). Cliffwater Direct Lending Index Webcast for the First Quarter, 2026. Presentation, Cliffwater LLC.
https://www.cliffwaterdirectlendingindex.com

Cliffwater (2026b). Cliffwater Direct Lending Index Webcast for the Second Quarter, 2026, August 19, 2026. Presentation,
Cliffwater LLC. https://www.cliffwaterdirectlendingindex.com

Dogaru, A. (2026). Same loan, different marks: Income recognition and fair-value judgment. Working paper, University of
California, Berkeley. SSRN: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=7238961

Erel, I., Flanagan, T., and Weisbach, M. S. (2024). Risk-adjusting the returns to private debt funds. NBER Working Paper
32278. https://doi.org/10.3386/w32278

KBRA (2024). Private credit: BDC portfolio valuations are rigorous. Research report, Kroll Bond Rating Agency, May 20,
2024.

Lincoln International (2026). European Lincoln Private Market Index, quarterly reports Q2 2025 to Q2 2026; S&P Lincoln
European Senior Debt Index, quarterly reports. https://www.lincolninternational.com

Mählmann, T. (2026a). Leveraged loan factors from public data. Working paper, SSRN.
https://papers.ssrn.com/sol3/papers.cfm?abstract_id=7704758

Mählmann, T. (2026b). Direct lending returns from public data: An open index and what it reveals about private credit
valuations. Working paper, SSRN. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=7733980

Mählmann, T. (2026c). *OpenDL US: Registered Fund Direct Lending Index* (Version 2026.12) [Data set]. Zenodo.
https://doi.org/10.5281/zenodo.24280967

Mählmann, T. (2026d). *OpenDL Europe: BDC European Direct Lending Index* (Version 2026.12.1) [Data set]. Zenodo.
https://doi.org/10.5281/zenodo.24396813

Mählmann, T. (2026e). *Leveraged Loan Factors* (Version v2026.12.3) [Computer software; includes the code of OpenDL US and
OpenDL Europe]. Zenodo. https://doi.org/10.5281/zenodo.24114954 (version DOI 10.5281/zenodo.24444181)

Mählmann, T. (2026f). *OpenDL US BDC: BDC US Direct Lending Index* (Version 2026.12) [Data set]. Zenodo.
https://doi.org/10.5281/zenodo.24463013

Morgan Stanley Investment Management (2026). Evolution of direct lending: Direct lending primer. Morgan Stanley
Private Credit.

Pemberton and Saïd Business School (2025). *European Direct Lending Report 2025*. Pemberton Asset Management and Saïd
Business School, University of Oxford.

PitchBook (2026). 2025 Annual Global Private Debt Report. PitchBook Data.

S&P Dow Jones Indices (2026). S&P Dow Jones Indices and Lincoln International enhance S&P Lincoln Senior Debt Index
Series. Press release, August 11, 2026.

SEC (2020). Securities Offering Reform for Closed-End Investment Companies. Release Nos. 33-10771, 34-88606, IC-33836,
April 8, 2020.
