// Unit tests for docs/js/lib.js. Run: node --test tests/js   (pytest runs them too, through tests/test_js.py)
const test = require('node:test');
const assert = require('node:assert/strict');
const L = require('../../docs/js/lib.js');

// the weighted percentile as it was written before, to check the faster one against
function oldPercentile(values, weights, q) {
  const order = Array.from({ length: values.length }, (_, i) => i).sort((a, b) => values[a] - values[b]);
  const sortedV = order.map(i => values[i]), sortedW = order.map(i => weights[i]);
  const cumW = []; let cum = 0;
  for (const w of sortedW) { cum += w; cumW.push(cum); }
  const target = q * cumW[cumW.length - 1];
  let idx = cumW.findIndex(c => c >= target);
  if (idx < 0) idx = sortedV.length - 1;
  return sortedV[idx];
}
function rng(seed) { let a = seed >>> 0; return () => { a = (a + 0x6D2B79F5) >>> 0; let t = a; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; }
// incomes roughly like the real thing (lognormal, median about $75,000), with unequal weights
function sample(n, seed, spread = 1) {
  const r = rng(seed), inc = [], w = [];
  for (let i = 0; i < n; i++) {
    const z = Math.sqrt(-2 * Math.log(1 - r())) * Math.cos(2 * Math.PI * r());
    inc.push(Math.round(75000 * Math.exp(0.8 * z)));
    w.push(20 + spread * 200 * r());
  }
  return { inc, w };
}

test('formatting', () => {
  assert.equal(L.fmt$(71234.6), '$71,235');
  assert.equal(L.fmt$(null), '—');
  assert.equal(L.fmtHH(6303838), '6.3M');
  assert.equal(L.fmtHH(45200), '45K');
  assert.equal(L.fmtHH(1234), '1.2K');
  assert.equal(L.fmtHH(999), '999');
  assert.equal(L.fmtPct(0.1234), '12.3%');
  assert.equal(L.fmtPct(NaN), '—');
});

test('table keys: the place, then filters in alphabetical order, whatever order they were chosen in', () => {
  assert.equal(L.buildKey('state=25', { sex: 2, educ: 4 }), 'state=25|educ=4|sex=2');
  assert.equal(L.buildKey('state=25', { educ: 4, sex: 2 }), 'state=25|educ=4|sex=2');
  assert.equal(L.buildKey('national', {}), 'national');
  assert.equal(L.buildKey('', { age: 3 }), 'age=3');
});

test('weighted quantiles: by hand', () => {
  // weights 1,1,2: the value 30 holds half the weight
  assert.deepEqual(L.wQuantiles([10, 20, 30], [1, 1, 2], [0.25, 0.5, 0.75, 1]), [10, 20, 30, 30]);
  assert.equal(L.wPercentile([30, 10, 20], [2, 1, 1], 0.5), 20);        // order of the rows doesn't matter
  assert.equal(L.wPercentile([5], [3], 0.5), 5);
  assert.equal(L.wPercentile([1, 2], [1, 1], 0), 1);
  assert.equal(L.wMean([10, 20, 30], [1, 1, 2]), 22.5);
});

test('weighted quantiles agree with the earlier implementation on thousands of households', () => {
  const { inc, w } = sample(5000, 11);
  for (const q of [0.01, 0.1, 0.25, 0.5, 0.75, 0.9, 0.99, 1]) assert.equal(L.wPercentile(inc, w, q), oldPercentile(inc, w, q), `q=${q}`);
  assert.deepEqual(L.wQuantiles(inc, w, [0.25, 0.5, 0.75]), [0.25, 0.5, 0.75].map(q => oldPercentile(inc, w, q)));
});

test("Kish's effective sample size: n for equal weights, fewer for unequal ones", () => {
  assert.equal(L.kishN([2, 2, 2, 2]), 4);
  assert.equal(L.kishN([1, 1, 1, 9]), 144 / 84);
  assert.equal(L.kishN([]), 0);
});

test('the approximate standard error of the median is about right', () => {
  // truth by brute force: the spread of the median across many independent samples of the same size
  const n = 800, medians = [], ses = [];
  for (let s = 1; s <= 300; s++) {
    const { inc, w } = sample(n, s);
    medians.push(L.wPercentile(inc, w, 0.5));
    ses.push(L.approxQuantileSE(inc, w, 0.5));
  }
  const mean = a => a.reduce((x, y) => x + y, 0) / a.length;
  const sd = Math.sqrt(mean(medians.map(m => (m - mean(medians)) ** 2)));
  const est = mean(ses);
  assert.ok(est > 0.8 * sd && est < 1.25 * sd, `estimated ${est.toFixed(0)} against a true spread of ${sd.toFixed(0)}`);
});

test('the approximate standard error shrinks with more households and grows with more unequal weights', () => {
  const small = sample(400, 5), big = sample(6400, 5);
  const seSmall = L.approxQuantileSE(small.inc, small.w, 0.5), seBig = L.approxQuantileSE(big.inc, big.w, 0.5);
  assert.ok(seBig < seSmall / 2.5, `${seSmall} then ${seBig}`);           // sixteen times the sample: about a quarter
  const even = sample(2000, 9, 0), uneven = sample(2000, 9, 30);
  assert.ok(L.kishN(uneven.w) < L.kishN(even.w));
  assert.equal(L.approxQuantileSE([1], [1], 0.5), null);                  // one household: no estimate
  assert.equal(L.approxQuantileSE([], [], 0.5), null);
});

test('subsample: the right number, no repeats, all of them when there are few', () => {
  const rows = Array.from({ length: 1000 }, (_, i) => i);
  const got = L.subsample(rows, 100, rng(3));
  assert.equal(got.length, 100);
  assert.equal(new Set(got).size, 100);
  assert.ok(got.every(v => v >= 0 && v < 1000));
  assert.equal(L.subsample(rows, 5000), rows);
  assert.equal(rows.length, 1000);                                          // the input is left alone
  assert.deepEqual(L.subsample(rows, 100, rng(3)), got);                    // the same draws give the same sample
});
