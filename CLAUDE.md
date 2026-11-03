# ACS Income Explorer

Static site served from `docs/` by GitHub Pages (deployed by `.github/workflows/deploy.yml`). No build step, no
bundler, no server. Everything runs in the browser or in the one-shot local preprocessor.

> **Deploy gotcha:** the frontend fetches `docs/data/{codebook.json,stats_precomputed.json,national.arrow}`. The
> raw IPUMS extract (1.25 GB gzipped, 9 GB raw) can't be processed in CI, so these files must be committed.

## What this is

US household income from IPUMS USA ACS 1-year samples 2021–2024, pooled, in constant 2024 dollars. Users filter
to a slice and see the weighted distribution, with replicate-weight standard errors where precomputed. Successor to
the CPS ASEC version (csciuto/am-inc-exp); same frontend, new data pipeline.

Docs: [EXTRACT.md](EXTRACT.md) (what to request from IPUMS), [METHODOLOGY.md](METHODOLOGY.md) (definitions and
statistics). Keep METHODOLOGY.md in sync when a derivation changes.

## Files

```
preprocess.py            IPUMS extract -> docs/data (see below)
docs/index.html          the entire frontend
docs/data/               national.arrow, stats_precomputed.json, codebook.json (committed)
docs/version.json        {"version":"dev"} locally; the deploy workflow overwrites it with v1.<commit count>
tests/test_preprocess.py unit tests on a fake extract built in tmp (no real data needed)
tests/test_frontend.py   Playwright tests against docs/ and its committed data
```

## Environment and tests

Python deps live in `.venv` (uv): `uv venv .venv && uv pip install --python .venv/bin/python -r requirements-test.txt`,
then `.venv/bin/python -m playwright install chromium`.

```bash
.venv/bin/python -m pytest tests/test_preprocess.py -p no:playwright   # fast
.venv/bin/python -m pytest --browser chromium                          # everything (~2 min)
```

Frontend tests need internet (D3 and Arrow from CDN). Don't run them while the preprocessor is writing docs/data.

## Preprocessor

```bash
.venv/bin/python preprocess.py --input usa_00017.dat.gz --ddi usa_00017.xml --output-dir ./docs/data
```

The extract lives outside the repo (currently `~/Downloads/usa_00017.*`). ~10 min, ~15 GB peak memory.

Pipeline:
1. `parse_ddi` / `check_extract`: column positions from the DDI; stop if a variable or the 80 REPWTs are missing,
   or if the RELATED labels for 1114/1115/1241 changed.
2. `read_extract`: every record is the same length, so chunks of bytes become uint8 arrays and columns are parsed
   with numpy (`parse_int`), not pandas.read_fwf. Replicate weights are kept only for each household's first person.
3. `build_households`: sums over members via `np.bincount` on a household index (PERNUM==1 starts a household).
   NIU codes (all 9s / 9…8 for the column width) count as 0. Topcode flag: member at the (year, state) max of an
   income item. Dollar factor = ADJUST (Census ADJINC; IPUMS doesn't apply it) × CPI99(year)/CPI99(latest).
4. `derive`: the Arrow columns. Drops GQ 3/4 and vacant units. Weights ÷ number of years.
5. `validate`: stop on impossible values or implausible medians.
6. `stratified_sample` -> `national.arrow` (300k rows, year × state strata, weights scaled N_h/n_h).
7. `compute_stats` -> `stats_precomputed.json` from ALL households (`CellStats` sorts by income once; medians are
   interpolated within $2,500 bins like the Census Bureau's, for the full sample and each replicate).

## Data schema (national.arrow)

`id` u32, `inc` u32, `wage_inc` u32, `passive_inc` u32, `weight` f32, `state` u8 (FIPS), `year` u8 (0=2021 … 3=2024),
`metro_area` u32 (MET2013 CBSA, 0 = not identifiable), then u8 codes: `age_bucket` (0 <25 … 7 65+), `sex` (1/2),
`marst`, `educ`, `region` (1–4), `metro` (0 non-metro, 1 metro, 2 unknown), `city` (0 principal city, 1 suburb,
2 non-metro, 3 metro/unknown), `kids`, `youngest_child`, `n_children`, `work_status`, `hours_category`,
`weeks_worked`, `topcoded`, `race_ethnicity`, `housing`, `burden` (0 <30%, 1 30–49%, 2 50%+, 3 N/A),
`has_roommate`, `earner_count`, `breadwinner`, `passive_pct`, `passive_source`, `hh_size`.
Labels for all of them are in `codebook.json` `labels`; metro names in `codebook.metros`.

## Precomputed stats

Key: `scope|dim=val|…`, dims sorted. Scopes: `national` (1-D and 2-D), `state=FIPS` (1-D), `metro=CBSA` (overall for
every metro, 1-D for metros with 2,000+ households). Dim names: `age sex marst educ region city work kids race house
burden earners bread ppct psrc year`. Cell: `{n, n_rep, med, mean, p25, p75, iqr, sd, wage_pct, rel, se_med,
se_mean, ci_lo, ci_hi}`; `rel` 3 n≥500, 2 n≥200, 1 n≥50; cells under 50 are absent.

Frontend (`getStats`): scope is `state=X` for one state, else `metro=X` for one metro area with no state, else
`national`; single-value filters become key parts via `DIM_TO_KEY`; anything multi-valued or missing falls back to
live stats from the sample (no SE).

## Frontend notes

Single `index.html`. Global state: `filters` (dim → Set), `selectedFips`, `colorMode`, `nationalTable`,
`precomputed`, `codebook`. Metro areas are a filter (`filters.metro_area`, single choice from the searchable list in
the Geo tab), so URL hashes like `#metro_area=14460&work_status=0` deep-link. In Static dot mode a chosen metro
narrows the dot pool to that metro.

Adding a filter/color dimension: palette in `PALETTES` (legend skips palette entries without a label), a
`.cm-btn`, a `.filter-btns` container in the right tab, entries in `FILTER_DEFS`, `DIM_LABELS`, `DIM_TO_KEY`
(if precomputed), the preprocessor's `DIMS`, `LABELS` and Arrow schema, and tests.
