# ACS Income Explorer

An interactive look at US household income, built from American Community Survey microdata (2021–2024, in 2024
dollars). Filter 5.3 million survey households down to a slice — work status, income mix, age, education, family,
housing cost burden, state, metro area, city or suburb — and see the weighted income distribution as dots,
stacked bars or a 100% view, with standard errors and reliability warnings.

It's the ACS successor to the [CPS-based American Income Explorer](https://github.com/csciuto/am-inc-exp). The
ACS is about 15 times bigger per year, which is what makes states, metro areas and narrow slices reliable.

A static site: one `index.html` and three data files, no backend, no build step. The heavy lifting is a one-shot
local preprocessor.

## The data

**Source:** [IPUMS USA](https://usa.ipums.org/), ACS 1-year samples 2021–2024, pooled. One row per household
(group quarters excluded). Income is total household income over the 12 months before the interview, put into
2024 dollars.

How to read it:

- **Weighted.** Statistics use the household weights, divided by 4 so counts describe an average year
  (about 130 million households).
- **Standard errors** come from the ACS's 80 replicate weights, for every precomputed view: national, each state,
  each metro area, and combinations of filters (see [METHODOLOGY.md](METHODOLOGY.md) for which).
- **Reliability.** Fewer than 50 sample households: no statistics. Under 200 or 500: a warning.
- **The dots are a sample.** The chart draws from 300,000 households sampled within each year and state; the
  sidebar statistics come from all 5.3 million when the view is precomputed, and from the sample otherwise.
- **Topcoding (⊕).** The ACS replaces income items above a state's cutoff with the state mean of those values,
  so the top of the distribution is compressed.

Cite IPUMS USA per its [terms](https://usa.ipums.org/usa/citation.shtml) if you publish results.

## Run it

```bash
python3 -m http.server -d docs 8000   # then open http://localhost:8000
```

D3 and Apache Arrow load from a CDN, so the browser needs internet access.

## Tests

```bash
uv venv .venv && uv pip install --python .venv/bin/python -r requirements-test.txt
.venv/bin/python -m playwright install chromium
.venv/bin/python -m pytest --browser chromium
```

- `tests/test_preprocess.py`: unit tests on a small fake IPUMS extract (codebook + fixed-width records) built in
  a temp directory, so they don't need the real download. They cover parsing, every derived variable, the dollar
  adjustments, the browser sample, and the replicate-weight standard errors against a brute-force calculation.
- `tests/test_frontend.py`: Playwright tests of the page against the committed data.

## Regenerating the data

1. Request the extract described in [EXTRACT.md](EXTRACT.md) from IPUMS USA (fixed-width `.dat.gz` plus the DDI
   `.xml`).
2. Run:

   ```bash
   .venv/bin/python preprocess.py --input usa_00017.dat.gz --ddi usa_00017.xml --output-dir ./docs/data
   ```

   It reads the 9 GB file in about a minute and spends most of its time on standard errors (about 10 minutes on
   a 2024 laptop; it needs roughly 15 GB of memory). `--skip-stats` skips them. It checks the extract first and
   stops with a clear message if something is missing.
3. Commit `docs/data/` (the site can't rebuild it; the raw extract is far too big for CI).

Adding a year: add its ADJUST factor to `ADJUST_BY_YEAR` in `preprocess.py` (or include ADJUST in the extract).
The preprocessor refuses to run without one.

## Layout

```
preprocess.py          IPUMS extract -> docs/data
docs/index.html        the whole frontend
docs/data/
  national.arrow         300,000-household sample (~15 MB)
  stats_precomputed.json exact statistics with standard errors (~4 MB)
  codebook.json          labels, states, metro areas
EXTRACT.md             what to request from IPUMS
METHODOLOGY.md         definitions and statistical methods
```

## Deploying and versioning

Pushing to `main` deploys `docs/` to GitHub Pages through `.github/workflows/deploy.yml`, which writes
`docs/version.json` with `v1.<commit count>`; the footer shows it.

## License

MIT, see [LICENCE](LICENCE).
