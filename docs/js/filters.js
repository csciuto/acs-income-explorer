// American Income Explorer: filters.js
// Which households match the filters and the brushed income range; the range breakdown.
// A plain script: these files share one set of globals and load in the order index.html lists them.

// ============================================================
// Row filtering
// ============================================================
function computeVisibleRows() {
  const cols = currentCols();
  const n = cols.inc.length;
  const result = [];
  for (let i = 0; i < n; i++) {
    if (selectedFips.size > 0 && !selectedFips.has(cols.state[i])) continue;
    let pass = true;
    for (const [dim, vals] of Object.entries(filters)) {
      if (!vals || vals.size === 0) continue;
      if (!cols[dim]) continue;
      if (!vals.has(cols[dim][i])) { pass = false; break; }
    }
    if (pass) result.push(i);
  }
  return result;
}


function computeScope() {
  const base = selectedFips.size === 0 ? 'national' : [...selectedFips].sort().join(',');
  const m = filters.metro_area && filters.metro_area.size ? [...filters.metro_area].sort().join(',') : '';
  const pu = filters.puma && filters.puma.size ? [...filters.puma].sort().join(',') : '';
  return base + (m ? `|metro=${m}` : '') + (pu ? `|puma=${pu}` : '');
}

function matchesFilters(i, cols) {
  if (selectedFips.size > 0 && !selectedFips.has(cols.state[i])) return false;
  for (const [dim, vals] of Object.entries(filters)) {
    if (!vals || vals.size === 0) continue;
    if (!cols[dim]) continue;
    if (!vals.has(cols[dim][i])) return false;
  }
  return true;
}

function matchesBrush(i, cols) {
  if (!brushRange) return true;
  return cols.inc[i] >= brushRange.lo && cols.inc[i] <= brushRange.hi;
}

function isDimmed(i, cols, hasFilters) {
  if (hasFilters && !matchesFilters(i, cols)) return true;
  if (!matchesBrush(i, cols)) return true;
  return false;
}

function updateDotOpacity() {
  const cols = currentCols();
  const hasFilters = selectedFips.size > 0 || Object.values(filters).some(s => s && s.size > 0);
  d3.select('#chart-svg').selectAll('circle:not(.pin-ring)')
    .attr('opacity', d => isDimmed(d.i, cols, hasFilters) ? 0.12 : 0.75)
    .attr('pointer-events', d => isDimmed(d.i, cols, hasFilters) ? 'none' : 'all');
  syncPin();
}

function renderBrushInfo(transient) {
  const el = document.getElementById('brush-range-info');
  const r = transient || brushRange;
  if (!r) {
    el.innerHTML = '<div class="no-range">Click Range, then drag across the chart.</div>';
    return;
  }
  if (!visibleRows || !visibleRows.length) { el.innerHTML = ''; return; }
  const cols = currentCols();
  const {lo, hi} = r;
  const rangeRows = visibleRows.filter(i => cols.inc[i] >= lo && cols.inc[i] <= hi);
  const totalW = visibleRows.reduce((s, i) => s + cols.weight[i], 0);
  const rangeW = rangeRows.reduce((s, i) => s + cols.weight[i], 0);
  const pct = totalW > 0 ? (rangeW / totalW * 100).toFixed(1) : '0';
  let medStr = '—', meanStr = '—';
  if (rangeRows.length >= 5) {
    const inc = rangeRows.map(i => cols.inc[i]);
    const w   = rangeRows.map(i => cols.weight[i]);
    medStr  = fmt$(wPercentile(inc, w, 0.5));
    meanStr = fmt$(inc.reduce((s, v, k) => s + v * w[k], 0) / w.reduce((a, b) => a + b, 0));
  }
  el.innerHTML = `<div class="stat-row" style="margin-bottom:4px"><span class="stat-label" style="font-weight:600">${fmt$(lo)} – ${fmt$(hi)}</span></div>
    <div class="stat-row"><span class="stat-label">Households</span><span class="stat-val">${pct}% of slice</span></div>
    <div class="stat-row"><span class="stat-label">Median</span><span class="stat-val">${medStr}</span></div>
    <div class="stat-row"><span class="stat-label">Mean</span><span class="stat-val">${meanStr}</span></div>`;
  renderRangeBreakdown(transient);
}

function renderRangeBreakdown(transient) {
  const container = document.getElementById('range-breakdown');
  const expandBtn = document.getElementById('btn-expand-range');
  if (!container) return;
  const r = transient || brushRange;
  if (!r || !visibleRows || !visibleRows.length) {
    container.innerHTML = '';
    if (expandBtn) expandBtn.style.display = 'none';
    return;
  }

  const cols = currentCols();
  const rangeRows = visibleRows.filter(i => cols.inc[i] >= r.lo && cols.inc[i] <= r.hi);
  if (rangeRows.length === 0) {
    container.innerHTML = '';
    if (expandBtn) expandBtn.style.display = 'none';
    return;
  }

  if (expandBtn) expandBtn.style.display = '';
  // Populate content; visibility controlled by the expand toggle
  container.style.display = rangeBreakdownExpanded ? '' : 'none';

  if (colorMode === 'state') {
    const groups = new Map();
    for (const i of rangeRows) {
      const fips = cols.state[i];
      const idx = stateColorMap.get(fips);
      if (idx == null) continue;
      const color = idx < STATE_PALETTE.length ? STATE_PALETTE[idx] : '#888';
      if (!groups.has(fips)) groups.set(fips, { incs: [], weights: [], color });
      groups.get(fips).incs.push(cols.inc[i]);
      groups.get(fips).weights.push(cols.weight[i]);
    }
    const rows = [...groups.entries()].map(([fips, g]) => ({
      lbl: codebook?.states?.[String(fips)]?.name ?? `State ${fips}`,
      med: g.incs.length > 0 ? wPercentile(g.incs, g.weights, 0.5) : null,
      mean: g.incs.length > 0 ? g.incs.reduce((s,v,i) => s + v * g.weights[i], 0) / g.weights.reduce((a,b)=>a+b,0) : null,
      totalW: g.weights.reduce((a,b)=>a+b,0),
      color: g.color,
    }));
    _renderBreakdownRows(container, rows, rangeRows.length);
    return;
  }

  const palette = PALETTES[colorMode];
  if (!palette) { container.innerHTML = ''; return; }

  const lb = codebook?.labels?.[colorMode] || {};
  const colName = colorMode === 'state' ? 'state' : colorMode;
  const groups = new Map();

  for (const i of rangeRows) {
    const v = cols[colName]?.[i];
    if (v == null || palette[v] == null) continue;
    if (!groups.has(v)) groups.set(v, { incs: [], weights: [] });
    groups.get(v).incs.push(cols.inc[i]);
    groups.get(v).weights.push(cols.weight[i]);
  }

  const rows = [...groups.entries()]
    .map(([v, g]) => {
      const totalW = g.weights.reduce((a,b)=>a+b,0);
      return {
        v,
        lbl: lb[String(v)] ?? String(v),
        med: wPercentile(g.incs, g.weights, 0.5),
        mean: g.incs.reduce((s,val,i) => s + val * g.weights[i], 0) / totalW,
        totalW,
        color: palette[v],
      };
    })
    .sort((a,b) => a.v - b.v);

  _renderBreakdownRows(container, rows, rangeRows.length);
}
