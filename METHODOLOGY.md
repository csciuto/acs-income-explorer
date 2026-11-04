# Methodology

How `preprocess.py` turns two IPUMS extracts into the explorer's data. What to request is in
[EXTRACT.md](EXTRACT.md); the code is in `pipeline/` (`common.py`, `acs.py`, `cps.py`).

## The two surveys

| | ACS (American Community Survey) | CPS ASEC (Current Population Survey) |
|---|---|---|
| Sample | IPUMS USA 5-year sample 2020–2024 | IPUMS CPS ASEC 2021–2025 |
| Income period | 12 months before each interview, interviews all year | previous calendar year (2020–2024) |
| Size | about 6 million households | about 290,000 households |
| Income questions | 8 | about 50 |
| Geography | states, 260+ metro areas, 2,462 local areas (PUMAs) | states; the 59 metro areas with 1,000+ survey households (METFIPS; the Census Bureau names only larger metros, and about a quarter of people live outside an identified one) |
| Replicate weights | 80, successive difference replication | 160, Fay's balanced repeated replication |
| Best for | places and narrow slices, housing costs | income sources, the official national figure |

Both are reduced to one row per household with the same derived variables, so the same filters work on both and
a slice can be compared across them.

## Universe and weights

- **ACS:** households only; group quarters (GQ 3 and 4) and vacant units are dropped. 5-year weights already
  describe an average year. If an extract holds several overlapping 5-year samples, only the latest is used.
- **CPS:** all ASEC household records; the weight is ASECWTH, divided by the 5 pooled years so counts describe an
  average year. Non-ASEC records stop the run.

## Dollars

Everything is in 2024 dollars.

- **ACS:** IPUMS already expresses 5-year amounts in the final year's dollars; each household's ADJUST (the Census
  Bureau's ADJINC) then accounts for when in the period it was interviewed. Pooled 1-year samples are also
  supported: ADJUST to the survey year, then CPI99 to the latest year.
- **CPS:** amounts are in the income year's dollars; × CPI99(year) / CPI99(2024).

## Households

Person records arrive grouped by household, householder first. Household variables come from the householder;
sums run over every member. Income items coded "not in universe" (all 9s, or 9…8, in the column's width) count as 0.

| Variable | ACS | CPS |
|---|---|---|
| `inc` | HHINCOME × dollar factor | same |
| `wage_inc` | Σ max(0, INCWAGE + INCBUS00) | Σ max(0, INCWAGE + INCBUS + INCFARM) |
| `passive_source` groups: SS / SSI | INCSS + INCSUPP | INCSS + INCSSI |
| retirement and pensions | INCRETIR (retirement, survivor and disability pensions, one item) | INCRETIR + INCPEN1 + INCPEN2 + INCRANN + INCSURV + INCDISAB |
| capital | INCINVST (interest, dividends and rent, one item) | INCINT + INCDIVID + INCRENT |
| public assistance | INCWELFR | INCWELFR |
| `educ` | EDUCD: <62, 62–64 diploma/GED, 65–100, 101, 110+ | EDUC: <73, 73 diploma, 80–110, 111, 120+ |
| `marst` cohabiting | unmarried partner present (RELATED 1114) | RELATE 1114, 1116, 1117 |
| `has_roommate` | RELATED 1115, 1241 | RELATE 1113, 1115, 1241 |
| `work_status` | EMPSTAT, CLASSWKR, UHRSWORK, WKSWORK2 | EMPSTAT, CLASSWKR, UHRSWORKLY, WKSWORK2 |
| `housing` | OWNERSHP + MORTGAGE | SPMMORT |
| `city` | METRO 5 principal city, 3 suburb, 1 non-metro | METRO 2, 3, 1 |
| ACS only | `burden` (12 × rent or owner costs ÷ income: <30%, 30–49%, 50%+), `metro_area` (MET2013), `puma` (state × 100,000 + PUMA) | |
| CPS only | | `multi_job_proxy` (hours at all jobs − main job) |
| `topcoded` | a member at the (year, state) maximum of an income item, which is where the ACS puts topcoded values | 0: the CPS swaps top values instead |

Shared definitions: `passive_pct` buckets the wage share of income (≥75%, 50–74%, 25–49%, under 25%, none);
`passive_source` is the largest of the four groups, set only when wages are under 75% of income; `breadwinner` is
the householder's share of household earnings; `earner_count` counts members with earnings, capped at 3;
`work_status` takes the first match of full-time full-year wage, full-time full-year self-employed, full-time
part-year, part-time, unemployed, retired (not in labor force, 55+, with Social Security), not working.

### Two traps in the CPS

- **Education.** EDUC 73 is "high school diploma or equivalent". The earlier CPS version binned it with some
  college, leaving "HS diploma" with 3% of households.
- **Pensions.** Since the 2019 ASEC redesign INCRETIR holds only retirement-account income for people 58+;
  pensions and annuities are INCPEN1, INCPEN2 and INCRANN ([IPUMS](https://cps.ipums.org/cps/asec_2019_changes.shtml)).
  The earlier version left them out, so almost no household looked pension-dependent. The preprocessor now refuses
  an extract without them, and reports how much of HHINCOME its income items account for (98.6% for 2021–2025).

## Statistics

Precomputed cells use every household.

- **Median:** linear interpolation within the $2,500 interval that holds it, as the Census Bureau does; otherwise
  respondents' round numbers pin the median and its replicates to one value and the standard error collapses.
- **Standard errors:** SE = √(4/R × Σ(θᵣ − θ)²) with R = 80 (ACS) or 160 (CPS), for the median and the mean.
- **Suppression:** fewer than 50 sample households, no statistics; 50–199 low, 200–499 moderate reliability.

| Scope | Cells |
|---|---|
| `national` | overall, each dimension value, each pair of values |
| `state=FIPS` | overall and each dimension value |
| `metro=CBSA` | overall; each dimension value for metros with 2,000+ households (CPS: listed only with 1,000+) |
| `puma=CODE` (ACS, one file per state) | overall and each value of age, work, housing, cost burden, kids, education, race, earners, income mix |

The page also shows the other survey's median whenever the same key exists in both.

## Browser samples

Each source's `national.arrow` holds 300,000 households drawn within year × state strata, weights scaled so each
stratum keeps its total. Each state's local file holds up to 300 households per local area. These drive the dots
and the statistics for views that aren't precomputed (shown without standard errors).

## Checks

The run stops if a required variable or the replicate weights are missing, if a code's label in the DDI doesn't
match what the code assumes, if a categorical column has an unexpected value, if a year's median is outside
$55k–$95k, if the wage-dominated share is outside 35–75%, if "HS diploma" isn't 15–40% of households, or if a
household's wages top $20M.
