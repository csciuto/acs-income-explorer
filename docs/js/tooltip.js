// American Income Explorer: tooltip.js
// The tooltip, and the pinned household card.
// A plain script: these files share one set of globals and load in the order index.html lists them.

// ============================================================
// Tooltip
// ============================================================
function showTooltip(event, i) {
  const cols = currentCols();
  const tt = document.getElementById('tooltip');

  const inc = cols.inc[i];
  const topcode = cols.topcoded[i] === 1;
  const yr = codebook?.year_display?.[String(cols.year[i])] ?? String(cols.year[i]);
  const stateName = codebook?.states?.[String(cols.state[i])]?.name ?? `State ${cols.state[i]}`;

  const hhSize    = cols.hh_size?.[i] ?? '?';
  const nEarners  = cols.earner_count?.[i] ?? '?';
  const nKids     = cols.n_children?.[i] ?? (cols.kids?.[i] ? '1+' : '0');
  const wageInc   = cols.wage_inc[i];
  const passiveInc= cols.passive_inc?.[i];
  const psrcLabel = cols.passive_source != null ? label('passive_source', cols.passive_source[i]) : null;

  const earnerLine = nEarners === 0
    ? 'No earners'
    : `${nEarners} earner${nEarners !== 1 ? 's' : ''} · ${fmt$(wageInc)} earnings`;
  const passiveLine = (passiveInc != null && passiveInc > 0)
    ? `${fmt$(passiveInc)} unearned${psrcLabel && psrcLabel !== 'Mainly earnings' ? ' (' + psrcLabel + ')' : ''}`
    : null;

  tt.innerHTML = `
    <div class="tt-income">${fmt$(inc)}${topcode ? ' <span class="tt-topcode">(topcoded)</span>' : ''}</div>
    <div class="tt-dim">${hhSize} in household · ${nKids === 0 || nKids === '0' ? 'no children' : nKids + ' child' + (nKids !== 1 ? 'ren' : '')}</div>
    <div class="tt-dim">${earnerLine}</div>
    ${passiveLine ? `<div class="tt-dim">${passiveLine}</div>` : ''}
    <div class="tt-dim">${label('age_bucket', cols.age_bucket[i])} · ${label('marst', cols.marst[i])} · ${label('educ', cols.educ[i])}</div>
    <div class="tt-dim">${cols.metro_area?.[i] ? label('metro_area', cols.metro_area[i]) : stateName} · ${label('city', cols.city[i])}</div>
    ${cols.puma?.[i] ? `<div class="tt-dim">${label('puma', cols.puma[i])}</div>` : ''}
    <div class="tt-dim">${label('work_status', cols.work_status[i])} · ${label('housing', cols.housing[i])}${cols.burden?.[i] < 3 ? ', ' + label('burden', cols.burden[i]) + ' of income' : ''}</div>
    <div class="tt-dim">Stands for ${Math.round(cols.weight[i]).toLocaleString()} households · ${yr}</div>
  `;
  tt.style.display = 'block';
  moveTooltip(event);
}

function moveTooltip(event) {
  if (isMobile()) return; // CSS pins tooltip to top-center on mobile
  const tt = document.getElementById('tooltip');
  const x = event.clientX + 14;
  const y = event.clientY - 10;
  const maxX = window.innerWidth - tt.offsetWidth - 10;
  tt.style.left = Math.min(x, maxX) + 'px';
  tt.style.top = y + 'px';
}

function hideTooltip() {
  document.getElementById('tooltip').style.display = 'none';
}

// ============================================================
// Pinned household: click a dot to keep its whole record open. The pin follows the record, so in Dim others
// you can change filters and watch it match or fade. It closes when the household leaves the chart.
// ============================================================
let pinnedRow = null;
const pinSheet = document.getElementById('pin-sheet');

function pinRow(i) {
  pinnedRow = i;
  hideTooltip();
  if (isMobile()) { pinSheet.hidden = false; pinSheet.classList.remove('open'); }
  else switchStatsTab('household');
  syncPin();
}

function unpin() {
  pinnedRow = null;
  pinSheet.hidden = true;
  pinSheet.classList.remove('open');
  d3.select('#chart-svg').selectAll('.pin-ring').remove();
  renderPinEmpty();
}

function renderPinEmpty() {
  document.getElementById('pin-card').innerHTML = '<p class="pin-empty">Click a dot to pin it.</p>';
  pinSheet.innerHTML = '';
}

function syncPin() {
  if (pinnedRow == null) return;
  const d = viewMode === 'dots' ? dotData.find(d => d.i === pinnedRow) : null;
  if (!d) { unpin(); return; }
  const svg = d3.select('#chart-svg');
  svg.selectAll('.pin-ring').remove();
  svg.append('circle').attr('class', 'pin-ring')
    .attr('cx', d.x).attr('cy', d.y).attr('r', d.r + 3)
    .attr('fill', 'none').attr('stroke', '#fff').attr('stroke-width', 1.5).attr('pointer-events', 'none');
  renderPinCard();
}

function renderPinCard() {
  const cols = currentCols(), i = pinnedRow;
  const lab = dim => cols[dim] != null ? label(dim, cols[dim][i]) : null;
  const rows = pairs => '<dl>' + pairs.filter(([, v]) => v != null && v !== '')
    .map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join('') + '</dl>';

  const out = [];
  if (selectedFips.size && !selectedFips.has(cols.state[i])) out.push('State');
  for (const [dim, vals] of Object.entries(filters)) {
    if (vals?.size && cols[dim] && !vals.has(cols[dim][i])) out.push(DIM_LABELS[dim] ?? dim);
  }
  if (!matchesBrush(i, cols)) out.push('Range');
  const anyFilter = selectedFips.size > 0 || brushRange || Object.values(filters).some(s => s && s.size > 0);
  const status = !anyFilter ? ''
    : out.length ? `<div class="pin-status out">Filtered out by ${out.join(', ')}</div>`
    : '<div class="pin-status in">Matches</div>';

  const kids = cols.n_children?.[i];
  const youngest = kids > 0 ? lab('youngest_child') : null;
  const unearned = cols.passive_inc?.[i];
  const src = lab('passive_source');
  const stateName = codebook?.states?.[String(cols.state[i])]?.name ?? `State ${cols.state[i]}`;
  const burden = cols.burden?.[i] < 3 ? lab('burden') + ' of income' : null;

  const html = `
    <div class="pin-head">
      <span class="pin-inc">${fmt$(cols.inc[i])}${cols.topcoded[i] === 1 ? ' <span class="tt-topcode">(topcoded)</span>' : ''}</span>
      <span class="pin-actions"><button class="pin-more" aria-label="More">▴</button><button class="pin-close" aria-label="Close">×</button></span>
    </div>
    ${status}
    <div class="pin-summary">${lab('age_bucket')} · ${lab('housing')} · ${cols.hh_size?.[i] ?? '?'} in household</div>
    <div class="pin-body">
    <h4>Income</h4>
    ${rows([
      ['Earnings', fmt$(cols.wage_inc[i])],
      ['Unearned', unearned > 0 ? fmt$(unearned) : '$0'],
      ['Main unearned', unearned > 0 && src !== 'Mainly earnings' ? src : null],
      ['Share from earnings', lab('passive_pct')],
    ])}
    <h4>Household</h4>
    ${rows([
      ['People', cols.hh_size?.[i]],
      ['Children', kids != null ? (youngest ? `${kids} · youngest ${youngest.toLowerCase()}` : kids) : lab('kids')],
      ['Earners', lab('earner_count')],
      ["Householder's share", lab('breadwinner')],
      ['Roommates', cols.has_roommate ? (cols.has_roommate[i] ? 'Yes' : 'No') : null],
      ['Housing', lab('housing')],
      ['Cost burden', burden],
    ])}
    <h4>Householder</h4>
    ${rows([
      ['Age', lab('age_bucket')],
      ['Sex', lab('sex')],
      ['Race/ethnicity', lab('race_ethnicity')],
      ['Marital', lab('marst')],
      ['Education', lab('educ')],
      ['Work', lab('work_status')],
      ['Hours', lab('hours_category')],
      ['Secondary hours', lab('multi_job_proxy')],
    ])}
    <h4>Place</h4>
    ${rows([
      ['Local area', cols.puma?.[i] ? lab('puma') : null],
      ['Metro', cols.metro_area?.[i] ? lab('metro_area') : null],
      ['State', stateName],
      ['Area type', lab('city')],
      ['Region', lab('region')],
    ])}
    <h4>Survey</h4>
    ${rows([
      ['Year', label('year', cols.year[i])],
      ['Stands for', `${Math.round(cols.weight[i]).toLocaleString()} households`],
    ])}
    </div>
  `;
  document.querySelectorAll('.pin-view').forEach(el => { el.innerHTML = html; });
}

// One listener per container: the card is re-rendered on every filter change
document.querySelectorAll('.pin-view').forEach(el => el.addEventListener('click', e => {
  if (e.target.closest('.pin-close')) { unpin(); return; }
  if (el === pinSheet && (e.target.closest('.pin-more') || e.target.closest('.pin-head'))) {
    pinSheet.classList.toggle('open');
    const more = pinSheet.querySelector('.pin-more');
    if (more) more.textContent = pinSheet.classList.contains('open') ? '▾' : '▴';
  }
}));
renderPinEmpty();

document.addEventListener('keydown', e => { if (e.key === 'Escape' && pinnedRow != null) unpin(); });
document.getElementById('chart-svg').addEventListener('click', () => { if (pinnedRow != null) unpin(); });
