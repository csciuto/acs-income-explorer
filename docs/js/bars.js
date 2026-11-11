// American Income Explorer: bars.js
// The stacked bars and 100% views.
// A plain script: these files share one set of globals and load in the order index.html lists them.

// ============================================================
// Stacked bars view
// ============================================================
function renderStackedBars() {
  const svg = document.getElementById('chart-svg');
  const W = svg.clientWidth || svg.parentElement.clientWidth;
  const H = svg.clientHeight || svg.parentElement.clientHeight;
  if (W < 10 || H < 10) return;

  d3.select(svg).selectAll('*').remove();
  brushLayer = null;
  chartScope = null;  // force full renderChart() if we switch back to dots

  const marginL = 60, marginR = 20, marginT = 20, marginB = 40;
  const chartW = W - marginL - marginR;
  const chartH = H - marginT - marginB;

  const xScale = d3.scaleLog()
    .domain([1000, 2500000])
    .range([0, chartW])
    .clamp(true);

  const NUM_BINS = isMobile() ? 40 : 60;
  const binEdges = d3.range(NUM_BINS + 1).map(k =>
    xScale.invert(k * chartW / NUM_BINS)
  );

  const cols = currentCols();
  const palette = PALETTES[colorMode] || [];
  const colName = colorMode === 'state' ? 'state' : colorMode;

  // Build per-bin stacks from visibleRows (weighted)
  const bins = Array.from({length: NUM_BINS}, () => new Map());
  for (const i of visibleRows) {
    const inc = Math.max(1000, cols.inc[i]);
    const bx = xScale(inc);
    const b = Math.min(NUM_BINS - 1, Math.floor(bx / (chartW / NUM_BINS)));
    const key = cols[colName] != null ? cols[colName][i] : 0;
    const w = cols.weight[i];
    bins[b].set(key, (bins[b].get(key) || 0) + w);
  }

  const isPct = viewMode === 'pct';

  // Max total weight across bins (for y-scale in absolute mode)
  const maxTotal = d3.max(bins, b => d3.sum(b.values())) || 1;

  const yScale = isPct
    ? d3.scaleLinear().domain([0, 1]).range([chartH, 0])
    : d3.scaleLinear().domain([0, maxTotal]).range([chartH, 0]);
  const barW = Math.max(1, chartW / NUM_BINS - 1);

  const svgEl = d3.select(svg);

  // X axis
  const barTickValues = isMobile()
    ? [10000, 50000, 100000, 500000, 2000000]
    : [5000, 10000, 25000, 50000, 100000, 250000, 500000, 1000000, 2000000];
  const xAxis = d3.axisBottom(xScale)
    .tickValues(barTickValues)
    .tickFormat(d => d >= 1000000 ? `$${d/1000000}M` : `$${d/1000}k`);

  svgEl.append('g')
    .attr('class', 'axis')
    .attr('transform', `translate(${marginL},${marginT + chartH})`)
    .call(xAxis)
    .call(g => g.select('.domain').attr('stroke', 'var(--border)'))
    .call(g => g.selectAll('.tick line').attr('stroke', 'var(--border)'))
    .call(g => g.selectAll('.tick text').attr('fill', 'var(--text-dim)').attr('font-size', isMobile() ? 9 : 10));

  // Y axis
  const yAxis = isPct
    ? d3.axisLeft(yScale).ticks(5).tickFormat(d => `${Math.round(d * 100)}%`)
    : d3.axisLeft(yScale).ticks(5).tickFormat(fmtHH);

  svgEl.append('g')
    .attr('class', 'axis')
    .attr('transform', `translate(${marginL},${marginT})`)
    .call(yAxis)
    .call(g => g.select('.domain').attr('stroke', 'var(--border)'))
    .call(g => g.selectAll('.tick line').attr('stroke', 'var(--border)'))
    .call(g => g.selectAll('.tick text').attr('fill', 'var(--text-dim)').attr('font-size', 10));

  // Draw stacked bars
  const g = svgEl.append('g').attr('transform', `translate(${marginL},${marginT})`);

  bins.forEach((binMap, b) => {
    if (binMap.size === 0) return;
    const x = b * (chartW / NUM_BINS);
    const total = d3.sum(binMap.values());
    let y = chartH;
    // Sort keys for consistent stacking order
    const keys = [...binMap.keys()].sort((a, z) => a - z);
    const loInc = fmt$(Math.round(binEdges[b]));
    const hiInc = fmt$(Math.round(binEdges[b + 1]));
    for (const key of keys) {
      const segW = binMap.get(key);
      const segH = isPct
        ? (segW / total) * chartH
        : (segW / maxTotal) * chartH;
      y -= segH;
      let color = '#888';
      if (colorMode === 'state') {
        const idx = stateColorMap.get(key);
        color = idx != null && idx < STATE_PALETTE.length ? STATE_PALETTE[idx] : '#888';
      } else if (palette[key] != null) {
        color = palette[key];
      }
      const catLabel = colName === 'state'
        ? (codebook?.states?.[String(key)]?.name ?? `State ${key}`)
        : label(colName, key);
      const pct = total > 0 ? (segW / total * 100).toFixed(1) : '0.0';
      g.append('rect')
        .attr('x', x)
        .attr('y', y)
        .attr('width', barW)
        .attr('height', segH)
        .attr('fill', color)
        .attr('opacity', 0.85)
        .style('cursor', 'pointer')
        .on('mouseover', (event) => {
          const tt = document.getElementById('tooltip');
          tt.innerHTML = `
            <div class="tt-income">${loInc} – ${hiInc}</div>
            <div class="tt-dim">${catLabel}</div>
            <div class="tt-dim">${fmtHH(segW)} households · ${pct}% of band</div>
          `;
          tt.style.display = 'block';
          moveTooltip(event);
        })
        .on('mousemove', moveTooltip)
        .on('mouseout', hideTooltip)
        .on('touchstart', (event) => {
          event.preventDefault();
          const tt = document.getElementById('tooltip');
          tt.innerHTML = `
            <div class="tt-income">${loInc} – ${hiInc}</div>
            <div class="tt-dim">${catLabel}</div>
            <div class="tt-dim">${fmtHH(segW)} households · ${pct}% of band</div>
          `;
          tt.style.display = 'block';
        }, {passive: false});
    }
  });

  attachBrushLayer(svgEl, xScale, marginL, marginT, chartW, chartH);
}
