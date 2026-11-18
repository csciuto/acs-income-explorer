// American Income Explorer: percentiles.js
// The Percentiles view: household income at P1-P99 for the current place and filters. Precomputed from the full
// survey (docs/data/<src>/pct/, loaded on first use) where the stats table has the slice; otherwise from the chart's
// sample, with approximate errors (lib.js percentileTable).
// A plain script: these files share one set of globals and load in the order index.html lists them.

const PCT_KEY_ROWS = [10, 25, 50, 75, 90, 95, 99];
const pctFiles = {};      // file name -> {key: {v, se, tc}}, or null when it couldn't be fetched
const pctLoading = {};
let pctShowAll = false;
let pctShown = null;      // what the table shows, for the CSV

// Which file holds a key's percentiles (the pipeline's pct_file): national, state-FIPS (with its local areas), metro-CBSA.
function pctFileFor(key) {
  const [scope, code] = key.split('|')[0].split('=');
  if (scope === 'national') return 'national';
  if (scope === 'metro') return `metro-${code}`;
  const st = scope === 'puma' ? Math.floor(Number(code) / 100000) : Number(code);
  return `state-${String(st).padStart(2, '0')}`;
}

function loadPctFile(name) {
  if (!pctLoading[name]) {
    pctLoading[name] = fetch(dataUrl(`data/${source}/pct/${name}.json`))
      .then(r => (r.ok ? r.json() : null)).catch(() => null)
      .then(j => { pctFiles[name] = j; });
  }
  return pctLoading[name];
}

// {v, se, tc, live, n} for the current view; {loading: true} while its file is on the way; {n} when too few.
function getPercentiles() {
  const p = currentPlace();
  const dimFilter = householdFilterKey();
  // precomputed: the slices the stats table holds; for a local area, only the area as a whole
  if (dimFilter && placeCell(p, dimFilter) && (p.level !== 'puma' || !Object.keys(dimFilter).length)) {
    const key = placeKey(p, dimFilter);
    const file = pctFileFor(key);
    if (!(file in pctFiles)) {
      loadPctFile(file).then(() => { if (viewMode === 'ptile') renderPercentiles(); });
      return { loading: true };
    }
    const hit = pctFiles[file]?.[key];
    if (hit) return { ...hit, live: false, n: placeCell(p, dimFilter).n };
  }
  const cols = currentCols();
  const rows = visibleRows;
  const t = percentileTable(rows.map(i => cols.inc[i]), rows.map(i => cols.weight[i]),
                            cols.topcoded ? rows.map(i => cols.topcoded[i]) : null);
  return t ? { ...t, live: true, n: rows.length } : { n: rows.length };
}

function showPctView(on) {
  document.getElementById('chart-svg').style.display = on ? 'none' : '';
  document.getElementById('pct-view').hidden = !on;
}

function renderPercentiles() {
  const el = document.getElementById('pct-view');
  showPctView(true);
  d3.select('#chart-svg').selectAll('*').remove();
  brushLayer = null;
  chartScope = null;  // force a full renderChart() on the way back to dots
  dotData = [];
  const t = getPercentiles();
  pctShown = null;
  const head = `<div class="pct-head">
      <span class="panel-title">Household income percentiles</span>
      <button type="button" id="pct-all" aria-pressed="${pctShowAll}">${pctShowAll ? 'Fewer' : 'All 99'}</button>
      <button type="button" id="pct-csv"${t.v ? '' : ' disabled'}>CSV</button>
    </div>`;
  let body;
  if (t.loading) body = '<p class="pct-msg">Loading…</p>';
  else if (!t.v) body = `<p class="pct-msg">⚠ Too few households (${t.n ?? 0})</p>`;
  else {
    pctShown = t;
    const ks = pctShowAll ? Array.from({ length: 99 }, (_, i) => i + 1) : PCT_KEY_ROWS;
    const approx = t.live ? '≈' : '';
    const rows = ks.map(k => {
      const v = t.v[k - 1], se = t.se[k - 1];
      const cap = t.tc && k >= t.tc ? ' <span class="pct-cap" title="Near the survey\'s income cap">†</span>' : '';
      const key = PCT_KEY_ROWS.includes(k) && pctShowAll ? ' class="pct-key"' : '';
      return `<tr${key}><th scope="row">P${k}${k === 50 ? ' · median' : ''}</th>`
        + `<td>${v == null ? '—' : fmt$(v) + cap}</td>`
        + `<td class="pct-se">${se == null ? '' : `${approx}±${fmt$(se)}`}</td></tr>`;
    }).join('');
    const notes = [];
    if (t.live) notes.push(`≈ From the chart's sample (${t.n.toLocaleString()} households)`);
    if (t.tc && ks.some(k => k >= t.tc)) notes.push("† Near the survey's income cap");
    if (ks.some(k => t.v[k - 1] == null)) notes.push('— Too few households that far out');
    body = `<table class="pct-table" aria-label="Household income percentiles">
        <thead><tr><th scope="col">Percentile</th><th scope="col">Income</th><th scope="col">± SE</th></tr></thead>
        <tbody>${rows}</tbody></table>`
      + notes.map(n => `<p class="pct-note">${n}</p>`).join('');
  }
  el.innerHTML = head + body;
  el.querySelector('#pct-all').onclick = () => { pctShowAll = !pctShowAll; renderPercentiles(); };
  el.querySelector('#pct-csv').onclick = downloadPctCsv;
}

function downloadPctCsv() {
  const t = pctShown;
  if (!t) return;
  const lines = ['percentile,income,se,approximate,near_cap'];
  for (let k = 1; k <= 99; k++) {
    const v = t.v[k - 1], se = t.se[k - 1];
    lines.push([k, v ?? '', se ?? '', t.live ? 1 : 0, t.tc && k >= t.tc ? 1 : 0].join(','));
  }
  const slug = placeName(currentPlace()).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([lines.join('\n') + '\n'], { type: 'text/csv' }));
  a.download = `income-percentiles-${source}-${slug}.csv`;
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
