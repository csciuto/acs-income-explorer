# American Income Explorer

An interactive look at US household income from two Census Bureau surveys, in 2024 dollars. Filter millions of
survey households down to a slice (work status, income sources, age, education, family, housing costs, state,
metro area, or a local area like Malden & Medford, MA) and see the weighted income distribution as dots, stacked
bars or a 100% view, with standard errors and reliability warnings.

**Live:** [corey.sciu.to/acs-income-explorer](https://corey.sciu.to/acs-income-explorer/)

## Two surveys, one tool

| | ACS (default) | CPS |
|---|---|---|
| | American Community Survey, 5-year 2020–2024 | Current Population Survey ASEC, income years 2020–2024 |
| Households | about 6 million | about 290,000 |
| Good at | states, metro areas, local areas, narrow slices, housing costs | income sources (pensions, interest, dividends), the official national income figures, multiple jobs |

Switch at the top right. When a slice exists in both, the sidebar shows the other survey's median too and flags
gaps larger than chance. [METHODOLOGY.md](METHODOLOGY.md) has the definitions; the two differ for real reasons
(the CPS asks about 50 income questions, the ACS 8; the ACS covers the 12 months before each interview).

This replaces an earlier CPS-only version, fixing its education coding, its missing pension income and its
standard errors along the way.

How to read it:

- **Weighted**, with counts for an average year.
- **Standard errors** from each survey's replicate weights for every precomputed view; live views (several values
  of a filter, several states) are computed from the chart's sample and have none.
- **Reliability:** under 50 sample households, no statistics; under 200 or 500, a warning.
- **The dots are a sample** (300,000 households per survey; up to 300 per local area).

Cite IPUMS ([USA](https://usa.ipums.org/usa/citation.shtml), [CPS](https://cps.ipums.org/cps/citation.shtml)) if
you publish results.

## Run it

```bash
python3 -m http.server -d docs 8000   # then open http://localhost:8000
```

## Tests

```bash
uv venv .venv && uv pip install --python .venv/bin/python -r requirements-test.txt
.venv/bin/python -m playwright install chromium
.venv/bin/python -m pytest --browser chromium
```

`tests/test_preprocess.py` builds small fake IPUMS extracts for both surveys and checks parsing, every derivation,
dollar adjustments, sampling and the replicate-weight standard errors (against a brute-force calculation).
`tests/test_frontend.py` drives the page with Playwright.

## Regenerating the data

1. Request the two extracts in [EXTRACT.md](EXTRACT.md).
2. Run:

   ```bash
   .venv/bin/python preprocess.py --acs usa_00018.dat.gz --acs-ddi usa_00018.xml \
                                  --cps cps_00008.dat.gz --cps-ddi cps_00008.xml --output-dir ./docs/data
   ```

   Either survey can be rebuilt alone. The preprocessor checks each extract against what it needs and stops with
   a clear message if something is missing or IPUMS has renumbered a code.
3. Commit `docs/data/` (the raw extracts are too large for CI) and push.

## Deploying and versioning

Pushing to `main` deploys `docs/` through `.github/workflows/deploy.yml`, which writes `v1.<commit count>` into
`docs/version.json` for the footer.

## License

MIT, see [LICENCE](LICENCE).
