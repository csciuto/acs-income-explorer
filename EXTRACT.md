# IPUMS USA extract for the ACS Income Explorer

What to request at https://usa.ipums.org/usa-action/variables/group so `preprocess.py`
can build the site. The preprocessor reads the DDI codebook and stops with a clear error
if a required variable is missing, so a wrong extract fails fast rather than silently.

## Samples

Select **ACS 1-year** samples for **2021, 2022, 2023 and 2024** (the "default" ACS samples,
not the 3-/5-year or PRCS ones).

- 2020 is left out on purpose: the 2020 ACS 1-year file has experimental weights because of
  COVID-era collection problems, and the Census Bureau advises against comparing it with other years.
- Each year has roughly 1.3 million households and 3.3 million people, so with replicate weights
  the compressed extract will be a few GB. That's expected.

## Format

- **Data format:** fixed-width text (`.dat`), the IPUMS default, gzipped.
- **Structure:** rectangular, person records (the default).
- Download the **DDI codebook (`.xml`)** along with the data. The preprocessor needs both.
- **Sample members:** default (no case selection). Group quarters are dropped by the preprocessor.

## Variables

Preselected technical variables (YEAR, SAMPLE, SERIAL, HHWT, CLUSTER, STRATA, GQ, PERNUM, PERWT)
come automatically; keep them all.

### Household

| Variable | Why |
|---|---|
| **REPWT** (household replicate weights, `REPWT1`–`REPWT80`) | Standard errors. Turn on via "Replicate weights" when selecting HHWT; pick household weights, not person. |
| STATEFIP | State |
| MET2013 | Metro area (2013 CBSA delineation). Enables per-metro views, which the CPS version can't do. |
| METRO | Principal city / suburb / non-metro |
| PUMA | Kept for later small-area work; not used yet |
| HHINCOME | Total household income (the headline number) |
| CPI99 | Converts every year to the same dollars |
| OWNERSHP | Owner vs renter |
| MORTGAGE | Owner with mortgage vs free and clear |
| RENTGRS | Gross rent (housing cost burden) |
| OWNCOST | Owner costs (housing cost burden) |

### Person

| Variable | Why |
|---|---|
| RELATE | Householder, partner and roommate detection (the detailed RELATED codes come with it) |
| AGE, SEX, MARST | Demographics |
| RACE, HISPAN | Race/ethnicity |
| NCHILD, YNGCH | Kids and youngest child's age |
| EDUC | Education (the detailed EDUCD comes with it) |
| EMPSTAT | Employment status (EMPSTATD comes with it) |
| CLASSWKR | Wage worker vs self-employed (CLASSWKRD comes with it) |
| WKSWORK2 | Weeks worked last year (bracketed) |
| UHRSWORK | Usual hours per week last year |
| INCTOT | Total personal income |
| INCWAGE | Wages and salary |
| INCBUS00 | Business and farm income |
| INCSS | Social Security |
| INCSUPP | Supplemental Security Income (SSI) |
| INCWELFR | Public assistance |
| INCRETIR | Retirement and pension income |
| INCINVST | Interest, dividends and rental income (the ACS reports these as one item) |
| INCOTHER | Other income (alimony, child support, VA, unemployment) |

## How this differs from the CPS extract

- **Much bigger sample** (about 15x the households per year), so states, metro areas and
  narrow slices get reliable estimates.
- **Capital income is one item.** The ACS reports interest, dividends and rent together as
  INCINVST, so there's no separate INCDIVID/INCRENT/INCINT.
- **No multiple-job detail.** The ACS doesn't ask about second jobs, so the CPS version's
  multi-job dimension is dropped.
- **SSI is its own item** (INCSUPP), so it can be counted with disability/SS income.
- **Income period is the previous 12 months** before the interview, not the previous calendar year.
  IPUMS already scales ACS income to the survey year's dollars; CPI99 then puts all years into
  2024 dollars.
- **80 household replicate weights** (successive difference replication) instead of 160 BRR person weights.
  The variance formula is the same, 4/R × Σ(θᵣ − θ)², so the SE code carries over unchanged.
- **Topcoding is per state.** Each income item above the state's 99.5th percentile is replaced by
  the mean of those values, so there's no single national topcode.

## After downloading

Put the `.dat.gz` and `.xml` anywhere (they're gitignored) and run:

```bash
python3 preprocess.py --input usa_000NN.dat.gz --ddi usa_000NN.xml --output-dir ./docs/data
```
