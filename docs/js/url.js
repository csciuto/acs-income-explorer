// American Income Explorer: url.js
// The address holds the whole view; reading it and writing it.
// A plain script: these files share one set of globals and load in the order index.html lists them.

// ============================================================
// URL state (deep-link)
// ============================================================
function pushUrl() {
  const params = new URLSearchParams();
  if (source !== 'acs') params.set('src', source);
  if (colorMode !== 'passive_pct') params.set('cm', colorMode);
  for (const [dim, vals] of Object.entries(filters)) {
    if (vals && vals.size > 0) params.set(dim, [...vals].sort().join(','));
  }
  if (selectedFips.size > 0) params.set('states', [...selectedFips].sort().join(','));
  if (brushRange) { params.set('brush_lo', brushRange.lo); params.set('brush_hi', brushRange.hi); }
  if (viewMode !== 'dots') params.set('v', viewMode);
  if (maxDots !== 3000) params.set('md', maxDots);
  if (!sampleMode) params.set('sm', '0');
  const qs = params.toString();
  history.replaceState(null, '', qs ? '#' + qs : location.pathname + location.search);
}

function applyUrl() {
  const hash = location.hash.slice(1);
  if (!hash) return;
  const params = new URLSearchParams(hash);

  let cm = params.get('cm');
  if (cm === 'state') cm = 'region';  // older links: coloring by chosen states became coloring by region
  if (cm) {
    colorMode = cm;
    document.querySelectorAll('.cm-btn').forEach(b => b.classList.toggle('active', b.dataset.mode === cm));
    _legendColorMode = null;
  }

  const statesStr = params.get('states');
  if (statesStr) {
    selectedFips.clear();
    statesStr.split(',').forEach(s => { const f = parseInt(s); if (!isNaN(f)) selectedFips.add(f); });
    updateStateColorMap();
  }

  const brushLo = params.get('brush_lo');
  const brushHi = params.get('brush_hi');
  if (brushLo && brushHi) { brushRange = {lo: parseInt(brushLo), hi: parseInt(brushHi)}; switchStatsTab('range'); }

  const v = params.get('v');
  if (v) {
    viewMode = v;
    document.querySelectorAll('.view-btn').forEach(b => b.classList.toggle('active', b.dataset.view === v));
  }

  const md = parseInt(params.get('md'));
  if ([1000, 3000, 5000].includes(md)) {
    maxDots = md;
    document.querySelectorAll('.dots-btn').forEach(b => b.classList.toggle('active', parseInt(b.dataset.maxdots) === md));
  }

  if (params.get('sm') === '0') {
    sampleMode = false;
    syncSampleButtons();
  }

  filters = {};
  for (const [key, val] of params.entries()) {
    if (['src', 'cm', 'states', 'brush_lo', 'brush_hi', 'v', 'md', 'sm'].includes(key)) continue;
    const nums = val.split(',').map(Number).filter(v => !isNaN(v));
    if (nums.length) filters[key] = new Set(nums);
  }
}

window.addEventListener('popstate', () => { applyUrl(); render(); });
