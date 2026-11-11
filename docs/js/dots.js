// American Income Explorer: dots.js
// Dot colors, and how many dots are drawn.
// A plain script: these files share one set of globals and load in the order index.html lists them.

// ============================================================
// Dot color
// ============================================================
function dotColor(i, cols, palette) {
  if (colorMode === 'state') {
    const fips = cols.state[i];
    const idx = stateColorMap.get(fips);
    return (idx != null && idx < STATE_PALETTE.length) ? STATE_PALETTE[idx] : '#888';
  }
  if (!cols[colorMode]) return '#888';
  const v = cols[colorMode][i];
  return palette[v] ?? '#888';
}

// Topcoded households keep their group color and get a thin light-grey outline, so the mark doesn't compete
// with the palette (several palettes use yellow).
const TOPCODE_RING = '#d8dce3';

function updateDotColors() {
  const cols = currentCols();
  const palette = PALETTES[colorMode] || PALETTES.passive_pct;
  d3.select('#chart-svg').selectAll('circle:not(.pin-ring)')
    .attr('fill', d => dotColor(d.i, cols, palette))
    .attr('stroke', d => d.topcode ? TOPCODE_RING : dotColor(d.i, cols, palette));
}

// ============================================================
// Subsample — partial Fisher-Yates shuffle
// ============================================================
function updateDotCountDisplay() {
  const el = document.getElementById('dot-count');
  const cap = document.getElementById('chart-caption');
  if (cap) cap.hidden = viewMode !== 'dots';
  if (!el || viewMode !== 'dots') { if (el) el.textContent = ''; return; }
  const total = visibleRows.length;
  const shown = dotData.length;
  el.textContent = shown < total ? `${shown.toLocaleString()} of ${total.toLocaleString()} households` : '';
  syncDotCapButtons();
}

// A bigger cap changes nothing once a smaller one already draws every household in the pool.
function syncDotCapButtons() {
  const caps = [...document.querySelectorAll('.dots-btn')].map(b => parseInt(b.dataset.maxdots)).sort((a, b) => a - b);
  const enough = caps.find(c => c >= lastPoolSize) ?? Infinity;
  document.querySelectorAll('.dots-btn').forEach(b => {
    const v = parseInt(b.dataset.maxdots);
    const idle = v > enough;
    b.classList.toggle('idle', idle);
    b.title = idle ? `Only ${lastPoolSize.toLocaleString()} households to draw; ${enough.toLocaleString()} already shows them all` : `Draw up to ${v.toLocaleString()} dots`;
  });
}

function syncSampleButtons() {
  document.getElementById('btn-static').classList.toggle('active', sampleMode);
  document.getElementById('btn-showall').classList.toggle('active', !sampleMode);
}
