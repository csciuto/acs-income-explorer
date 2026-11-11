// American Income Explorer: stats.js
// The statistics: precomputed when the table has the slice, worked out from the sample when it does not; and showing them.
// A plain script: these files share one set of globals and load in the order index.html lists them.

// ============================================================
// Stats
// ============================================================
const DIM_TO_KEY = {
  age_bucket: 'age', sex: 'sex', marst: 'marst', educ: 'educ',
  work_status: 'work', passive_pct: 'ppct', passive_source: 'psrc', earner_count: 'earners', breadwinner: 'bread',
  kids: 'kids', race_ethnicity: 'race', city: 'city', burden: 'burden', multi_job_proxy: 'mjob',
  housing: 'house', metro: 'metro', year: 'year', region: 'region',
};

function getStats() {
  const cols = currentCols();
  const rows = visibleRows;
  const n = rows.length;

  // A precomputed cell (with standard errors) exists for one place and single-valued household filters.
  const p = currentPlace();
  const dimFilter = householdFilterKey();
  let otherCell = null;
  if (dimFilter) {
    otherCell = p.level === 'puma' ? null : placeCell(p, dimFilter, otherPrecomputed, {});
    const cell = placeCell(p, dimFilter);
    if (cell) return { ...cell, source: 'precomputed', other: otherCell };
  }

  if (n < 50) return { n, rel: 0, source: 'live', other: otherCell };

  const inc = rows.map(i => cols.inc[i]);
  const w = rows.map(i => cols.weight[i]);
  const wTotal = w.reduce((a,b) => a+b, 0);

  const [p25, wMed, p75] = wQuantiles(inc, w, [0.25, 0.5, 0.75]);
  const seApprox = approxQuantileSE(inc, w, 0.5);   // from this sample alone: rougher than the precomputed errors

  return {
    n, n_rep: wTotal,
    med: Math.round(wMed), mean: Math.round(wMean(inc, w)),
    se_med_approx: seApprox == null ? null : Math.round(seApprox),
    p25: Math.round(p25), p75: Math.round(p75),
    iqr: Math.round(p75 - p25),
    rel: n >= 500 ? 3 : n >= 200 ? 2 : 1,
    source: 'live',
    other: otherCell,
  };
}

// ============================================================
// Stats display
// ============================================================
function renderStats(stats) {
  if (!stats) { clearStats(); return; }
  const { n, rel } = stats;

  if (rel <= 0) {
    document.getElementById('s-med').textContent = '—';
    document.getElementById('s-mean').textContent = '—';
    document.getElementById('s-p2575').textContent = '—';
    document.getElementById('rel-badge').innerHTML = `<span class="reliability rel-0">⚠ Too few households (${n})</span>`;
    document.getElementById('n-info').textContent = '';
    renderOther(stats);
    return;
  }

  // precomputed views carry the survey's own standard error; live views get an approximate one, marked ≈
  const seStr = stats.se_med ? ` ±${fmt$(stats.se_med)} SE`
    : stats.se_med_approx ? ` <span title="Approximate: worked out from the chart's sample, not the survey's replicate weights">≈±${fmt$(stats.se_med_approx)} SE</span>` : '';
  document.getElementById('s-med').innerHTML = `${fmt$(stats.med)}<span class="stat-se">${seStr}</span>`;
  document.getElementById('s-mean').textContent = fmt$(stats.mean);
  document.getElementById('s-p2575').textContent = `${fmt$(stats.p25)} / ${fmt$(stats.p75)}`;
  const relMsg = rel === 1 ? '⚠ Small sample' :
                 rel === 2 ? '⚠ Modest sample' : '';
  document.getElementById('rel-badge').innerHTML = relMsg
    ? `<span class="reliability rel-${rel}">${relMsg}</span>` : '';

  const nRep = !stats.n_rep ? '' : ` · ~${fmtHH(stats.n_rep)} households`;
  document.getElementById('n-info').textContent = `${n.toLocaleString()} surveyed${nRep}`;
  renderOther(stats);
}

// The other survey's figure for the same slice, when it has one
function renderOther(stats) {
  const el = document.getElementById('other-src');
  if (!el) return;
  const o = stats && stats.other;
  const otherSrc = source === 'acs' ? 'cps' : 'acs';
  if (!o || !codebook.sources[otherSrc]) { el.innerHTML = ''; return; }
  const name = codebook.sources[otherSrc].short;
  const se = o.se_med ? ` ±${fmt$(o.se_med)}` : '';
  let gap = '';
  if (stats.med && o.med && stats.se_med != null && o.se_med != null) {
    const z = (stats.med - o.med) / Math.hypot(stats.se_med || 0, o.se_med || 0);
    if (Math.abs(z) > 2) gap = ` <span class="gap">· differs</span>`;
  }
  el.innerHTML = `${name}: ${fmt$(o.med)}${se}${gap} <button type="button">Switch</button>`;
  el.querySelector('button').onclick = () => setSource(otherSrc);
}

function clearStats() {
  ['s-med','s-mean','s-p2575'].forEach(id => {
    document.getElementById(id).textContent = '—';
  });
  document.getElementById('rel-badge').innerHTML = '';
  document.getElementById('n-info').textContent = '';
}
