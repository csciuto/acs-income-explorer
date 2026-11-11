// American Income Explorer: state.js
// Everything the page remembers: the loaded data, the selections, the view. Plus the color palettes.
// A plain script: these files share one set of globals and load in the order index.html lists them.

// ============================================================
// State
// ============================================================
let codebook = null;
let precomputed = null;
let nationalTable = null;
let source = new URLSearchParams(location.hash.slice(1)).get('src') === 'cps' ? 'cps' : 'acs';
let srcInfo = null;            // codebook.sources[source]
let otherPrecomputed = null;   // the other survey's precomputed stats, for the comparison line
const localStats = {};         // state FIPS -> local-area stats (ACS)
const localTables = {};        // state FIPS -> local-area households (ACS)
const localLoading = {};

let selectedFips = new Set();        // multi-state selection
let fipsToRegion = new Map();        // fips → regionCode
let regionToFips = new Map();        // regionCode → Set<fips>
let stateColorMap = new Map();       // fips → palette index

let filters = {};
let colorMode = 'passive_pct';

let visibleRows = [];
let dotData = [];
let chartScope = null;
let brushRange = null;   // {lo, hi} income values, or null
let brushLayer = null;   // D3 selection of brush <g>
let d3brush = null;      // D3 brush object
let brushModeActive = false;
let viewMode = 'dots';   // 'dots' | 'bars'
let sampleMode = true;   // true=static (sample all rows, dim non-matching); false=all (only matching rows)
let maxDots = 3000;      // dot cap: 1000 | 3000 | 5000
let lastPoolSize = 0;    // households the chart could draw from, to grey out caps that change nothing

function isMobile() { return window.innerWidth < 768; }

// ============================================================
// Color palettes
// ============================================================
const STATE_PALETTE = ['#4a7cbc', '#e07070', '#4a9c5e', '#c9a227', '#a97cc4', '#5bc8c8'];

const PALETTES = {
  region:          ['#888', '#4a7cbc', '#4a9c5e', '#c9a227', '#c94040'],
  passive_pct:     ['#4a9c5e', '#7ab87a', '#c9a227', '#bc7040', '#c94040'],
  passive_source:  ['#4a7cbc', '#8892b0', '#c9a227', '#c94040', '#4a9c5e'],
  earner_count:    ['#c94040', '#4a7cbc', '#4a9c5e', '#c9a227'],
  breadwinner:     ['#4a7cbc', '#4a9c9a', '#c9a227', '#e07070', '#a97cc4'],
  work_status:     ['#4a7cbc', '#6bcc6b', '#c9a227', '#e07070', '#c94040', '#888', '#4a4a6a'],
  educ:            ['#c94040', '#e07070', '#c9a227', '#4a9c5e', '#4a7cbc'],
  marst:           ['#4a7cbc', '#c9a227', '#e07070', '#888', '#4a9c5e'],
  has_roommate:    ['#8892b0', '#c9a227'],
  race_ethnicity:  ['#4a7cbc', '#4a9c5e', '#c9a227', '#bc6e4a', '#888'],
  city:            ['#4a7cbc', '#4a9c9a', '#8892b0', '#555'],
  burden:          ['#4a9c5e', '#c9a227', '#c94040', '#888'],
  multi_job_proxy: ['#666', '#c9a227', '#e07070', '#c94040'],
  age_bucket:      ['#8fbcdb', '#4a7cbc', '#4a9c9a', '#4a9c5e', '#c9a227', '#e07070', '#c94040', '#7a2020'],
  sex:             [null, '#4a7cbc', '#e07070'],
  kids:            ['#8892b0', '#4a9c5e'],
  metro:           ['#8892b0', '#4a7cbc', '#555'],
  housing:         ['#4a7cbc', '#4a9c5e', '#c9a227', '#888'],
  year:            ['#8892b0', '#4a7cbc', '#4a9c9a', '#c9a227', '#c94040'],
};
