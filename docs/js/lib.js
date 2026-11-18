// American Income Explorer: the pure pieces. No page, no state: numbers in, numbers or text out.
// Loaded as a plain script by index.html, and by the unit tests in Node (tests/js/lib.test.js).

// ---------- formatting ----------
function fmtHH(n) {
  if (n == null || isNaN(n)) return '—';
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)}M`;
  if (n >= 1e4) return `${Math.round(n / 1e3)}K`;
  if (n >= 1e3) return `${(n / 1e3).toFixed(1)}K`;
  return Math.round(n).toLocaleString();
}
function fmt$(n) {
  if (n == null || isNaN(n)) return '—';
  return '$' + Math.round(n).toLocaleString();
}
function fmtPct(n) {
  if (n == null || isNaN(n)) return '—';
  return (n * 100).toFixed(1) + '%';
}

// ---------- the precomputed table's keys ----------
// "state=25|educ=4|sex=2": the place, then each filter in alphabetical order.
function buildKey(scopeStr, filterObj) {
  const parts = scopeStr ? [scopeStr] : [];
  for (const [k, v] of Object.entries(filterObj).sort((a, b) => a[0].localeCompare(b[0]))) {
    parts.push(`${k}=${v}`);
  }
  return parts.join('|');
}

// ---------- weighted statistics ----------
// Weighted quantiles, one sort for any number of them: for each q, the smallest value at which the running
// weight reaches q of the total.
function wQuantiles(values, weights, qs) {
  const n = values.length;
  if (!n) return qs.map(() => undefined);
  const order = Array.from({ length: n }, (_, i) => i).sort((a, b) => values[a] - values[b]);
  const cum = new Float64Array(n);
  let run = 0;
  for (let k = 0; k < n; k++) { run += weights[order[k]]; cum[k] = run; }
  return qs.map(q => {
    const target = q * run;
    let lo = 0, hi = n - 1;                       // first k with cum[k] >= target
    if (cum[hi] < target) return values[order[hi]];
    while (lo < hi) { const mid = (lo + hi) >> 1; if (cum[mid] >= target) hi = mid; else lo = mid + 1; }
    return values[order[lo]];
  });
}
function wPercentile(values, weights, q) { return wQuantiles(values, weights, [q])[0]; }
function wMean(values, weights) {
  let s = 0, w = 0;
  for (let i = 0; i < values.length; i++) { s += values[i] * weights[i]; w += weights[i]; }
  return s / w;
}

// Binned quantiles, the way the precomputed statistics are worked out (pipeline/common.py): find the $2,500
// interval where the running weight reaches q of the total, then interpolate inside it. Exactly $0 is its own
// point. Without this, round numbers (many households at exactly $80,000) pin a quantile to one value.
const QUANTILE_BIN = 2500;
function sortByValue(values, weights, extra) {
  const n = values.length;
  const order = Array.from({ length: n }, (_, i) => i).sort((a, b) => values[a] - values[b]);
  const v = new Float64Array(n), w = new Float64Array(n), x = extra ? new Uint8Array(n) : null;
  for (let k = 0; k < n; k++) { v[k] = values[order[k]]; w[k] = weights[order[k]]; if (x) x[k] = extra[order[k]]; }
  return { v, w, x };
}
function incomeBins(v, w) {   // v sorted ascending
  const lo = [], wd = [], bw = [];
  let prev = null;
  for (let k = 0; k < v.length; k++) {
    const key = v[k] === 0 ? -1 : Math.floor(v[k] / QUANTILE_BIN);
    if (key !== prev) { lo.push(key < 0 ? 0 : key * QUANTILE_BIN); wd.push(key < 0 ? 0 : QUANTILE_BIN); bw.push(0); prev = key; }
    bw[bw.length - 1] += w[k];
  }
  const cb = new Float64Array(bw.length);
  let run = 0;
  for (let b = 0; b < bw.length; b++) { run += bw[b]; cb[b] = run; }
  return { lo, wd, bw, cb };
}
function quantilesFromBins({ lo, wd, bw, cb }, qs) {
  const last = cb.length - 1, tot = cb[last];
  return qs.map(q => {
    const target = q * tot;
    let a = 0, b = last;                         // first bin whose running weight reaches the target
    while (a < b) { const m = (a + b) >> 1; if (cb[m] >= target) b = m; else a = m + 1; }
    const inside = bw[a], below = cb[a] - inside;
    const frac = inside > 0 ? Math.min(1, Math.max(0, (target - below) / inside)) : 0;
    return lo[a] + wd[a] * frac;
  });
}
function binnedQuantiles(values, weights, qs) {
  if (!values.length) return qs.map(() => undefined);
  const { v, w } = sortByValue(values, weights);
  return quantilesFromBins(incomeBins(v, w), qs);
}

// Kish's effective sample size: how many equally weighted households the weighted sample is worth.
function kishN(weights) {
  let s = 0, s2 = 0;
  for (const w of weights) { s += w; s2 += w * w; }
  return s2 > 0 ? s * s / s2 : 0;
}

// An approximate standard error for a weighted quantile, from the sample alone (Woodruff's method).
// The share of households below the quantile has standard error sqrt(q(1-q) / n_eff); the quantiles one
// standard error either side of q bracket the estimate, and half their distance is its standard error.
// It is rougher than the replicate-weight errors the precomputed views carry: it knows about unequal
// weights but not about the survey's clustering, and it measures the chart's sample, not the full survey.
function approxQuantileSE(values, weights, q) {
  const nEff = kishN(weights);
  if (!(nEff > 1)) return null;
  const sp = Math.sqrt(q * (1 - q) / nEff);
  const [lo, hi] = binnedQuantiles(values, weights, [Math.max(0, q - sp), Math.min(1, q + sp)]);
  return (hi - lo) / 2;
}

// P1-P99 from a sample, the way the Percentiles view shows them: {v, se, tc}, or null under 50 households.
// v and se are null where fewer than 10 sample households lie on either side; se is approxQuantileSE's;
// tc is the first percentile where most households (by weight) at or above it are topcoded, as the pipeline does.
const PCT_QS = Array.from({ length: 99 }, (_, i) => (i + 1) / 100);
function percentileTable(values, weights, topcoded) {
  const n = values.length;
  if (n < 50) return null;
  const { v, w, x } = sortByValue(values, weights, topcoded);
  const bins = incomeBins(v, w);
  const vals = quantilesFromBins(bins, PCT_QS);
  const nEff = kishN(w);
  const sps = PCT_QS.map(q => Math.sqrt(q * (1 - q) / nEff));
  const lo = quantilesFromBins(bins, PCT_QS.map((q, i) => Math.max(0, q - sps[i])));
  const hi = quantilesFromBins(bins, PCT_QS.map((q, i) => Math.min(1, q + sps[i])));
  const cw = new Float64Array(n);
  let run = 0;
  for (let k = 0; k < n; k++) { run += w[k]; cw[k] = run; }
  const below = q => { let a = 0, b = n - 1; while (a < b) { const m = (a + b) >> 1; if (cw[m] >= q * run) b = m; else a = m + 1; } return a; };
  // weight at and above each row, all and topcoded only
  const above = new Float64Array(n + 1), aboveTc = new Float64Array(n + 1);
  for (let k = n - 1; k >= 0; k--) { above[k] = above[k + 1] + w[k]; aboveTc[k] = aboveTc[k + 1] + (x && x[k] ? w[k] : 0); }
  const out = { v: [], se: [] };
  PCT_QS.forEach((q, i) => {
    const j = below(q), ok = j >= 10 && n - j >= 10;
    out.v.push(ok ? Math.round(vals[i]) : null);
    out.se.push(ok ? Math.round((hi[i] - lo[i]) / 2) : null);
    if (x && out.tc == null && aboveTc[j] > 0 && aboveTc[j] >= 0.5 * above[j]) out.tc = i + 1;
  });
  return out;
}

// ---------- sampling ----------
// `limit` of the rows, chosen at random without replacement (all of them if there are no more than that).
function subsample(rows, limit, random = Math.random) {
  if (rows.length <= limit) return rows;
  const arr = [...rows];
  const n = arr.length;
  for (let i = 0; i < limit; i++) {
    const j = i + Math.floor(random() * (n - i));
    const tmp = arr[i]; arr[i] = arr[j]; arr[j] = tmp;
  }
  return arr.slice(0, limit);
}

if (typeof module !== 'undefined') module.exports = { fmtHH, fmt$, fmtPct, buildKey, wQuantiles, wPercentile, binnedQuantiles, wMean, kishN, approxQuantileSE, percentileTable, subsample };
