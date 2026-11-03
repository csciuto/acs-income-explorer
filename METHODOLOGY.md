# Methodology

How `preprocess.py` turns an IPUMS USA extract of the American Community Survey into the explorer's data.
The extract itself is specified in [EXTRACT.md](EXTRACT.md).

## Source and universe

- **Samples:** ACS 1-year samples for 2021, 2022, 2023 and 2024 from IPUMS USA. 2020 is left out because its
  1-year file uses experimental weights.
- **Universe:** households. Group quarters (GQ 3 and 4: institutions, dorms, barracks) and vacant units are dropped.
  That leaves 5,296,401 households across the four years.
- **Pooling:** the four years are pooled. Household weights (HHWT) and the 80 replicate weights are divided by 4,
  so weighted counts describe an average year (about 130 million households).

## Dollars

ACS incomes cover the 12 months before each interview, and interviews run all year, so the raw amounts are in a
mix of dollars. Two adjustments:

1. **Survey-year dollars.** Each amount is multiplied by the Census Bureau's ADJINC for its sample (IPUMS calls it
   ADJUST and leaves it unapplied in single-year files): 2021 1.029928, 2022 1.042311, 2023 1.019518,
   2024 1.015250 ([IPUMS note](https://usa.ipums.org/usa/acsincadj.shtml)). The preprocessor uses ADJUST from the
   extract if it's there and these values otherwise, and stops for a year it has no factor for.
2. **Constant dollars.** Then × CPI99(year) / CPI99(2024), putting every year in 2024 dollars. `--nominal` skips this.

Check: after step 1, the weighted medians by year come out at $69,829 (2021), $74,775 (2022), $77,687 (2023) and
$81,644 (2024); the Census Bureau publishes $69,717, $74,755 and $77,719 for 2021–2023. Rounding and the Bureau's
interpolation account for the differences.

## Households

Person records arrive grouped by household, householder first (PERNUM 1). Household variables come from that
record; sums run over every member. Income items coded "not in universe" (all 9s, or 9…8, in the column's width)
count as zero.

| Variable | Definition |
|---|---|
| `inc` | HHINCOME, adjusted, floored at 0 |
| `wage_inc` | Sum over members of max(0, INCWAGE + INCBUS00) |
| `passive_inc` | max(0, `inc` − `wage_inc`) |
| `earner_count` | Members with INCWAGE + INCBUS00 > 0, capped at 3 |
| `breadwinner` | Householder's share of `wage_inc`: ≥90% sole, 60–89% primary, 40–59% co-earner, under 40% secondary, 0 non-earner |
| `passive_pct` | `wage_inc` / `inc`: ≥75%, 50–74%, 25–49%, under 25%, or no wages |
| `passive_source` | Largest of: SS + SSI (INCSS + INCSUPP), retirement (INCRETIR), capital (INCINVST: interest, dividends and rent, which the ACS asks as one item), public assistance (INCWELFR). Only when wages are under 75% of income |
| `marst` | Householder's MARST; "cohabiting" when an unmarried partner of the householder is present (RELATED 1114) and the householder isn't married with spouse present |
| `has_roommate` | A housemate/roommate (RELATED 1115) or roomer/boarder (1241) is present |
| `educ` | Householder's EDUCD: under 62 less than high school; 62–64 diploma or GED; 65–100 some college or associate's; 101 bachelor's; 110+ graduate or professional |
| `race_ethnicity` | Hispanic (HISPAN 1–4) of any race; otherwise White (RACE 1), Black (2), Asian/Pacific Islander (4–6), other or multiracial |
| `work_status` | Householder, first match wins: full-time (35+ usual hours) full-year (48+ weeks) wage worker; same, self-employed; full-time part-year; part-time; unemployed; retired (not in labor force, 55+, with Social Security); not working |
| `housing` | OWNERSHP and MORTGAGE: owner with a mortgage or contract to purchase, owner free and clear, renter |
| `burden` | 12 × monthly gross rent (renters) or selected owner costs (owners) ÷ household income in the same year's dollars: under 30%, 30–49%, 50%+, or N/A when there are no cash housing costs or no income |
| `city` | METRO: principal city (5), suburb (3), non-metro (1), metro but city status unknown (2, 4) |
| `metro_area` | MET2013 (2013 CBSA delineation). 0 where the area isn't identifiable in public data |
| `region` | Census region from STATEFIP |
| `topcoded` | A member has an income item (wages, business, retirement, investment) equal to the largest value of that item in their state and year. The ACS replaces values above each state's cutoff with the mean of those values, so the cap is the state maximum. About 3.6% of households |

The ACS has no question about second jobs, so the CPS version's multiple-job dimension is gone.

## Statistics

Precomputed cells use every household, not the browser sample.

- **Median:** found by linear interpolation within the $2,500 interval that holds it, as the Census Bureau does.
  Without that, respondents' round numbers (many households report exactly $80,000) pin the median and all of its
  replicates to one value, and the standard error comes out near zero.
- **Mean, percentiles, SD:** weighted; P25 and P75 are the first value at which cumulative weight reaches the quantile.
- **Standard errors:** successive difference replication with the 80 household replicate weights,
  SE = √(4/80 × Σ(θᵣ − θ)²), for the median and the mean. The confidence interval shown is around the mean.
  Pooled years share replicate numbers, the usual approximation when combining ACS years.
- **Suppression and reliability:** fewer than 50 sample households: no statistics. 50–199 low, 200–499 moderate,
  500+ high.

### Cells

Keys are `scope|dim=value|…` with dimensions sorted alphabetically. Dimension names: `age`, `sex`, `marst`, `educ`,
`region`, `city`, `work`, `kids`, `race`, `house`, `burden`, `earners`, `bread`, `ppct`, `psrc`, `year`.

| Scope | Cells | Standard errors |
|---|---|---|
| `national` | overall, every dimension value, every pair of dimension values | yes |
| `state=FIPS` | overall and every dimension value (except region) | yes |
| `metro=CBSA` | overall for every identifiable metro; every dimension value for metros with 2,000+ sample households | yes |

About 20,000 cells, 4 MB of JSON (under 1 MB compressed). When a view isn't precomputed (several values of one filter, several states,
or a combination not listed), the browser computes median, mean and percentiles from the sample, without
standard errors.

## The browser sample

`national.arrow` holds 300,000 households drawn within each year × state stratum in proportion to its size, with
weights scaled by (households in stratum ÷ households drawn) so each stratum keeps its weighted total. It drives
the dots, the group breakdowns, and the statistics for views that aren't precomputed.

## Validation

The preprocessor stops before writing anything if a categorical column has an unexpected value, a year's median
falls outside $60k–$95k, the share of wage-dominated households is outside 35–75%, or any household's wage
income tops $20M (a sign of "not in universe" codes leaking into a sum). It also stops if the extract lacks a
required variable or the replicate weights, or if the DDI's labels for the relationship codes it relies on have
changed.
