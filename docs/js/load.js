// American Income Explorer: load.js
// Loading: the codebook and statistics first, then the households; switching survey; the pieces of state derived from the data.
// A plain script: these files share one set of globals and load in the order index.html lists them.

// ============================================================
// Helpers
// ============================================================
// Household counts at a sensible unit: 840, 12K, 1.2M
function label(dim, val) {
  if (dim === 'year') return codebook?.year_display?.[String(val)] ?? String(val);
  const lb = codebook?.labels?.[dim];
  if (!lb) return String(val);
  return lb[String(val)] ?? String(val);
}

// ============================================================
// Arrow column extraction
// ============================================================
function extractColumns(arrowTable) {
  const cols = {};
  for (const name of arrowTable.schema.fields.map(f => f.name)) {
    cols[name] = arrowTable.getChild(name).toArray();
  }
  return cols;
}

// ============================================================
// Data loading
// ============================================================
// The deploy stamps the page with its version; data addresses carry it, so a reload after an update fetches
// the new files instead of ones the browser kept (GitHub Pages lets it keep them for ten minutes).
const DATA_V = (document.getElementById('version-stamp')?.textContent || 'dev').trim();
const dataUrl = path => `${path}?v=${DATA_V}`;

async function loadArrow(url) {
  const res = await fetch(dataUrl(url));
  if (!res.ok) throw new Error(`Failed to fetch ${url}: ${res.status}`);
  const buf = await res.arrayBuffer();
  return Arrow.tableFromIPC(new Uint8Array(buf));
}

async function init() {
  setLoading('Loading…');
  // The households are most of the download (about 4.8 MB of 6). Their fetch starts now but isn't waited for:
  // the codebook and the precomputed statistics are enough to show the headline numbers first.
  const households = loadArrow(`data/${source}/national.arrow`);
  households.catch(() => {});   // reported below, where it is awaited
  const [cb, stats, ver] = await Promise.all([
    fetch(dataUrl('data/codebook.json')).then(r => r.json()),
    fetch(dataUrl(`data/${source}/stats.json`)).then(r => r.json()),
    fetch('version.json', { cache: 'no-cache' }).then(r => r.json()).catch(() => null),
  ]);
  if (ver) {
    const el = document.getElementById('version-stamp');
    if (el) el.textContent = ver.version + (ver.date ? ` · ${ver.date}` : '');
  }

  codebook = cb;
  precomputed = stats;

  srcInfo = codebook.sources[source];
  codebook.year_display = srcInfo.years;
  codebook.labels.year = { ...srcInfo.years };
  // Metro areas this survey can show (the CPS names only larger ones); names from either survey for notes.
  codebook.metros = srcInfo.metros || {};
  codebook.metroNames = Object.fromEntries(['acs', 'cps'].flatMap(k =>
    Object.entries(codebook.sources[k]?.metros || {}).map(([c, m]) => [c, m.name])));
  codebook.labels.metro_area = Object.fromEntries(
    Object.entries(codebook.metros).map(([k, m]) => [k, m.name])
  );
  codebook.localAreas = codebook.sources.acs?.local_areas || {};
  // Each local area lies in one state and one metro area (0 = none): the place breadcrumbs and the CPS
  // fallback (metro or local area -> its state) come from this table.
  codebook.geoAreas = Object.entries(codebook.localAreas)
    .filter(([, a]) => a.metro !== undefined && a.city !== undefined)
    .map(([code, a]) => ({ code: parseInt(code), state: a.state, metro: a.metro, city: a.city, n: a.n }));
  codebook.labels.puma = Object.fromEntries(
    Object.entries(codebook.localAreas).map(([k, a]) => [k, localName(a).join(' · ')])
  );
  applySourceUI();
  // the other survey's stats, for the comparison line (not needed to draw the page)
  const other = source === 'acs' ? 'cps' : 'acs';
  if (codebook.sources[other]) {
    fetch(dataUrl(`data/${other}/stats.json`)).then(r => r.json()).then(j => { otherPrecomputed = j; renderStats(getStats()); }).catch(() => {});
  }

  // Hide groupings and filters this survey doesn't have. The codebook lists each survey's columns, so this
  // doesn't wait for the households.
  const has = dim => srcInfo.columns.includes(dim);
  document.querySelectorAll('.cm-btn[data-mode]').forEach(b => {
    const m = b.dataset.mode;
    if (m !== 'state' && !has(m)) b.remove();
  });
  for (const { id, dim } of FILTER_DEFS) {
    if (!has(dim)) document.getElementById(id)?.closest('.filter-group')?.remove();
  }
  if (!has('puma') || !Object.keys(codebook.localAreas).length) document.getElementById('local-group')?.remove();

  buildFilterUI();
  buildPlacePicker();
  applyUrl();
  normalizePlace();  // before dropping columns this survey lacks: a CPS link to a local area falls back to its state
  for (const k of Object.keys(filters)) if (!has(k)) delete filters[k];  // a filter the other survey had
  if (filters.puma) {
    filters.puma = new Set([...filters.puma].filter(c => codebook.localAreas[c]));
    if (!filters.puma.size) delete filters.puma;
  }

  showHeadline();
  nationalTable = extractColumns(await households);
  buildFipsToRegion();
  if (filters.puma) await ensureLocal([...filters.puma][0]);
  syncPlace();
  hideLoading();
  renderLegend();
  render();
}

// While the households load: the place's name and its statistics, when the precomputed table has this slice
// (one place, at most one value per filter). The loading notice moves over the chart, the only part still
// waiting, and the controls stay off until there is something for them to act on.
const WAITING = ['source-switch', 'stats-tab-bar', 'sidebar-body', 'toolbar'];
function showHeadline() {
  const p = currentPlace(), key = householdFilterKey();
  const cell = key && p.level !== 'puma' ? placeCell(p, key) : null;
  const title = document.getElementById('place-title');
  if (title) title.textContent = placeName(p);
  if (cell) {
    const s = { ...cell, source: 'precomputed', other: null };
    renderStats(s);
    renderMobileStats(s);
  }
  const overlay = document.getElementById('loading');
  document.getElementById('chart-wrap').appendChild(overlay);
  overlay.classList.add('over-chart');
  document.getElementById('loading-msg').textContent = 'Loading households…';
  for (const id of WAITING) document.getElementById(id)?.setAttribute('inert', '');
}

// ============================================================
// Data source (ACS / CPS)
// ============================================================
function applySourceUI() {
  const yrs = Object.values(srcInfo.years);
  document.getElementById('header-sub').textContent =
    `${srcInfo.name} · ${yrs[0]}–${yrs[yrs.length - 1]} · ${srcInfo.dollars}`;
  document.getElementById('about-data').textContent =
    `${srcInfo.about} ${srcInfo.strengths} ${srcInfo.se} ${srcInfo.topcodes}`.trim();
  const link = document.getElementById('ipums-link');
  link.href = source === 'cps' ? 'https://cps.ipums.org' : 'https://usa.ipums.org';
  link.textContent = source === 'cps' ? 'IPUMS CPS' : 'IPUMS USA';
  document.querySelectorAll('#source-switch button').forEach(b => {
    b.classList.toggle('active', b.dataset.src === source);
    b.setAttribute('aria-pressed', b.dataset.src === source);
    b.onclick = () => setSource(b.dataset.src);
  });
}

function setSource(s) {
  if (s === source) return;
  const params = new URLSearchParams(location.hash.slice(1));
  if (s === 'acs') params.delete('src'); else params.set('src', s);
  // replaceState, not location.hash: a hash change fires popstate, whose handler would rewrite the URL first
  history.replaceState(null, '', '#' + params.toString());
  location.reload();
}

// Local areas (ACS PUMAs): "Middlesex County (East)--Malden & Medford" -> ["Malden & Medford, MA", "Middlesex County (East)"]
function localName(a) {
  const abbr = codebook.states?.[String(a.state)]?.abbr ?? '';
  const [where, what] = a.name.includes('--') ? a.name.split('--') : [null, a.name];
  return [`${what}, ${abbr}`].concat(where ? [where] : []);
}

async function ensureLocal(code) {
  const st = Math.floor(code / 100000), ss = String(st).padStart(2, '0');
  if (localTables[st]) return;
  if (!localLoading[st]) {
    localLoading[st] = Promise.all([
      fetch(dataUrl(`data/acs/local/${ss}.json`)).then(r => r.json()),
      loadArrow(`data/acs/local/${ss}.arrow`),
    ]).then(([j, t]) => { localStats[st] = j; localTables[st] = extractColumns(t); });
  }
  await localLoading[st];
}





// ============================================================
// Default filters
// ============================================================

// ============================================================
// State → region mapping (derived from nationalTable)
// ============================================================
function buildFipsToRegion() {
  const cols = nationalTable;
  for (let i = 0; i < cols.state.length; i++) {
    const s = cols.state[i];
    const r = cols.region[i];
    if (!fipsToRegion.has(s)) {
      fipsToRegion.set(s, r);
      if (!regionToFips.has(r)) regionToFips.set(r, new Set());
      regionToFips.get(r).add(s);
    }
  }
}

// ============================================================
// State color map
// ============================================================
function updateStateColorMap() {
  stateColorMap.clear();
  let idx = 0;
  for (const fips of selectedFips) {
    stateColorMap.set(fips, idx++);
  }
}

// ============================================================
// Current table (always national)
// ============================================================
function currentCols() {
  // a chosen local area draws on that state's local file, which holds far more of its households
  const pu = filters.puma && filters.puma.size ? [...filters.puma][0] : null;
  if (pu != null && localTables[Math.floor(pu / 100000)]) return localTables[Math.floor(pu / 100000)];
  return nationalTable;
}
