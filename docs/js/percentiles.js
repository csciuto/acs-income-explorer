// American Income Explorer: percentiles.js
// The Percentiles view: household income at P1-P99 for the current place and filters, as a chart or a table. Precomputed from the full
// survey (docs/data/<src>/pct/, loaded on first use) where the stats table has the slice; otherwise from the chart's
// sample, with approximate errors (lib.js percentileTable).
// A plain script: these files share one set of globals and load in the order index.html lists them.

// every tenth plus the quartiles, then every percentile from P80 up
const PCT_KEY_ROWS = [10, 20, 25, 30, 40, 50, 60, 70, 75, ...Array.from({ length: 20 }, (_, i) => 80 + i)];
const pctFiles = {};      // file name -> {key: {v, se, tc}}, or null when it couldn't be fetched
const pctLoading = {};
let pctTab = 'chart';     // 'chart' | 'table'

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
  document.getElementById('legend').style.visibility = on ? 'hidden' : '';  // nothing here is colored by group
}

// $180k, $1.2M: the chart's labels
function fmt$Short(n) {
  if (n >= 1e6) return `$${(n / 1e6).toFixed(n >= 1e7 ? 0 : 1)}M`;
  if (n >= 1e3) return `$${Math.round(n / 1e3)}k`;
  return `$${Math.round(n)}`;
}

function renderPercentiles() {
  const el = document.getElementById('pct-view');
  showPctView(true);
  d3.select('#chart-svg').selectAll('*').remove();
  brushLayer = null;
  chartScope = null;  // force a full renderChart() on the way back to dots
  dotData = [];
  const t = getPercentiles();
  const table = pctTab === 'table';
  const head = `<div class="pct-head">
      <span class="panel-title">Household income percentiles</span>
      <span class="pct-tabs" role="group" aria-label="Show as">
        <button type="button" data-pt="chart" aria-pressed="${!table}">Chart</button><button type="button" data-pt="table" aria-pressed="${table}">Table</button>
      </span>
    </div>`;
  let body;
  const notes = [];
  el.classList.toggle('pct-chart-mode', !table && !!t.v);
  if (t.loading) body = '<p class="pct-msg">Loading…</p>';
  else if (!t.v) body = `<p class="pct-msg">⚠ Too few households (${t.n ?? 0})</p>`;
  else {
    const ks = table ? PCT_KEY_ROWS : Array.from({ length: 99 }, (_, i) => i + 1);
    if (t.live) notes.push(`≈ From the chart's sample (${t.n.toLocaleString()} households)`);
    if (t.tc && ks.some(k => k >= t.tc)) notes.push(table ? "† Near the survey's income cap" : "Dashed: near the survey's income cap");
    if (ks.some(k => t.v[k - 1] == null)) notes.push('— Too few households that far out');
    if (table) {
      const approx = t.live ? '≈' : '';
      const rows = ks.map(k => {
        const v = t.v[k - 1], se = t.se[k - 1];
        const cap = t.tc && k >= t.tc ? ' <span class="pct-cap" title="Near the survey\'s income cap">†</span>' : '';
        return `<tr><th scope="row">P${k}${k === 50 ? ' · median' : ''}</th>`
          + `<td>${v == null ? '—' : fmt$(v) + cap}</td>`
          + `<td class="pct-se">${se == null ? '' : `${approx}±${fmt$(se)}`}</td></tr>`;
      }).join('');
      body = `<table class="pct-table" aria-label="Household income percentiles">
          <thead><tr><th scope="col">Percentile</th><th scope="col">Income</th><th scope="col">± SE</th></tr></thead>
          <tbody>${rows}</tbody></table>`;
    } else {
      body = '<svg id="pct-chart" role="img" aria-label="Household income by percentile"></svg>';
    }
  }
  el.innerHTML = head + body + notes.map(n => `<p class="pct-note">${n}</p>`).join('');
  el.querySelectorAll('.pct-tabs button').forEach(b => {
    b.onclick = () => { pctTab = b.dataset.pt; pushUrl(); renderPercentiles(); };
  });
  if (!table && t.v) drawPctChart(t);
}

// Income against percentile, the ±SE band around it, a few points labelled.
function drawPctChart(t) {
  const svgEl = document.getElementById('pct-chart');
  const W = svgEl.clientWidth, H = svgEl.clientHeight;
  if (W < 50 || H < 50) return;
  const m = { l: isMobile() ? 44 : 56, r: 12, t: 18, b: 26 };
  const cw = W - m.l - m.r, ch = H - m.t - m.b;
  const pts = t.v.map((v, i) => ({ k: i + 1, v, se: t.se[i] }));
  const ok = d => d.v != null;
  const x = d3.scaleLinear().domain([1, 99]).range([0, cw]);
  const y = d3.scaleLinear().domain([0, d3.max(pts, d => (ok(d) ? d.v + (d.se ?? 0) : null))]).nice(5).range([ch, 0]);
  const g = d3.select(svgEl).append('g').attr('transform', `translate(${m.l},${m.t})`);

  const style = s => s
    .call(a => a.select('.domain').remove())
    .call(a => a.selectAll('.tick line').attr('stroke', 'var(--border)'))
    .call(a => a.selectAll('.tick text').attr('fill', 'var(--text-dim)').attr('font-size', isMobile() ? 9 : 10));
  g.append('g').attr('class', 'axis').call(d3.axisLeft(y).ticks(5).tickSize(-cw).tickFormat(fmt$Short)).call(style);
  g.append('g').attr('class', 'axis').attr('transform', `translate(0,${ch})`)
    .call(d3.axisBottom(x).tickValues(isMobile() ? [1, 20, 40, 60, 80, 99] : [1, 10, 20, 30, 40, 50, 60, 70, 80, 90, 99])
      .tickSize(4).tickFormat(d => `P${d}`))
    .call(style);

  g.append('path').datum(pts).attr('class', 'pct-band')
    .attr('d', d3.area().defined(d => ok(d) && d.se != null).x(d => x(d.k))
      .y0(d => y(Math.max(0, d.v - d.se))).y1(d => y(d.v + d.se)));
  const line = d3.line().defined(ok).x(d => x(d.k)).y(d => y(d.v));
  const tc = t.tc || 100;
  g.append('path').datum(pts.filter(d => d.k <= tc)).attr('class', 'pct-line').attr('d', line);
  if (tc < 100) g.append('path').datum(pts.filter(d => d.k >= tc)).attr('class', 'pct-line pct-line-cap').attr('d', line);

  for (const k of [50, 80, 90, 95, 99]) {
    const d = pts[k - 1];
    if (!ok(d)) continue;
    g.append('circle').attr('class', 'pct-mark').attr('cx', x(k)).attr('cy', y(d.v)).attr('r', 3.5);
    g.append('text').attr('class', 'pct-label').attr('x', x(k) - 6).attr('y', y(d.v) - 6)
      .attr('text-anchor', 'end').text(`P${k} ${fmt$Short(d.v)}`);
  }

  // hover or tap: the nearest percentile, and past P80 how many times P80 it is
  const guide = g.append('line').attr('class', 'pct-guide').attr('y2', ch).style('display', 'none');
  const dot = g.append('circle').attr('class', 'pct-mark').attr('r', 4.5).style('display', 'none');
  const p80 = pts[79].v;
  const hide = () => { guide.style('display', 'none'); dot.style('display', 'none'); hideTooltip(); };
  const show = event => {
    const k = Math.max(1, Math.min(99, Math.round(x.invert(d3.pointer(event, g.node())[0]))));
    const d = pts[k - 1];
    if (!ok(d)) { hide(); return; }
    guide.attr('x1', x(k)).attr('x2', x(k)).style('display', null);
    dot.attr('cx', x(k)).attr('cy', y(d.v)).style('display', null);
    const tt = document.getElementById('tooltip');
    const se = d.se == null ? '' : ` ${t.live ? '≈' : ''}±${fmt$(d.se)}`;
    tt.innerHTML = `<div class="tt-income">P${k}${k === 50 ? ' · median' : ''}</div>`
      + `<div>${fmt$(d.v)}<span class="tt-dim">${se}</span></div>`
      + (k > 80 && p80 ? `<div class="tt-dim">×${(d.v / p80).toFixed(2)} P80</div>` : '')
      + (k >= tc ? '<div class="tt-dim">Near the income cap</div>' : '');
    tt.style.display = 'block';
    moveTooltip(event);
  };
  g.append('rect').attr('class', 'pct-hit').attr('width', cw).attr('height', ch).attr('fill', 'transparent')
    .style('touch-action', 'pan-y')
    .on('pointermove', show).on('pointerdown', show).on('pointerleave', hide);
}
