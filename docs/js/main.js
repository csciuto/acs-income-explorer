// American Income Explorer: main.js
// Start-up: redraw on resize, the loading notice, and the first load.
// A plain script: these files share one set of globals and load in the order index.html lists them.

// ============================================================
// Resize
// ============================================================
const ro = new ResizeObserver(() => {
  if (!nationalTable) return;  // it fires once on load, before the data has arrived
  if (viewMode === 'bars' || viewMode === 'pct') renderStackedBars();
  else renderChart();
});
ro.observe(document.getElementById('chart-wrap'));

// ============================================================
// Loading overlay
// ============================================================
function setLoading(msg) {
  document.getElementById('loading').style.display = 'flex';
  document.getElementById('loading-msg').textContent = msg;
}
function hideLoading() {
  document.getElementById('loading').style.display = 'none';
  for (const id of WAITING) document.getElementById(id)?.removeAttribute('inert');
}

// ============================================================
// Boot
// ============================================================
init().catch(err => {
  setLoading(`Error: ${err.message}`);
  console.error(err);
});
