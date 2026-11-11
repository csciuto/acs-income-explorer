// American Income Explorer: controls.js
// The controls: filter buttons, chips, color mode, tabs, toolbar, the mobile drawer.
// A plain script: these files share one set of globals and load in the order index.html lists them.

// ============================================================
// Filter UI
// ============================================================
const FILTER_DEFS = [
  { id: 'f-age_bucket', dim: 'age_bucket' },
  { id: 'f-sex', dim: 'sex' },
  { id: 'f-marst', dim: 'marst' },
  { id: 'f-has_roommate', dim: 'has_roommate' },
  { id: 'f-educ', dim: 'educ' },
  { id: 'f-race_ethnicity', dim: 'race_ethnicity' },
  { id: 'f-kids', dim: 'kids' },
  { id: 'f-city', dim: 'city' },
  { id: 'f-work_status', dim: 'work_status' },
  { id: 'f-earner_count', dim: 'earner_count' },
  { id: 'f-breadwinner', dim: 'breadwinner' },
  { id: 'f-passive_pct', dim: 'passive_pct' },
  { id: 'f-passive_source', dim: 'passive_source' },
  { id: 'f-year', dim: 'year' },
  { id: 'f-housing', dim: 'housing' },
  { id: 'f-burden', dim: 'burden' },
  { id: 'f-multi_job_proxy', dim: 'multi_job_proxy' },
];

function buildFilterUI() {
  for (const { id, dim } of FILTER_DEFS) {
    const container = document.getElementById(id);
    if (!container) continue;
    const lb = codebook?.labels?.[dim];
    if (!lb) continue;
    container.innerHTML = '';
    for (const [val, lbl] of Object.entries(lb)) {
      const btn = document.createElement('button');
      btn.className = 'f-btn';
      btn.dataset.dim = dim;
      btn.dataset.val = val;
      btn.textContent = lbl;
      btn.addEventListener('click', () => toggleFilter(dim, parseInt(val)));
      container.append(btn);
    }
  }
}

// Tri-state filter: no filter→exclusive, sole active→clear, active-in-multi→exclusive, inactive→add
function toggleFilter(dim, val) {
  const cur = filters[dim];
  if (!cur || cur.size === 0) {
    filters[dim] = new Set([val]);
  } else if (cur.size === 1 && cur.has(val)) {
    delete filters[dim];
  } else if (cur.has(val)) {
    filters[dim] = new Set([val]);
  } else {
    cur.add(val);
  }
  render();
}

function syncFilterButtons() {
  document.querySelectorAll('.f-btn').forEach(btn => {
    const dim = btn.dataset.dim;
    const val = parseInt(btn.dataset.val);
    btn.classList.toggle('active', !!(filters[dim] && filters[dim].has(val)));
  });
}

// ============================================================
// Active chips
// ============================================================
const DIM_LABELS = {
  age_bucket: 'Age', sex: 'Sex', marst: 'Marital', educ: 'Educ', has_roommate: 'Roommates',
  work_status: 'Work', race_ethnicity: 'Race',
  kids: 'Kids', city: 'Area type', region: 'Region', metro: 'Metro', metro_area: 'Metro area', puma: 'Local area', burden: 'Cost burden', multi_job_proxy: '2nd job',
  housing: 'Housing', year: 'Year',
  earner_count: 'Earners', breadwinner: "Householder's share",
  passive_pct: 'Earnings share', passive_source: 'Unearned src',
};

function renderActiveChips() {
  const container = document.getElementById('active-chips');
  container.innerHTML = '';

  // Brush range chip
  if (brushRange) {
    const chip = document.createElement('div');
    chip.className = 'chip';
    chip.innerHTML = `<span>Range: ${fmt$(brushRange.lo)} – ${fmt$(brushRange.hi)}</span><span class="x">✕</span>`;
    chip.addEventListener('click', () => {
      brushRange = null;
      if (brushLayer) brushLayer.call(d3brush.move, null);
      updateDotOpacity();
      renderBrushInfo();
      renderActiveChips();
      switchStatsTab('summary');
      pushUrl();
    });
    container.append(chip);
  }

  // State chips
  for (const fips of selectedFips) {
    const name = codebook?.states?.[String(fips)]?.name ?? `State ${fips}`;
    const chip = document.createElement('div');
    chip.className = 'chip';
    chip.innerHTML = `<span>State: ${name}</span><span class="x">✕</span>`;
    chip.addEventListener('click', () => {
      setPlace('us');
    });
    container.append(chip);
  }

  // Filter chips
  for (const [dim, vals] of Object.entries(filters)) {
    if (!vals || vals.size === 0) continue;
    for (const val of vals) {
      const chip = document.createElement('div');
      chip.className = 'chip';
      chip.innerHTML = `<span>${DIM_LABELS[dim] ?? dim}: ${label(dim, val)}</span><span class="x">✕</span>`;
      chip.addEventListener('click', () => {
        filters[dim].delete(val);
        if (filters[dim].size === 0) delete filters[dim];
        syncFilterButtons();
        render();
      });
      container.append(chip);
    }
  }
}








// ============================================================
// Color mode
// ============================================================
document.querySelectorAll('.cm-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.cm-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    colorMode = btn.dataset.mode;
    _legendColorMode = null;  // force full legend rebuild
    if (viewMode === 'bars' || viewMode === 'pct') renderStackedBars();
    else updateDotColors();
    renderLegend();
    renderGroupBreakdown();
    renderBrushInfo();
    pushUrl();
  });
});

// ============================================================
// Tabs
// ============================================================
document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById('tab-' + btn.dataset.tab).classList.add('active');
  });
});

let breakdownExpanded = false;
document.getElementById('btn-expand-breakdown').addEventListener('click', () => {
  breakdownExpanded = !breakdownExpanded;
  document.getElementById('stats-detail').style.maxHeight = breakdownExpanded ? 'none' : '';
  document.getElementById('btn-expand-breakdown').textContent = breakdownExpanded ? 'By group ▴' : 'By group ▾';
});

let rangeBreakdownExpanded = false;
document.getElementById('btn-expand-range').addEventListener('click', () => {
  rangeBreakdownExpanded = !rangeBreakdownExpanded;
  document.getElementById('range-breakdown').style.display = rangeBreakdownExpanded ? '' : 'none';
  document.getElementById('btn-expand-range').textContent = rangeBreakdownExpanded ? 'By group ▴' : 'By group ▾';
});

function switchStatsTab(name) {
  document.querySelectorAll('.stats-tab-btn').forEach(b => b.classList.toggle('active', b.dataset.statsTab === name));
  document.querySelectorAll('.stats-tab-panel').forEach(p => p.classList.remove('active'));
  document.getElementById('stats-' + name).classList.add('active');
}

document.querySelectorAll('.stats-tab-btn').forEach(btn => {
  btn.addEventListener('click', () => switchStatsTab(btn.dataset.statsTab));
});


// ============================================================
// Clear all
// ============================================================
document.getElementById('btn-brush').addEventListener('click', () => {
  if (brushRange) {
    // Clear existing selection
    brushRange = null;
    brushModeActive = false;
    document.getElementById('btn-brush').classList.remove('active');
    if (brushLayer) brushLayer.call(d3brush.move, null);
    updateDotOpacity();
    renderBrushInfo();
    renderActiveChips();
    switchStatsTab('summary');
    pushUrl();
  } else {
    // Enter brush mode
    brushModeActive = true;
    document.getElementById('btn-brush').classList.add('active');
    if (brushLayer) brushLayer.select('.overlay').attr('pointer-events', 'all');
  }
});

document.getElementById('btn-clear').addEventListener('click', () => {
  filters = {};
  selectedFips.clear();
  brushRange = null;
  brushModeActive = false;
  document.getElementById('btn-brush').classList.remove('active');
  if (brushLayer) brushLayer.call(d3brush.move, null);
  switchStatsTab('summary');
  updateStateColorMap();
  syncFilterButtons();
  render();
});

// View toggle (Dots / Bars / 100%)
document.querySelectorAll('.view-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    viewMode = btn.dataset.view;
    document.querySelectorAll('.view-btn').forEach(b => b.classList.toggle('active', b === btn));
    render();
  });
});

// Dot count (1K / 3K / 5K)
document.querySelectorAll('.dots-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    maxDots = parseInt(btn.dataset.maxdots);
    document.querySelectorAll('.dots-btn').forEach(b => b.classList.toggle('active', b === btn));
    chartScope = null;  // force full re-render with new limit
    render();
  });
});

// Dim others / Matches only toggle
document.getElementById('btn-static').addEventListener('click', () => {
  if (sampleMode) return;
  sampleMode = true;
  chartScope = null;  // re-render from full row pool
  syncSampleButtons();
  render();
});
document.getElementById('btn-showall').addEventListener('click', () => {
  if (!sampleMode) return;
  sampleMode = false;
  syncSampleButtons();
  render();
});

// ============================================================
// Mobile sidebar drawer
// ============================================================
function openSidebar() {
  document.getElementById('sidebar').classList.add('open');
  document.getElementById('sidebar-backdrop').classList.add('open');
}
function closeSidebar() {
  document.getElementById('sidebar').classList.remove('open');
  document.getElementById('sidebar-backdrop').classList.remove('open');
}
document.getElementById('btn-filters').addEventListener('click', openSidebar);
document.getElementById('btn-close-sidebar').addEventListener('click', closeSidebar);
document.getElementById('sidebar-backdrop').addEventListener('click', closeSidebar);

document.getElementById('btn-about').addEventListener('click', () => {
  const panel = document.getElementById('chart-about');
  const open = panel.style.display !== 'none' && panel.style.display !== '';
  panel.style.display = open ? 'none' : 'block';
});

// Dismiss tooltip on tap of chart background
document.getElementById('chart-wrap').addEventListener('touchstart', (e) => {
  const tag = e.target.tagName.toLowerCase();
  if (tag === 'svg' || tag === 'path' || tag === 'line' || tag === 'text' || tag === 'g') {
    hideTooltip();
  }
}, { passive: true });
