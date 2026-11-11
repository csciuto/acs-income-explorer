// American Income Explorer: breakdown.js
// The breakdown by color group, and the legend.
// A plain script: these files share one set of globals and load in the order index.html lists them.

// ============================================================
// Group breakdown (by color)
// ============================================================
function renderGroupBreakdown() {
  const container = document.getElementById('group-breakdown');
  if (!container) return;
  if (!visibleRows || visibleRows.length === 0) { container.innerHTML = ''; return; }

  const cols = currentCols();
  const colName = colorMode === 'state' ? 'state' : colorMode;

  if (colorMode === 'state') {
    if (stateColorMap.size === 0) { container.innerHTML = '<div style="color:var(--text-dim);font-size:12px;padding:8px 0">Select states in the Geo tab to see breakdown.</div>'; return; }
    const groups = new Map();
    for (const i of visibleRows) {
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
    _renderBreakdownRows(container, rows, visibleRows.length);
    return;
  }

  const palette = PALETTES[colorMode];
  if (!palette) { container.innerHTML = ''; return; }

  const lb = codebook?.labels?.[colorMode] || {};
  const groups = new Map();

  for (const i of visibleRows) {
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

  _renderBreakdownRows(container, rows, visibleRows.length);
}

function _renderBreakdownRows(container, rows, n) {
  if (rows.length === 0) { container.innerHTML = ''; return; }
  const cmLabel = colorMode.replace(/_/g, ' ');
  container.innerHTML = `
    <div style="font-size:11px;color:var(--text-dimmer);margin-bottom:6px">Grouped by ${cmLabel} · median &amp; mean household income</div>
    <div style="display:grid;grid-template-columns:10px 1fr auto auto auto;gap:4px 6px;align-items:baseline;font-size:11px">
      <span></span>
      <span style="color:var(--text-dimmer)">Group</span>
      <span style="color:var(--text-dimmer)">Median</span>
      <span style="color:var(--text-dimmer)">Mean</span>
      <span style="color:var(--text-dimmer)">Households</span>
      ${rows.map(r => `
        <span class="breakdown-dot" style="background:${r.color};align-self:center"></span>
        <span class="breakdown-label">${r.lbl}</span>
        <span class="breakdown-med">${r.med != null ? fmt$(r.med) : '—'}</span>
        <span class="breakdown-med" style="color:var(--text-dim)">${r.mean != null ? fmt$(r.mean) : '—'}</span>
        <span style="color:var(--text-dimmer);text-align:right">${r.totalW != null ? fmtHH(r.totalW) : '—'}</span>
      `).join('')}
    </div>
  `;
}

// ============================================================
// Legend — rebuild structure only on colorMode change; active state via syncLegendActive
// ============================================================
let _legendColorMode = null;

function renderLegend() {
  if (colorMode === _legendColorMode && colorMode !== 'state') {
    syncLegendActive();
    return;
  }
  _legendColorMode = colorMode;

  const container = document.getElementById('legend');
  container.innerHTML = '';

  if (colorMode === 'state') {
    // Only show entries for states that got a distinct palette color
    for (const [fips, idx] of stateColorMap) {
      if (idx >= STATE_PALETTE.length) continue;
      const color = STATE_PALETTE[idx];
      const name = codebook?.states?.[String(fips)]?.name ?? `State ${fips}`;
      const item = document.createElement('div');
      item.className = 'legend-item';
      const dot = document.createElement('div');
      dot.className = 'legend-dot';
      dot.style.background = color;
      item.append(dot, document.createTextNode(name));
      container.append(item);
    }
    // "Other" = unselected states OR selected states beyond palette capacity
    const totalStates = Object.keys(codebook?.states ?? {}).length;
    const hasOther = selectedFips.size < totalStates || selectedFips.size > STATE_PALETTE.length;
    if (hasOther) {
      const item = document.createElement('div');
      item.className = 'legend-item';
      const dot = document.createElement('div');
      dot.className = 'legend-dot';
      dot.style.background = '#888';
      item.append(dot, document.createTextNode('Other'));
      container.append(item);
    }
    return;
  }

  const palette = PALETTES[colorMode];
  const lb = codebook?.labels?.[colorMode] || {};

  if (palette) {
    const labeled = Object.keys(lb).length > 0;
    palette.forEach((color, i) => {
      if (color == null) return;
      if (labeled && lb[String(i)] == null) return;  // palette longer than the codes in this data
      const lbl = lb[String(i)] ?? String(i);
      const item = document.createElement('div');
      item.className = 'legend-item';
      item.dataset.val = i;
      item.addEventListener('click', () => {
        toggleFilter(colorMode, i);
        syncFilterButtons();
      });
      const dot = document.createElement('div');
      dot.className = 'legend-dot';
      dot.style.background = color;
      item.append(dot, document.createTextNode(lbl));
      container.append(item);
    });
  }

  const tc = document.createElement('div');
  tc.className = 'legend-item';
  tc.innerHTML = '<span class="legend-topcode" aria-hidden="true"></span> Topcoded';
  container.append(tc);

  syncLegendActive();
}

function syncLegendActive() {
  document.querySelectorAll('#legend .legend-item[data-val]').forEach(item => {
    const val = parseInt(item.dataset.val);
    item.classList.toggle('active', !!(filters[colorMode]?.has(val)));
  });
}
