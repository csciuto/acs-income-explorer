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
  const [lo, hi] = wQuantiles(values, weights, [Math.max(0, q - sp), Math.min(1, q + sp)]);
  return (hi - lo) / 2;
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

if (typeof module !== 'undefined') module.exports = { fmtHH, fmt$, fmtPct, buildKey, wQuantiles, wPercentile, wMean, kishN, approxQuantileSE, subsample };
