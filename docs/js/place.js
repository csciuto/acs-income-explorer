// American Income Explorer: place.js
// Place: one at a time (the US, a region, a state, a metro area or a local area), its picker and its breadcrumbs.
// A plain script: these files share one set of globals and load in the order index.html lists them.

// ============================================================
// Place: one at a time (United States, a region, a state, a metro area or a local area)
// ============================================================
// Stored in the existing selections so links keep working: states=FIPS, region=R, metro_area=CBSA, puma=CODE.
const PLACE_TYPE = { us: 'Country', region: 'Region', state: 'State', metro: 'Metro area', puma: 'Local area' };
let placeNote = '';

function currentPlace() {
  if (filters.puma && filters.puma.size) return { level: 'puma', code: [...filters.puma][0] };
  if (filters.metro_area && filters.metro_area.size) return { level: 'metro', code: [...filters.metro_area][0] };
  if (selectedFips.size) return { level: 'state', code: [...selectedFips][0] };
  if (filters.region && filters.region.size) return { level: 'region', code: [...filters.region][0] };
  return { level: 'us', code: 0 };
}

function placeName(p) {
  if (p.level === 'us') return 'United States';
  if (p.level === 'region') return codebook.labels.region?.[p.code] ?? `Region ${p.code}`;
  if (p.level === 'state') return codebook.states?.[String(p.code)]?.name ?? `State ${p.code}`;
  if (p.level === 'metro') return codebook.metroNames?.[p.code] ?? `Metro area ${p.code}`;
  const a = codebook.localAreas?.[p.code];
  return a ? localName(a)[0] : `Local area ${p.code}`;
}

// States a metro area reaches, largest share of survey households first.
function metroStates(code) {
  const byState = new Map();
  for (const a of codebook.geoAreas || []) if (a.metro === code) byState.set(a.state, (byState.get(a.state) || 0) + a.n);
  return [...byState.entries()].sort((a, b) => b[1] - a[1]).map(([st]) => st);
}

// The place and the larger areas containing it, smallest first (local area -> metro -> state -> US).
function placeChain(p) {
  const chain = [p];
  if (p.level === 'puma') {
    const a = codebook.localAreas[p.code];
    if (a?.metro && codebook.metros?.[a.metro]) chain.push({ level: 'metro', code: a.metro });
    if (a) chain.push({ level: 'state', code: a.state });
  } else if (p.level === 'metro') {
    const st = metroStates(p.code);
    if (st.length === 1) chain.push({ level: 'state', code: st[0] });
  } else if (p.level === 'state') {
    const r = fipsToRegion.get(p.code);
    if (r) chain.push({ level: 'region', code: r });
  }
  if (p.level !== 'us') chain.push({ level: 'us', code: 0 });
  return chain;
}

// The precomputed cell for a place and a set of single-valued filters, or null.
function placeCell(p, dimFilter, table = precomputed, locals = localStats) {
  if (!table) return null;
  if (p.level === 'puma') return (locals[Math.floor(p.code / 100000)] || {})[buildKey(`puma=${p.code}`, dimFilter)] ?? null;
  if (p.level === 'metro') return table[buildKey(`metro=${p.code}`, dimFilter)] ?? null;
  if (p.level === 'state') return table[buildKey(`state=${p.code}`, dimFilter)] ?? null;
  if (p.level === 'region') return table[buildKey('national', { ...dimFilter, region: p.code })] ?? null;
  return table[buildKey('national', dimFilter)] ?? null;
}

const GEO_FILTERS = new Set(['metro_area', 'puma', 'region']);

// The household filters (not the place) as a stats key, or null when one has several values.
function householdFilterKey() {
  const dimFilter = {};
  for (const [dim, vals] of Object.entries(filters)) {
    if (!vals || vals.size === 0 || GEO_FILTERS.has(dim)) continue;
    if (vals.size > 1) return null;
    dimFilter[DIM_TO_KEY[dim] ?? dim] = [...vals][0];
  }
  return dimFilter;
}

async function setPlace(level, code = 0, note = '') {
  selectedFips.clear();
  delete filters.metro_area; delete filters.puma; delete filters.region;
  if (level === 'puma') { await ensureLocal(code); filters.puma = new Set([code]); }
  else if (level === 'metro') filters.metro_area = new Set([code]);
  else if (level === 'state') selectedFips.add(code);
  else if (level === 'region') filters.region = new Set([code]);
  placeNote = note;
  updateStateColorMap();
  chartScope = null;
  render();
}

// Old links could hold several states or a mix of levels: keep the most specific single place. The CPS has
// no metro or local areas, so those fall back to their state, with a note.
function normalizePlace() {
  const p = currentPlace();
  let target = p, note = '';
  if (source !== 'acs' && p.level === 'puma') {
    const a = codebook.localAreas[p.code];
    target = a?.metro && codebook.metros[a.metro] ? { level: 'metro', code: a.metro }
           : a ? { level: 'state', code: a.state } : { level: 'us', code: 0 };
    note = `No local areas in the ${srcInfo.short}. Showing ${placeName(target)}.`;
  } else if (p.level === 'metro' && !codebook.metros[p.code]) {
    const st = metroStates(p.code)[0];
    target = st ? { level: 'state', code: st } : { level: 'us', code: 0 };
    note = `Too few ${srcInfo.short} households in ${placeName(p)}. Showing ${placeName(target)}.`;
  }
  selectedFips = new Set(target.level === 'state' ? [target.code] : []);
  delete filters.metro_area; delete filters.puma; delete filters.region;
  if (target.level === 'puma') filters.puma = new Set([target.code]);
  if (target.level === 'metro') filters.metro_area = new Set([target.code]);
  if (target.level === 'region') filters.region = new Set([target.code]);
  placeNote = note;
  updateStateColorMap();
}

function placeIndex() {
  if (placeIndex.cache?.source === source) return placeIndex.cache.items;
  const items = [{ level: 'us', code: 0, name: 'United States', where: '' }];
  for (const [k, v] of Object.entries(codebook.labels.region || {})) items.push({ level: 'region', code: +k, name: v, where: '' });
  for (const [k, v] of Object.entries(codebook.states || {})) items.push({ level: 'state', code: +k, name: v.name, where: v.abbr });
  for (const [k, m] of Object.entries(codebook.metros || {})) items.push({ level: 'metro', code: +k, name: m.name, where: '' });
  if (source === 'acs') {
    for (const [k, a] of Object.entries(codebook.localAreas || {})) {
      const [name, county] = localName(a);
      const metro = a.metro && codebook.metros?.[a.metro] ? codebook.metros[a.metro].name : '';
      items.push({ level: 'puma', code: +k, name, where: [county, metro].filter(Boolean).join(' · ') });
    }
  }
  for (const it of items) it.text = `${it.name} ${it.where} ${PLACE_TYPE[it.level]}`.toLowerCase();
  placeIndex.cache = { source, items };
  return items;
}

const LEVEL_RANK = { us: 0, region: 1, state: 2, metro: 3, puma: 4 };

function searchPlaces(q) {
  const words = q.toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return [];
  const hits = placeIndex().filter(it => words.every(w => it.text.includes(w)));
  const starts = it => it.name.toLowerCase().startsWith(words[0]) ? 0 : 1;
  return hits.sort((a, b) => starts(a) - starts(b) || LEVEL_RANK[a.level] - LEVEL_RANK[b.level] || a.name.localeCompare(b.name));
}

function buildPlacePicker() {
  const input = document.getElementById('place-search');
  const list = document.getElementById('place-results');
  const draw = () => {
    const q = input.value.trim();
    if (q.length < 2) { list.innerHTML = ''; return; }
    const hits = searchPlaces(q);
    if (!hits.length) {
      list.innerHTML = `<div class="hint">No place matches “${q.replace(/[<>&]/g, '')}”.${source !== 'acs' ? ` The ${srcInfo.short} has states and large metros only.` : ''}</div>`;
      return;
    }
    list.innerHTML = hits.slice(0, 40).map(it =>
      `<button class="place-item" role="option" data-level="${it.level}" data-code="${it.code}">${it.name}<small>${PLACE_TYPE[it.level]}${it.where ? ' · ' + it.where : ''}</small></button>`).join('')
      + (hits.length > 40 ? `<div class="hint">${hits.length - 40} more; keep typing.</div>` : '');
  };
  input.addEventListener('input', draw);
  input.addEventListener('keydown', e => {
    if (e.key === 'Enter') list.querySelector('.place-item')?.click();
    if (e.key === 'ArrowDown') { list.querySelector('.place-item')?.focus(); e.preventDefault(); }
  });
  list.addEventListener('keydown', e => {
    const b = e.target.closest('.place-item');
    if (!b) return;
    if (e.key === 'ArrowDown') { (b.nextElementSibling || b).focus(); e.preventDefault(); }
    if (e.key === 'ArrowUp') { (b.previousElementSibling || input).focus(); e.preventDefault(); }
  });
  list.addEventListener('click', async e => {
    const b = e.target.closest('.place-item');
    if (!b) return;
    b.querySelector('small').textContent = 'Loading…';
    await setPlace(b.dataset.level, parseInt(b.dataset.code));
    input.value = '';
    list.innerHTML = '';
  });
  document.getElementById('place-current').addEventListener('click', e => {
    const b = e.target.closest('button[data-level]');
    if (b) setPlace(b.dataset.level, parseInt(b.dataset.code));
  });
  document.getElementById('place-context').addEventListener('click', e => {
    const b = e.target.closest('button[data-level]');
    if (b) setPlace(b.dataset.level, parseInt(b.dataset.code));
  });
}

function syncPlace() {
  const p = currentPlace();
  const chain = placeChain(p).reverse();  // US first
  const crumbs = document.getElementById('place-current');
  if (crumbs) {
    crumbs.innerHTML = chain.map((c, i) => i === chain.length - 1
      ? `<span class="here">${placeName(c)}</span>`
      : `<button data-level="${c.level}" data-code="${c.code}">${placeName(c)}</button><span class="sep">›</span>`).join('');
  }
  const note = document.getElementById('place-note');
  if (note) { note.hidden = !placeNote; note.textContent = placeNote; }
  const title = document.getElementById('place-title');
  if (title) {
    const sub = p.level === 'us' ? '' : [PLACE_TYPE[p.level], ...placeChain(p).slice(1, -1).map(placeName)].join(' · ');
    title.innerHTML = `${placeName(p)}${sub ? `<small>${sub}</small>` : ''}`;
  }
}

// Under the main figures: the same filters in each larger area containing the place, where computed.
function renderPlaceContext(stats) {
  const box = document.getElementById('place-context');
  if (!box) return;
  const p = currentPlace();
  const dimFilter = householdFilterKey();
  if (p.level === 'us' || !dimFilter || brushRange) { box.innerHTML = ''; return; }
  const rows = placeChain(p).map((c, i) => {
    const cell = i === 0 && stats?.source === 'precomputed' ? stats : placeCell(c, dimFilter);
    const val = cell && cell.med != null
      ? `${fmt$(cell.med)}${cell.se_med ? ` <span class="stat-se">±${fmt$(cell.se_med)}</span>` : ''}`
      : '<span title="Not available for these filters">—</span>';
    const name = i === 0 ? placeName(c) : `<button data-level="${c.level}" data-code="${c.code}">${placeName(c)}</button>`;
    return `<tr class="${i === 0 ? 'here' : ''}"><td>${name}</td><td class="v">${val}</td></tr>`;
  });
  box.innerHTML = `<table aria-label="Median in this place and the larger areas containing it">${rows.join('')}</table>`;
}
