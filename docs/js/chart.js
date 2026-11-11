// American Income Explorer: chart.js
// The dot chart and its brush.
// A plain script: these files share one set of globals and load in the order index.html lists them.

// ============================================================
// Dot chart
function renderMobileStats(stats) {
  const el = document.getElementById('mobile-stats');
  if (!el) return;
  if (!stats || stats.rel === 0) {
    el.innerHTML = '<span style="color:var(--text-dim);font-size:11px">Insufficient data</span>';
    return;
  }
  el.innerHTML = `
    <div class="mstat"><span class="mstat-label">Median</span><span class="mstat-val">${fmt$(stats.med)}</span></div>
    <div class="mstat"><span class="mstat-label">Mean</span><span class="mstat-val">${fmt$(stats.mean)}</span></div>
    <div class="mstat"><span class="mstat-label">HH</span><span class="mstat-val">~${fmtHH(stats.n_rep)}</span></div>
    <div class="mstat"><span class="mstat-label">Records</span><span class="mstat-val">${stats.n.toLocaleString()}</span></div>
  `;
}

function render() {
  visibleRows = computeVisibleRows();
  const stats = getStats();
  renderStats(stats);
  renderMobileStats(stats);
  const scope = computeScope();
  if (viewMode === 'bars' || viewMode === 'pct') {
    renderStackedBars();
  } else if (!sampleMode || scope !== chartScope || dotData.length === 0) {
    renderChart();
  } else {
    updateDotOpacity();
  }
  syncPin();
  syncFilterButtons();
  syncPlace();
  renderPlaceContext(stats);
  renderActiveChips();
  renderBrushInfo();
  renderLegend();
  renderGroupBreakdown();
  pushUrl();
}

function renderChart() {
  const svg = document.getElementById('chart-svg');
  const W = svg.clientWidth || svg.parentElement.clientWidth;
  const H = svg.clientHeight || svg.parentElement.clientHeight;
  if (W < 10 || H < 10) return;

  chartScope = computeScope();

  const marginL = 60, marginR = 20, marginT = 20, marginB = 40;
  const chartW = W - marginL - marginR;
  const chartH = H - marginT - marginB;

  const cols = currentCols();
  const mobileMax = Math.min(maxDots, 800);
  const limit = isMobile() ? mobileMax : maxDots;
  // Dim-others mode samples every household, dimming non-matches; a chosen metro area narrows the pool to it
  const metroSel = filters.metro_area && filters.metro_area.size ? filters.metro_area : null;
  const localSel = filters.puma && filters.puma.size ? filters.puma : null;
  const all = Array.from({length: cols.inc.length}, (_, i) => i);
  const rowPool = sampleMode
    ? (localSel ? all.filter(i => localSel.has(cols.puma[i]))
       : metroSel ? all.filter(i => metroSel.has(cols.metro_area[i])) : all)
    : visibleRows;
  lastPoolSize = rowPool.length;
  const dotRows = subsample(rowPool, limit);
  // A redraw (resize, place change) resamples; keep a pinned household if it's still in the pool
  if (pinnedRow != null && !dotRows.includes(pinnedRow) && rowPool.includes(pinnedRow)) {
    if (dotRows.length >= limit) dotRows.pop();
    dotRows.push(pinnedRow);
  }
  const hasFilters = selectedFips.size > 0 || Object.values(filters).some(s => s && s.size > 0);

  d3.select(svg).selectAll('*').remove();

  const xScale = d3.scaleLog()
    .domain([1000, 2500000])
    .range([0, chartW])
    .clamp(true);

  const medWeight = d3.median(dotRows, i => cols.weight[i]) || 1;
  const rScale = isMobile()
    ? w => Math.max(3, Math.min(10, (w / medWeight) * 5))
    : w => Math.max(2, Math.min(8,  (w / medWeight) * 4));

  const BIN_PX = 8;
  const binScale = d3.scaleLog().domain([1000, 2500000]).range([0, chartW / BIN_PX]);
  const bins = {};
  const placed = dotRows.map(i => {
    const inc = Math.max(1000, cols.inc[i]);
    const bx = Math.round(binScale(inc));
    if (!bins[bx]) bins[bx] = 0;
    return {i, inc, slot: bins[bx]++};
  });
  // Squeeze every column by the same factor so the tallest one fits the chart; the shape stays true
  const tallest = Math.max(1, ...Object.values(bins));
  const step = Math.min(BIN_PX - 1, (chartH / 2 - 6) / Math.ceil(tallest / 2));
  dotData = placed.map(({i, inc, slot}) => {
    const jitter = (slot % 2 === 0 ? 1 : -1) * Math.ceil(slot / 2) * step;
    return {
      i,
      x: xScale(inc) + marginL,
      y: chartH / 2 + jitter + marginT,
      r: rScale(cols.weight[i]),
      topcode: cols.topcoded[i] === 1,
    };
  });

  const svgEl = d3.select(svg);
  const palette = PALETTES[colorMode] || PALETTES.passive_pct;

  // X axis
  const gAxis = svgEl.append('g')
    .attr('transform', `translate(${marginL},${marginT + chartH})`);
  const dotTickValues = isMobile()
    ? [10000, 50000, 100000, 500000, 2000000]
    : [5000, 10000, 25000, 50000, 100000, 250000, 500000, 1000000];
  gAxis.call(
    d3.axisBottom(xScale)
      .tickValues(dotTickValues)
      .tickFormat(d => d >= 1e6 ? `$${d/1e6}M` : d >= 1e3 ? `$${d/1e3}k` : `$${d}`)
  )
  .selectAll('text').style('fill', '#8892b0').style('font-size', isMobile() ? '10px' : '11px');
  gAxis.selectAll('line,path').style('stroke', '#2e3350');

  // Gridlines
  const gGrid = svgEl.append('g').attr('transform', `translate(${marginL},${marginT})`);
  gGrid.call(
    d3.axisLeft(d3.scaleLinear().domain([0,1]).range([chartH, 0]))
      .tickSize(-chartW).tickValues([])
  )
  .select('.domain').remove();


  // Dots
  svgEl.append('g')
    .selectAll('circle')
    .data(dotData)
    .join('circle')
      .attr('cx', d => d.x)
      .attr('cy', d => d.y)
      .attr('r', d => d.r)
      .attr('fill', d => dotColor(d.i, cols, palette))
      .attr('stroke', d => d.topcode ? TOPCODE_RING : dotColor(d.i, cols, palette))
      .attr('stroke-width', d => d.topcode ? 1.2 : 0.5)
      .attr('opacity', d => isDimmed(d.i, cols, hasFilters) ? 0.12 : 0.75)
      .attr('pointer-events', d => isDimmed(d.i, cols, hasFilters) ? 'none' : 'all')
      .on('mouseover', (event, d) => { if (d.i !== pinnedRow) showTooltip(event, d.i); })
      .on('mousemove', moveTooltip)
      .on('mouseout', hideTooltip)
      .on('click', (event, d) => { event.stopPropagation(); pinRow(d.i); })
      .on('touchstart', (event, d) => { event.preventDefault(); pinRow(d.i); }, {passive: false});

  attachBrushLayer(svgEl, xScale, marginL, marginT, chartW, chartH);
  syncPin();
  updateDotCountDisplay();
}

function attachBrushLayer(svgEl, xScale, marginL, marginT, chartW, chartH) {
  d3brush = d3.brushX()
    .extent([[0, 0], [chartW, chartH]])
    .on('brush', function(event) {
      if (!event.selection) return;
      const [x0, x1] = event.selection;
      const lo = Math.round(xScale.invert(x0));
      const hi = Math.round(xScale.invert(x1));
      renderBrushInfo({lo, hi});
      switchStatsTab('range');
    })
    .on('end', function(event) {
      if (!event.selection) {
        brushModeActive = false;
        document.getElementById('btn-brush').classList.remove('active');
        brushLayer.select('.overlay').attr('pointer-events', 'none');
        return;
      }
      const [x0, x1] = event.selection;
      brushRange = {lo: Math.round(xScale.invert(x0)), hi: Math.round(xScale.invert(x1))};
      brushModeActive = false;
      document.getElementById('btn-brush').classList.remove('active');
      brushLayer.select('.overlay').attr('pointer-events', 'none');
      updateDotOpacity();
      renderBrushInfo();
      renderActiveChips();
      switchStatsTab('range');
      pushUrl();
    });

  brushLayer = svgEl.append('g')
    .attr('class', 'brush-layer')
    .attr('transform', `translate(${marginL},${marginT})`)
    .call(d3brush);

  if (brushRange) {
    const x0 = xScale(Math.max(1000, brushRange.lo));
    const x1 = xScale(Math.min(2500000, brushRange.hi));
    brushLayer.call(d3brush.move, [x0, x1]);
  }
  brushLayer.select('.overlay').attr('pointer-events', brushModeActive ? 'all' : 'none');
}
