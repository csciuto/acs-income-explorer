# American Income Explorer

Static site served from `docs/` by GitHub Pages. `.github/workflows/deploy.yml` runs `pytest` (pipeline tests, browser
tests at desktop and phone size, axe accessibility checks in `tests/test_a11y.py`) and deploys only if they pass.
No build step, no server. Follows the app standards in
[csciuto/app-template STANDARDS.md](https://github.com/csciuto/app-template/blob/main/STANDARDS.md); commit and push
freely once tests pass.
Two data sources in one app: the ACS (default) and the CPS ASEC, switchable in the header (`#src=cps`).

> **Deploy gotcha:** the site fetches `docs/data/**` at runtime; the raw IPUMS extracts (ACS ~5 GB, CPS ~240 MB
> gzipped) can't be processed in CI, so the generated data is committed.

Docs: [ARCHITECTURE.md](ARCHITECTURE.md) (how it's built; keep current), [EXTRACT.md](EXTRACT.md) (what to request), [METHODOLOGY.md](METHODOLOGY.md) (definitions, statistics; keep
in sync with `pipeline/`). Successor to an earlier CPS-only app (deleted; corey.sciu.to/am-inc-exp/ redirects here from the csciuto.github.io repo).

## Files

```
preprocess.py            CLI: --acs/--acs-ddi and/or --cps/--cps-ddi -> docs/data (rebuild either alone)
pipeline/common.py       DDI + fixed-width reading (numpy), household sums, CellStats (interpolated medians,
                         replicate SEs), stratified sample, stats scopes, local-area stats
pipeline/acs.py, cps.py  per-survey variables, code checks against DDI labels, derivations
geo/                     PUMA names from Census TIGER/Line (fetch_puma_names.py -> puma_names_2020.json)
docs/index.html          the page: markup and styles
docs/js/lib.js           pure helpers (formatting, weighted statistics), unit-tested in Node: tests/js
docs/js/*.js             the rest of the frontend, one plain script per concern, sharing globals, loaded in order
docs/data/codebook.json  labels, states, sources{acs,cps}: years, columns, dims, notes, metros, local_areas
docs/data/<src>/         national.arrow (300k sample), stats.json
docs/data/acs/local/     <state>.json local-area stats, <state>.arrow up to 300 households per area
```

## Environment and tests

`.venv` via uv: `uv venv .venv && uv pip install --python .venv/bin/python -r requirements-test.txt`, then
`.venv/bin/python -m playwright install chromium`.

```bash
.venv/bin/python -m pytest tests/test_preprocess.py -p no:playwright   # unit tests on fake extracts, <1 s
.venv/bin/python -m pytest --browser chromium                          # everything, ~2.5 min
```

Don't run browser tests while the preprocessor is writing docs/data.

## Preprocessor

```bash
.venv/bin/python preprocess.py --acs ~/Downloads/usa_00018.dat.gz --acs-ddi ~/Downloads/usa_00018.xml \
    --cps ~/Downloads/cps_00008.dat.gz --cps-ddi ~/Downloads/cps_00008.xml --output-dir ./docs/data
```

The ACS 5-year file is ~16M person records; peak memory is high, so close other heavy work. The CPS alone takes
~20 s. Both loaders verify codes against the DDI labels and stop with a message if IPUMS renumbers something.

## Data (per source national.arrow)

Shared: `id inc wage_inc passive_inc weight state year region age_bucket sex marst educ metro kids youngest_child
n_children work_status hours_category weeks_worked earner_count breadwinner passive_pct passive_source
race_ethnicity housing topcoded has_roommate hh_size`. ACS adds `city metro_area puma burden`; CPS adds
`city multi_job_proxy metro_area`. `year` indexes `codebook.sources[src].years` (both 2020–2024; CPS by income year).

## Stats keys

`scope|dim=val|…`, dims sorted. Scopes `national`, `state=FIPS`, `metro=CBSA` (both; CPS names from `geo/metro_names_2013.json`), `puma=CODE` (ACS, in
`acs/local/<state>.json`). Dims: `age sex marst educ region city work kids race house earners bread ppct psrc year`
plus `burden` (ACS) and `mjob` (CPS). Cells `{n, n_rep, med, mean, p25, p75, rel, se_med, …}`; under 50 absent.

## Frontend

Globals: `source`, `srcInfo`, `filters` (dim → Set), `selectedFips`, `nationalTable`, `precomputed`,
`otherPrecomputed` (other survey, for the comparison line), `localStats`/`localTables` (per state, loaded on
demand). `currentCols()` returns the local table when a local area is selected. `getStats()` picks scope
`state=` (one state) > `puma=` > `metro=` > `national`, builds the key via `DIM_TO_KEY`, falls back to live stats.
UI elements for columns a source lacks are removed at load. Place tab: one place at a time (US, region, state, metro, local area), stored
in the old selections so links work (`states=`, `region=`, `metro_area=`, `puma=`). `currentPlace()`, `setPlace()`,
`normalizePlace()` (old multi-place links keep the most specific; the CPS falls back from a local area to its metro
or state, and from a metro it doesn't list to the state, with `placeNote`), `placeChain()` (place -> larger areas) and `placeCell()` (precomputed cell for a place and
single-valued household filters) drive the stats, breadcrumbs and the larger-area rows. Area type (`city`) is a
household filter in the Demo tab. Switching source rewrites the hash with
`history.replaceState` and reloads (a hash assignment would fire popstate and drop `src`).

Adding a dimension: preprocess `SHARED_DIMS`/`SOURCE_DIMS` + `LABELS` + loader column; frontend `PALETTES`,
`.cm-btn`, filter container, `FILTER_DEFS`, `DIM_LABELS`, `DIM_TO_KEY`; tests.

## Help page

`docs/help.html` with clips in `docs/help/*.webp` (animated WebP, ~300-700KB each), recorded by
`.venv/bin/python tools/help_clips.py [name…]` (Playwright + Pillow: `uv pip install --python .venv/bin/python pillow`).
Re-record a clip whenever the UI it shows changes.


## Visible text

Labels, not sentences. A note is one short line; explanations of method belong in METHODOLOGY.md, not the page.
Survey notes shown to readers live in `NOTES` in preprocess.py (copied into codebook.json) and follow the same rule.
