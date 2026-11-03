# IPUMS extracts for the American Income Explorer

The explorer has two sources. Request both at the same time; each comes as a fixed-width `.dat.gz` plus a DDI
codebook `.xml`, and the preprocessor needs both files of each.

| | ACS (geography, narrow slices, housing costs) | CPS ASEC (income detail, income sources) |
|---|---|---|
| Site | [usa.ipums.org](https://usa.ipums.org) | [cps.ipums.org](https://cps.ipums.org) |
| Sample | ACS **5-year 2020–2024** | ASEC **2021, 2022, 2023, 2024, 2025** (income years 2020–2024) |
| Format | fixed-width `.dat`, rectangular person records | same |
| Replicate weights | household REPWT, 80 | household REPWT, 160 |
| Case selection, attached characteristics, data quality flags, monetary adjustment, custom sample size | none | none |

The preprocessor reads the DDI and stops with a clear message if anything below is missing.

## ACS: IPUMS USA

**Sample:** the **ACS 5-year 2020–2024** sample only (not the 1-year samples, not PRCS, and not the earlier 5-year samples: 2017–2021 through 2019–2023 repeat the same households; if they're included anyway the preprocessor keeps only the latest). It pools five years of
interviews (about 5% of households), all on the 2020 PUMA boundaries, which is what makes local areas such as
"Medford & Malden" possible.

**Variables.** Preselected ones (YEAR, MULTYEAR, SAMPLE, SERIAL, CBSERIAL, HHWT, CLUSTER, STRATA, GQ, PERNUM, PERWT)
come automatically; keep them. Add:

| Household | Why |
|---|---|
| REPWT (household replicate weights, 80) | standard errors; pick *household*, not person |
| ADJUST | puts income into 2024 dollars (IPUMS doesn't apply it) |
| CPI99 | constant dollars |
| STATEFIP, PUMA, MET2013, METRO | state, local area, metro, principal city vs suburb |
| HHINCOME | household income |
| OWNERSHP, MORTGAGE, RENTGRS, OWNCOST | tenure and housing cost burden |

| Person | Why |
|---|---|
| RELATE (RELATED comes with it) | householder, partner, roommates |
| AGE, SEX, MARST, RACE, HISPAN, EDUC | demographics |
| NCHILD, YNGCH | children |
| EMPSTAT, CLASSWKR, WKSWORK2, UHRSWORK | work |
| INCTOT, INCWAGE, INCBUS00, INCSS, INCSUPP, INCWELFR, INCRETIR, INCINVST, INCOTHER | income |

MULTYEAR (preselected) gives each household's survey year, which drives the year filter.

## CPS: IPUMS CPS

**Samples:** in the sample picker, clear the default basic monthly samples and choose **ASEC 2021–2025** only.

**Variables.** Preselected ones (YEAR, SERIAL, MONTH, CPSID, ASECFLAG, ASECWTH, PERNUM, CPSIDP, ASECWT, …) come
automatically; keep them. Add:

| Household | Why |
|---|---|
| REPWT (household replicate weights, 160) | standard errors; pick *household* with ASECWTH |
| CPI99 | constant dollars |
| REGION, STATEFIP, METRO | geography and principal city vs suburb |
| HHINCOME | household income |
| OWNERSHP | owner vs renter |
| SPMMORT | owner with or without a mortgage |

| Person | Why |
|---|---|
| RELATE | householder, partner, roommates |
| AGE, SEX, MARST, RACE, HISPAN, EDUC | demographics |
| NCHILD, YNGCH | children |
| EMPSTAT, CLASSWKR, WKSWORK2, UHRSWORKLY | work last year |
| UHRSWORKT, UHRSWORK1 | multiple jobs (hours at all jobs vs main job) |
| INCTOT, INCWAGE, INCBUS, INCFARM | earnings |
| INCSS, INCSSI, INCDISAB, INCRETIR, INCSURV | Social Security, SSI, disability, retirement accounts, survivor benefits |
| **INCPEN1, INCPEN2, INCRANN** | pensions and annuities. Since the 2019 redesign these are no longer in INCRETIR, which covers only retirement accounts for people 58+ ([IPUMS](https://cps.ipums.org/cps/asec_2019_changes.shtml)). The preprocessor refuses to run without them |
| INCINT, INCDIVID, INCRENT | interest, dividends, rent, asked separately |
| INCWELFR, INCUNEMP, INCWKCOM, INCVET, INCEDUC, INCCHILD, INCALIM, INCASIST, INCOTHER | other sources |

The previous CPS extract lacked the pension items, so pension income was mostly missing from the old CPS version.

## After downloading

Put the four files anywhere outside the repo and run:

```bash
.venv/bin/python preprocess.py --acs usa_000NN.dat.gz --acs-ddi usa_000NN.xml \
                               --cps cps_000NN.dat.gz --cps-ddi cps_000NN.xml --output-dir ./docs/data
```
