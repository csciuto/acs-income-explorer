// American Income Explorer: percentiles.js
// The Percentiles view: household income at P1-P99 for the current place and filters, as a chart or a table;
// one line for everyone who matches (Combined) or one per group of the Group tab (By group). Dim others adds the
// place's households with no filters as a gray reference. Precomputed from the full survey (docs/data/<src>/pct/,
// loaded on first use) where the stats table has the slice; otherwise from the chart's sample, with approximate
// errors (lib.js percentileTable).
// A plain script: these files share one set of globals and load in the order index.html lists them.

const PCT_TABLE_ROWS = [10, 20, 30, 40, 50, 60, 70, 80, 85, 90, 95, 99];
const PCT_LABELS = [50, 80, 90, 95, 99];   // points labelled on the Combined chart
const PCT_REF_COLOR = '#5d6584';
const pctFiles = {};      // file name -> {key: {v, se, tc}}, or null when it couldn't be fetched
const pctLoading = {};
let pctTab = 'chart';     // 'chart' | 'table'
let pctSplit = 'all';     // 'all' (Combined) | 'group' (By group)
let pctPrev = null;       // the last chart drawn: {domain, lines: {key: v[]}}, for the slide to the next one

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

// Percentiles for one slice: {v, se, tc, live, n}; {loading: true} while its file is on the way; {n} when too few.
// dimFilter is the slice as a stats key (null when it has none); rows are its households in the chart's sample.
function pctFor(p, dimFilter, rows) {
  // precomputed: the slices the stats table holds; for a local area, only the area as a whole
  const cell = dimFilter && placeCell(p, dimFilter);
  if (cell && (p.level !== 'puma' || !Object.keys(dimFilter).length)) {
    const key = placeKey(p, dimFilter);
    const file = pctFileFor(key);
    if (!(file in pctFiles)) {
      loadPctFile(file).then(() => { if (viewMode === 'ptile') renderPercentiles(); });
      return { loading: true };
    }
    const hit = pctFiles[file]?.[key];
    if (hit) return { ...hit, live: false, n: cell.n };
  }
  if (!rows) return { n: 0 };
  const cols = currentCols();
  const t = percentileTable(rows.map(i => cols.inc[i]), rows.map(i => cols.weight[i]),
                            cols.topcoded ? rows.map(i => cols.topcoded[i]) : null);
  return t ? { ...t, live: true, n: rows.length } : { n: rows.length };
}

// The household filters with the Group tab's dimension set to one group, as a stats key; null when another filter
// has several values or the dimension isn't in the stats table.
function groupDimFilter(colName, g) {
  const kd = DIM_TO_KEY[colName];
  if (!kd) return null;
  const out = {};
  for (const [dim, vals] of Object.entries(filters)) {
    if (!vals || vals.size === 0 || GEO_FILTERS.has(dim) || dim === colName) continue;
    if (vals.size > 1) return null;
    out[DIM_TO_KEY[dim] ?? dim] = [...vals][0];
  }
  out[kd] = g;
  return out;
}

function groupColor(g) {
  if (colorMode === 'state') {
    const idx = stateColorMap.get(g);
    return idx != null && idx < STATE_PALETTE.length ? STATE_PALETTE[idx] : '#888';
  }
  return (PALETTES[colorMode] || [])[g] ?? '#888';
}

function hasHouseholdFilter() {
  return Object.entries(filters).some(([dim, vals]) => vals && vals.size > 0 && !GEO_FILTERS.has(dim));
}

// What to draw: the lines ({key, name, color, t}), the gray reference (or null), groups too small to draw.
function pctSeries() {
  const p = currentPlace();
  const ref = sampleMode && hasHouseholdFilter() ? pctFor(p, {}, null) : null;
  if (pctSplit !== 'group') {
    const t = pctFor(p, householdFilterKey(), visibleRows);
    return { lines: [{ key: 'all', name: 'Matching households', color: 'var(--accent)', t }], ref, small: [] };
  }
  const cols = currentCols();
  const colName = colorMode === 'state' ? 'state' : colorMode;
  const byGroup = new Map();
  for (const i of visibleRows) {
    const g = cols[colName] != null ? cols[colName][i] : 0;
    if (!byGroup.has(g)) byGroup.set(g, []);
    byGroup.get(g).push(i);
  }
  const lines = [], small = [];
  for (const g of [...byGroup.keys()].sort((a, b) => a - b)) {
    const name = colName === 'state' ? (codebook?.states?.[String(g)]?.name ?? `State ${g}`) : label(colName, g);
    const t = pctFor(p, groupDimFilter(colName, g), byGroup.get(g));
    if (t.loading || t.v) lines.push({ key: `g${g}`, name, color: groupColor(g), t });
    else small.push(name);
  }
  return { lines, ref, small };
}

function showPctView(on) {
  document.getElementById('chart-svg').style.display = on ? 'none' : '';
  document.getElementById('pct-view').hidden = !on;
  // the legend names the lines By group; Combined colors nothing by group
  const legend = document.getElementById('legend');
  legend.style.visibility = on && pctSplit !== 'group' ? 'hidden' : '';
  legend.classList.toggle('in-ptile', on);
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
  const s = pctSeries();
  const table = pctTab === 'table';
  const head = '<div class="pct-head"><span class="panel-title">Household income percentiles</span></div>';
  const loading = s.lines.some(l => l.t.loading) || s.ref?.loading;
  const lines = s.lines.filter(l => l.t.v);
  const ref = s.ref?.v ? s.ref : null;
  const all = [...lines.map(l => l.t), ...(ref ? [ref] : [])];
  let body = '';
  const notes = [];
  el.classList.toggle('pct-chart-mode', !table && !loading && lines.length > 0);
  if (loading) body = '<p class="pct-msg">Loading…</p>';
  else if (!lines.length) body = `<p class="pct-msg">⚠ Too few households (${s.lines[0]?.t.n ?? 0})</p>`;
  else {
    const ks = table ? PCT_TABLE_ROWS : Array.from({ length: 99 }, (_, i) => i + 1);
    if (lines.some(l => l.t.live)) {
      notes.push(pctSplit === 'group' ? "≈ From the chart's sample"
                                      : `≈ From the chart's sample (${lines[0].t.n.toLocaleString()} households)`);
    }
    if (ref && !table) notes.push(`Gray: all households in ${placeName(currentPlace())}`);
    if (all.some(t => t.tc && ks.some(k => k >= t.tc))) {
      notes.push(table ? "† Near the survey's income cap" : "Dashed: near the survey's income cap");
    }
    if (all.some(t => ks.some(k => t.v[k - 1] == null))) notes.push('— Too few households that far out');
    if (s.small.length) notes.push(`Too few households: ${s.small.join(', ')}`);
    body = table ? pctTableHtml(lines, ref) : '<svg id="pct-chart" role="img" aria-label="Household income by percentile"></svg>';
  }
  el.innerHTML = head + body + notes.map(n => `<p class="pct-note">${n}</p>`).join('');
  if (!table && !loading && lines.length) drawPctChart(lines, ref);
}

function pctCell(t, k) {
  const v = t.v[k - 1], se = t.se[k - 1];
  if (v == null) return null;
  const cap = t.tc && k >= t.tc ? ' <span class="pct-cap" title="Near the survey\'s income cap">†</span>' : '';
  return { v: fmt$(v) + cap, se: se == null ? '' : `${t.live ? '≈' : ''}±${fmt$(se)}` };
}

function pctTableHtml(lines, ref) {
  const cols = [...lines, ...(ref ? [{ name: 'All households', color: PCT_REF_COLOR, t: ref }] : [])];
  const single = cols.length === 1;
  const headCells = single
    ? '<th scope="col">Income</th><th scope="col">± SE</th>'
    : cols.map(c => `<th scope="col"><span class="pct-swatch" style="background:${c.color}"></span>${c.name}</th>`).join('');
  const rows = PCT_TABLE_ROWS.map(k => {
    const cells = cols.map(c => {
      const x = pctCell(c.t, k);
      if (!x) return single ? '<td>—</td><td></td>' : '<td>—</td>';
      return single ? `<td>${x.v}</td><td class="pct-se">${x.se}</td>` : `<td>${x.v}<div class="pct-se">${x.se}</div></td>`;
    }).join('');
    return `<tr><th scope="row">P${k}${k === 50 ? ' · median' : ''}</th>${cells}</tr>`;
  }).join('');
  return `<div class="pct-scroll"><table class="pct-table${single ? '' : ' pct-multi'}" aria-label="Household income percentiles">
      <thead><tr><th scope="col">Percentile</th>${headCells}</tr></thead><tbody>${rows}</tbody></table></div>`;
}

// Income against percentile: the lines, the gray reference behind them, and on a single line its ±SE band and a few
// labels. A change of filters slides the lines (and the scale) from where they were.
function drawPctChart(lines, ref) {
  const svgEl = document.getElementById('pct-chart');
  const W = svgEl.clientWidth, H = svgEl.clientHeight;
  if (W < 50 || H < 50) return;
  const single = lines.length === 1;
  const m = { l: isMobile() ? 44 : 56, r: 12, t: 18, b: 26 };
  const cw = W - m.l - m.r, ch = H - m.t - m.b;
  const ptsOf = t => t.v.map((v, i) => ({ k: i + 1, v, se: t.se[i] }));
  const series = [
    ...(ref ? [{ key: 'ref', name: 'All households', color: PCT_REF_COLOR, t: ref, ref: true }] : []),
    ...lines,
  ].map(l => ({ ...l, pts: ptsOf(l.t), tc: l.t.tc || 100 }));
  const ok = d => d.v != null;
  const top = d3.max(series, l => d3.max(l.pts, d => (ok(d) ? d.v + (single && !l.ref ? (d.se ?? 0) : 0) : null)));
  const x = d3.scaleLinear().domain([1, 99]).range([0, cw]);
  const y = d3.scaleLinear().domain([0, top]).nice(5).range([ch, 0]);
  const g = d3.select(svgEl).append('g').attr('transform', `translate(${m.l},${m.t})`);

  const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
  const prev = pctPrev;
  const dur = prev && !reduce ? 450 : 0;
  pctPrev = { domain: y.domain(), lines: Object.fromEntries(series.map(l => [l.key, l.t.v])) };
  const yAt = u => y.copy().domain(d3.interpolate(prev ? prev.domain : y.domain(), y.domain())(u));

  const yAxis = g.append('g').attr('class', 'axis');
  const drawY = sc => yAxis.call(d3.axisLeft(sc).ticks(5).tickSize(-cw).tickFormat(fmt$Short));
  g.append('g').attr('class', 'axis').attr('transform', `translate(0,${ch})`)
    .call(d3.axisBottom(x).tickValues(isMobile() ? [1, 20, 40, 60, 80, 99] : [1, 10, 20, 30, 40, 50, 60, 70, 80, 90, 99])
      .tickSize(4).tickFormat(d => `P${d}`));

  // a single line gets its ±SE band (under the lines) and a few labelled points, once it has arrived
  const band = g.append('g').style('opacity', dur ? 0 : 1);

  // each line is solid up to its cap percentile and dashed from there; a line that was drawn before slides in
  const paths = [];
  for (const l of series) {
    const from = prev?.lines[l.key];
    const parts = l.tc < 100 ? [[1, l.tc, ''], [l.tc, 99, ' pct-line-cap']] : [[1, 99, '']];
    for (const [a, b, cls] of parts) {
      const path = g.append('path').attr('class', `pct-line${cls}${l.ref ? ' pct-ref' : ''}`)
        .style('stroke', l.ref ? null : l.color);
      paths.push({ path, l, a, b, from });
    }
  }
  const frame = u => {
    const sc = yAt(u);
    drawY(sc);
    for (const { path, l, a, b, from } of paths) {
      const pts = l.pts.filter(d => d.k >= a && d.k <= b).map(d => {
        const was = from?.[d.k - 1];
        return { k: d.k, v: d.v != null && was != null ? was + (d.v - was) * u : d.v };
      });
      path.attr('d', d3.line().defined(ok).x(d => x(d.k)).y(d => sc(d.v))(pts));
    }
  };
  frame(dur ? 0 : 1);
  if (dur) d3.transition().duration(dur).ease(d3.easeCubicOut).tween('slide', () => frame);

  const labels = g.append('g').style('opacity', dur ? 0 : 1);
  if (single) {
    const l = series[series.length - 1];
    band.append('path').datum(l.pts).attr('class', 'pct-band')
      .attr('d', d3.area().defined(d => ok(d) && d.se != null).x(d => x(d.k))
        .y0(d => y(Math.max(0, d.v - d.se))).y1(d => y(d.v + d.se)));
    for (const k of PCT_LABELS) {
      const d = l.pts[k - 1];
      if (!ok(d)) continue;
      labels.append('circle').attr('class', 'pct-mark').attr('cx', x(k)).attr('cy', y(d.v)).attr('r', 3.5);
      labels.append('text').attr('class', 'pct-label').attr('x', x(k) - 6).attr('y', y(d.v) - 6)
        .attr('text-anchor', 'end').text(`P${k} ${fmt$Short(d.v)}`);
    }
  }
  if (dur) [band, labels].forEach(s => s.transition().delay(dur).duration(200).style('opacity', 1));

  // hover or tap: every line at the nearest percentile, highest first; on a single line, past P80, how many times P80
  const guide = g.append('line').attr('class', 'pct-guide').attr('y2', ch).style('display', 'none');
  const dots = g.append('g');
  const hide = () => { guide.style('display', 'none'); dots.selectAll('*').remove(); hideTooltip(); };
  const show = event => {
    const k = Math.max(1, Math.min(99, Math.round(x.invert(d3.pointer(event, g.node())[0]))));
    const at = series.map(l => ({ l, d: l.pts[k - 1] })).filter(o => ok(o.d)).sort((a, b) => b.d.v - a.d.v);
    if (!at.length) { hide(); return; }
    guide.attr('x1', x(k)).attr('x2', x(k)).style('display', null);
    dots.selectAll('*').remove();
    for (const { l, d } of at) {
      dots.append('circle').attr('class', 'pct-mark').attr('cx', x(k)).attr('cy', y(d.v)).attr('r', 4)
        .style('fill', l.ref ? PCT_REF_COLOR : l.color);
    }
    const row = ({ l, d }) => {
      const se = d.se == null ? '' : ` <span class="tt-dim">${l.t.live ? '≈' : ''}±${fmt$(d.se)}</span>`;
      const cap = k >= l.tc ? ' <span class="pct-cap">†</span>' : '';
      const name = single && !l.ref ? ''
        : `<span class="pct-swatch" style="background:${l.ref ? PCT_REF_COLOR : l.color}"></span>${l.name} `;
      const p80 = l.pts[79].v;
      const ratio = single && !l.ref && k > 80 && p80 ? `<div class="tt-dim">×${(d.v / p80).toFixed(2)} P80</div>` : '';
      return `<div class="tt-row">${name}${fmt$(d.v)}${se}${cap}</div>${ratio}`;
    };
    const tt = document.getElementById('tooltip');
    tt.innerHTML = `<div class="tt-income">P${k}${k === 50 ? ' · median' : ''}</div>` + at.map(row).join('')
      + (at.some(o => k >= o.l.tc) ? '<div class="tt-dim">† Near the income cap</div>' : '');
    tt.style.display = 'block';
    moveTooltip(event);
  };
  g.append('rect').attr('class', 'pct-hit').attr('width', cw).attr('height', ch).attr('fill', 'transparent')
    .style('touch-action', 'pan-y')
    .on('pointermove', show).on('pointerdown', show).on('pointerleave', hide);
}
