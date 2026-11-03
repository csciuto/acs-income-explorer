"""Shared pieces of the preprocessor: reading IPUMS fixed-width extracts, weighted statistics with replicate-weight
standard errors, the browser sample, and Arrow output. Source-specific logic lives in acs.py and cps.py."""

import gzip
import sys
import time
import xml.etree.ElementTree as ET
from itertools import combinations

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.ipc

MIN_N = 50                 # cells with fewer sample households are suppressed
MEDIAN_BIN = 2_500         # the Census Bureau interpolates medians linearly within $2,500 income intervals

FIPS_NAMES = {
    1: "Alabama", 2: "Alaska", 4: "Arizona", 5: "Arkansas", 6: "California", 8: "Colorado",
    9: "Connecticut", 10: "Delaware", 11: "District of Columbia", 12: "Florida", 13: "Georgia",
    15: "Hawaii", 16: "Idaho", 17: "Illinois", 18: "Indiana", 19: "Iowa", 20: "Kansas",
    21: "Kentucky", 22: "Louisiana", 23: "Maine", 24: "Maryland", 25: "Massachusetts",
    26: "Michigan", 27: "Minnesota", 28: "Mississippi", 29: "Missouri", 30: "Montana",
    31: "Nebraska", 32: "Nevada", 33: "New Hampshire", 34: "New Jersey", 35: "New Mexico",
    36: "New York", 37: "North Carolina", 38: "North Dakota", 39: "Ohio", 40: "Oklahoma",
    41: "Oregon", 42: "Pennsylvania", 44: "Rhode Island", 45: "South Carolina",
    46: "South Dakota", 47: "Tennessee", 48: "Texas", 49: "Utah", 50: "Vermont", 51: "Virginia",
    53: "Washington", 54: "West Virginia", 55: "Wisconsin", 56: "Wyoming",
}
STATE_ABBR = {1: "AL", 2: "AK", 4: "AZ", 5: "AR", 6: "CA", 8: "CO", 9: "CT", 10: "DE", 11: "DC", 12: "FL", 13: "GA",
              15: "HI", 16: "ID", 17: "IL", 18: "IN", 19: "IA", 20: "KS", 21: "KY", 22: "LA", 23: "ME", 24: "MD",
              25: "MA", 26: "MI", 27: "MN", 28: "MS", 29: "MO", 30: "MT", 31: "NE", 32: "NV", 33: "NH", 34: "NJ",
              35: "NM", 36: "NY", 37: "NC", 38: "ND", 39: "OH", 40: "OK", 41: "OR", 42: "PA", 44: "RI", 45: "SC",
              46: "SD", 47: "TN", 48: "TX", 49: "UT", 50: "VT", 51: "VA", 53: "WA", 54: "WV", 55: "WI", 56: "WY"}
# Census regions: 1 Northeast, 2 Midwest, 3 South, 4 West
REGION_OF_STATE = {
    **{f: 1 for f in (9, 23, 25, 33, 44, 50, 34, 36, 42)},
    **{f: 2 for f in (17, 18, 26, 39, 55, 19, 20, 27, 29, 31, 38, 46)},
    **{f: 3 for f in (10, 11, 12, 13, 24, 37, 45, 51, 54, 1, 21, 28, 47, 5, 22, 40, 48)},
    **{f: 4 for f in (4, 8, 16, 30, 32, 35, 49, 56, 2, 6, 15, 41, 53)},
}
WKSWORK2_MIDPOINTS = {0: 0, 1: 7, 2: 20, 3: 33, 4: 43, 5: 48, 6: 51}


def step(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ---------------------------------------------------------------------------
# DDI and fixed-width records
# ---------------------------------------------------------------------------
def parse_ddi(ddi_path):
    """{name: {start (0-based), width, dcml, labels{int: str}}} for every single-location variable."""
    root = ET.parse(ddi_path).getroot()
    ns = {"d": root.tag.split("}")[0].strip("{")}
    out = {}
    for var in root.findall(".//d:var", ns):
        locs = var.findall("d:location", ns)
        if len(locs) != 1:
            continue  # group entries such as REPWT itself; REPWT1..n have their own
        loc = locs[0]
        labels = {}
        for c in var.findall("d:catgry", ns):
            v, lab = c.find("d:catValu", ns), c.find("d:labl", ns)
            if v is not None and lab is not None and v.text and v.text.strip().lstrip("-").isdigit():
                labels[int(v.text)] = (lab.text or "").strip()
        out[var.get("name")] = {"start": int(loc.get("StartPos")) - 1, "width": int(loc.get("width")),
                                "dcml": int(var.get("dcml") or 0), "labels": labels}
    return out


def require(spec, names, reps, n_rep, source):
    missing = [v for v in names if v not in spec]
    if any(f"{reps}{i}" not in spec for i in range(1, n_rep + 1)):
        missing.append(f"{reps}1-{n_rep} (household replicate weights)")
    if missing:
        sys.exit(f"The {source} extract is missing required variables: {', '.join(missing)}. See EXTRACT.md.")


def check_label(spec, var, code, words, source):
    """Stop if a code we rely on doesn't carry the label we expect (IPUMS renumbering would silently corrupt data)."""
    lab = spec[var]["labels"].get(code, "")
    if not any(w in lab.lower() for w in words):
        sys.exit(f"{source}: {var} code {code} is labelled {lab!r}; expected it to mention {' or '.join(words)!r}. "
                 "IPUMS may have changed its codes; update the codes in the pipeline.")


def parse_int(block):
    """Fixed-width ASCII digits (n x w uint8, optional leading '-', spaces) -> int64."""
    d = block.astype(np.int64) - 48
    neg = (block == 45).any(axis=1)
    d[(block == 32) | (block == 45)] = 0
    val = d @ (10 ** np.arange(block.shape[1] - 1, -1, -1, dtype=np.int64))
    val[neg] = -val[neg]
    return val


def niu_mask(raw, width):
    """IPUMS codes 'not in universe' / missing as all 9s (or 9...8) filling the column."""
    top = 10 ** width - 1
    return raw >= top - 1


def _chunks(dat_path, chunk_rows):
    opener = gzip.open if str(dat_path).endswith(".gz") else open
    with opener(dat_path, "rb") as fh:
        reclen = len(fh.readline())
    with opener(dat_path, "rb") as fh:
        while True:
            buf = fh.read(chunk_rows * reclen)
            if not buf:
                return
            if len(buf) % reclen:
                sys.exit(f"Record length mismatch: {len(buf)} bytes is not a multiple of {reclen}.")
            a = np.frombuffer(buf, dtype=np.uint8).reshape(-1, reclen)
            if not (a[:, -1] == 10).all():
                sys.exit("Records are not all the same length; is this an IPUMS rectangular .dat file?")
            yield a


def scan_values(dat_path, spec, var, chunk_rows=1_000_000):
    """{value: records} for one column, in one pass (used to find which samples an extract holds)."""
    s, counts = spec[var], {}
    for a in _chunks(dat_path, chunk_rows):
        vals, n = np.unique(parse_int(a[:, s["start"]:s["start"] + s["width"]]), return_counts=True)
        for v, k in zip(vals.tolist(), n.tolist()):
            counts[v] = counts.get(v, 0) + k
    return counts


def read_extract(dat_path, spec, want, rep_prefix, n_rep, chunk_rows=400_000, keep=None):
    """Every record has the same length, so a chunk of bytes is a 2-D uint8 array and columns are numpy slices.
    keep=(var, value) reads only records with that value (e.g. one sample out of several).
    Returns (persons: {var: int64 array}, rep: float32 [households x n_rep], from each household's first person)."""
    want = [v for v in dict.fromkeys(want) if v in spec]
    reps = [spec[f"{rep_prefix}{i}"] for i in range(1, n_rep + 1)]
    cols = {v: [] for v in want}
    rep_chunks, n = [], 0
    for a in _chunks(dat_path, chunk_rows):
        if keep:
            ks = spec[keep[0]]
            a = a[parse_int(a[:, ks["start"]:ks["start"] + ks["width"]]) == keep[1]]
            if not len(a):
                continue
        for v in want:
            s = spec[v]
            cols[v].append(parse_int(a[:, s["start"]:s["start"] + s["width"]]))
        ah = a[cols["PERNUM"][-1] == 1]
        rep = np.empty((len(ah), n_rep), dtype=np.float32)
        for i, s in enumerate(reps):
            rep[:, i] = parse_int(ah[:, s["start"]:s["start"] + s["width"]]) / 10 ** s["dcml"]
        rep_chunks.append(rep)
        n += len(a)
        print(f"  {n:,} person records", end="\r", flush=True)
    print()
    persons = {v: np.concatenate(c) for v, c in cols.items()}
    if not (persons["PERNUM"][0] == 1):
        sys.exit("The first record isn't a household's first person; is the file sorted as IPUMS delivers it?")
    return persons, np.concatenate(rep_chunks)


class Households:
    """Helpers for one person -> household collapse: household index, sums over members, householder values."""

    def __init__(self, p):
        self.first = p["PERNUM"] == 1
        self.hid = np.cumsum(self.first) - 1
        self.n = int(self.first.sum())

    def sum(self, x):
        return np.bincount(self.hid, weights=np.asarray(x, dtype=np.float64), minlength=self.n)

    def any(self, mask):
        return self.sum(mask) > 0

    def head(self, x):
        return np.asarray(x)[self.first]

    def size(self):
        return np.bincount(self.hid, minlength=self.n)


def income(p, spec, var):
    """An income item with 'not in universe' codes set to 0 (missing variables count as 0)."""
    if var not in p:
        return np.zeros(len(p["PERNUM"]), dtype=np.int64)
    raw = p[var]
    return np.where(niu_mask(raw, spec[var]["width"]), 0, raw)


# ---------------------------------------------------------------------------
# Derivations shared by both sources (inputs already harmonised)
# ---------------------------------------------------------------------------
def age_bucket(age):
    return np.digitize(age, [25, 30, 35, 40, 45, 55, 65]).astype(np.uint8)  # 0=<25 ... 7=65+


def breadwinner(own_wage, hh_wage):
    ratio = np.clip(own_wage / np.clip(hh_wage, 1, None), 0, 1)
    has_w = hh_wage > 0
    bw = np.full(len(hh_wage), 4, dtype=np.uint8)
    bw[has_w & (ratio > 0)] = 3
    bw[has_w & (ratio >= 0.40)] = 2
    bw[has_w & (ratio >= 0.60)] = 1
    bw[has_w & (ratio >= 0.90)] = 0
    return bw


def income_mix(hhinc, wage, sources):
    """passive_pct (wage share buckets) and passive_source (largest of SS/SSI, retirement, capital, assistance)."""
    share = wage / np.clip(hhinc, 1, None)
    pos = hhinc > 0
    pp = np.full(len(hhinc), 4, dtype=np.uint8)
    pp[pos & (share > 0)] = 3
    pp[pos & (share >= 0.25)] = 2
    pp[pos & (share >= 0.50)] = 1
    pp[pos & (share >= 0.75)] = 0
    src = np.column_stack(sources).astype(np.float64)
    has_passive = (share < 0.75) & (src.sum(1) > 0) & pos
    ps = np.where(has_passive, src.argmax(1), 4).astype(np.uint8)
    return pp, ps


def kids(nchild, yngch):
    yc = np.zeros(len(nchild), dtype=np.uint8)
    yc[(nchild > 0) & (yngch <= 4)] = 1
    yc[(nchild > 0) & (yngch >= 5) & (yngch <= 12)] = 2
    yc[(nchild > 0) & (yngch >= 13) & (yngch < 99)] = 3
    return (nchild > 0).astype(np.uint8), yc, np.clip(nchild, 0, 9).astype(np.uint8)


def marst_code(m, partner):
    marst = np.full(len(m), 4, dtype=np.uint8)          # never married
    marst[m == 1] = 0                                    # married, spouse present
    marst[np.isin(m, [2, 3, 4])] = 2                     # separated / divorced / spouse absent
    marst[m == 5] = 3                                    # widowed
    marst[partner & (m != 1)] = 1                        # cohabiting with an unmarried partner
    return marst


def work_status(working, unemployed, retired, full_time, full_year, wage_worker, self_employed, hours):
    ws = np.full(len(working), 6, dtype=np.uint8)        # not working
    ws[retired] = 5
    ws[unemployed] = 4
    ws[working & ~full_time] = 3                         # part-time
    ws[working & full_time & ~full_year] = 2             # full-time, part-year
    ws[working & full_time & full_year & self_employed] = 1
    ws[working & full_time & full_year & wage_worker] = 0
    hc = np.full(len(working), 3, dtype=np.uint8)
    hc[working & (hours >= 35)] = 0
    hc[working & (hours >= 15) & (hours < 35)] = 1
    hc[working & (hours < 15)] = 2
    return ws, hc


def dollars_u32(x):
    return np.clip(np.round(x), 0, 2**32 - 1).astype(np.uint32)


# ---------------------------------------------------------------------------
# Browser sample and Arrow
# ---------------------------------------------------------------------------
def stratified_sample(d, n_target, strata_cols=("year", "state"), seed=20260101):
    """Sample within each stratum in proportion to its size; reweight N_h / n_h so stratum totals hold."""
    rng = np.random.default_rng(seed)
    strata = np.zeros(len(d), dtype=np.int64)
    for c in strata_cols:
        strata = strata * 1_000_000 + d[c].astype(np.int64).values
    frac = min(1.0, n_target / max(1, len(d)))
    picks, wscale = [], []
    for _, idx in pd.Series(np.arange(len(d))).groupby(strata):
        idx = idx.values
        k = max(1, int(round(len(idx) * frac)))
        sel = rng.choice(idx, size=min(k, len(idx)), replace=False)
        picks.append(sel)
        wscale.append(np.full(len(sel), len(idx) / len(sel)))
    sel = np.concatenate(picks)
    out = d.iloc[sel].copy()
    out["weight"] = (out["weight"].values * np.concatenate(wscale)).astype(np.float32)
    out = out.sort_values(list(strata_cols), kind="stable").reset_index(drop=True)
    out["id"] = np.arange(len(out), dtype=np.uint32)
    return out


ARROW_TYPES = {"inc": pa.uint32(), "wage_inc": pa.uint32(), "passive_inc": pa.uint32(), "weight": pa.float32(),
               "id": pa.uint32(), "metro_area": pa.uint32(), "puma": pa.uint32()}


def write_arrow(df, columns, path):
    schema = pa.schema([(c, ARROW_TYPES.get(c, pa.uint8())) for c in columns])
    table = pa.Table.from_pandas(df[columns], schema=schema, preserve_index=False)
    with pa.OSFile(str(path), "wb") as sink, pa.ipc.new_file(sink, table.schema) as w:
        w.write_table(table)


# ---------------------------------------------------------------------------
# Weighted stats with replicate-weight standard errors
# ---------------------------------------------------------------------------
def w_quantile_sorted(v, cw, q):
    """v sorted ascending, cw its cumulative weights: smallest v with cw >= q * total."""
    i = int(np.searchsorted(cw, q * cw[-1]))
    return float(v[min(i, len(v) - 1)])


def binned_median(v, cum, total, j):
    """Median by linear interpolation within the $2,500 interval holding v[j], the first value whose cumulative
    weight reaches half. cum(k) = total weight of rows [:k]. Without this, respondents' round numbers (many
    households at exactly $80,000) pin the median, and its replicate estimates, to a single value."""
    x = v[min(j, len(v) - 1)]
    edge = np.floor(x / MEDIAN_BIN) * MEDIAN_BIN
    k0 = int(np.searchsorted(v, edge, "left"))
    k1 = int(np.searchsorted(v, edge + MEDIAN_BIN, "left"))
    below, upto = cum(k0), cum(k1)
    if upto <= below:
        return float(x)
    return float(edge + MEDIAN_BIN * min(1.0, max(0.0, (total / 2 - below) / (upto - below))))


def _chunked_dot(v, R, chunk=500_000):
    out = np.zeros(R.shape[1])
    for s in range(0, len(v), chunk):
        out += v[s:s + chunk] @ R[s:s + chunk].astype(np.float64)
    return out


class CellStats:
    """Holds households sorted by income once; computes stats for any subset given as a boolean mask.
    Replicate variance: factor * sum((theta_r - theta)^2), with factor 4/R for both the ACS's successive difference
    replication (R=80) and the CPS's Fay-adjusted BRR (R=160, Fay coefficient 0.5)."""

    def __init__(self, inc, weight, rep, extra=None):
        order = np.argsort(inc, kind="stable")
        self.order = order
        self.v = inc[order].astype(np.float64)
        self.w = weight[order].astype(np.float64)
        self.rep = rep[order]
        self.n_rep = rep.shape[1]
        self.factor = 4 / self.n_rep
        self.extra = extra   # fn(sorted idx, weights, total) -> dict of extra fields

    def sorted_mask(self, mask):
        return mask[self.order]

    def cell(self, smask, with_se=True):
        idx = np.flatnonzero(smask)
        n = len(idx)
        if n < MIN_N:
            return None
        v, w = self.v[idx], self.w[idx]
        cw = np.cumsum(w)
        tot = cw[-1]
        full_cum = lambda k: float(cw[k - 1]) if k > 0 else 0.0  # noqa: E731
        med = binned_median(v, full_cum, tot, int(np.searchsorted(cw, tot / 2)))
        mean = float(v @ w / tot)
        p25, p75 = w_quantile_sorted(v, cw, 0.25), w_quantile_sorted(v, cw, 0.75)
        sd = float(np.sqrt(max(0.0, (v * v) @ w / tot - mean * mean)))
        c = {"n": int(n), "n_rep": round(float(tot)), "med": round(med), "mean": round(mean),
             "p25": round(p25), "p75": round(p75), "iqr": round(p75 - p25), "sd": round(sd),
             "rel": 3 if n >= 500 else 2 if n >= 200 else 1}
        if self.extra:
            c.update(self.extra(idx, w, tot))
        if not with_se:
            return c
        R = self.rep[idx]
        rt = R.sum(axis=0, dtype=np.float64)
        rmean = (v @ R.astype(np.float64)) / rt if n < 200_000 else _chunked_dot(v, R) / rt
        # replicate medians: only rows near the full-sample median can hold them, so cumulate a window
        # (widened to the $2,500 bins either side of the median's, which the interpolation reads)
        edge = np.floor(med / MEDIAN_BIN) * MEDIAN_BIN
        lo = min(int(np.searchsorted(cw, 0.40 * tot)), int(np.searchsorted(v, edge - MEDIAN_BIN, "left")))
        hi = min(n, max(int(np.searchsorted(cw, 0.60 * tot)) + 1,
                        int(np.searchsorted(v, edge + 2 * MEDIAN_BIN, "left")) + 1))
        base = R[:lo].sum(axis=0, dtype=np.float64)
        rc = base + np.cumsum(R[lo:hi], axis=0, dtype=np.float64)   # rc[i] = sum of R[:lo + i + 1]
        rmed = np.empty(self.n_rep)
        for r in range(self.n_rep):
            def cum(k, r=r):
                if k == lo:
                    return float(base[r])
                if lo < k <= hi:
                    return float(rc[k - lo - 1, r])
                return float(R[:k, r].sum(dtype=np.float64))
            j = int(np.searchsorted(rc[:, r], 0.5 * rt[r]))
            if j >= len(rc) or (j == 0 and base[r] >= 0.5 * rt[r]):  # outside the window: do it in full
                j = int(np.searchsorted(np.cumsum(R[:, r], dtype=np.float64), 0.5 * rt[r]))
            else:
                j += lo
            rmed[r] = binned_median(v, cum, rt[r], j)
        se_med = float(np.sqrt(self.factor * ((rmed - med) ** 2).sum()))
        se_mean = float(np.sqrt(self.factor * ((rmean - mean) ** 2).sum()))
        c.update({"se_med": round(se_med), "se_mean": round(se_mean),
                  "ci_lo": round(mean - 1.96 * se_mean), "ci_hi": round(mean + 1.96 * se_mean)})
        return c


def build_key(scope, filt):
    return "|".join(([scope] if scope else []) + [f"{k}={v}" for k, v in sorted(filt.items())])


def wage_share_extra(d, order):
    wage0 = (d["passive_pct"].values == 0)[order]
    return lambda idx, w, tot: {"wage_pct": round(float(w[wage0[idx]].sum() / tot), 4)}


def compute_stats(d, rep, dims, metro_min_n=2000, log=True):
    """National 1-D and 2-D, state 1-D, metro overall (+1-D for big metros). dims: {short: (column, values)}."""
    cs = CellStats(d["inc"].values, d["weight"].values, rep)
    cs.extra = wage_share_extra(d, cs.order)
    col = lambda c: d[c].values[cs.order]  # noqa: E731
    stats, t = {}, time.time()

    def add(key, mask):
        c = cs.cell(mask)
        if c:
            stats[key] = c

    add("national", np.ones(len(d), dtype=bool))
    eq = {(dn, v): col(c) == v for dn, (c, vals) in dims.items() for v in vals}
    for dn, (_, vals) in dims.items():
        for v in vals:
            add(build_key("national", {dn: v}), eq[(dn, v)])
    names = list(dims)
    for a, b in combinations(names, 2):
        for va in dims[a][1]:
            for vb in dims[b][1]:
                add(build_key("national", {a: va, b: vb}), eq[(a, va)] & eq[(b, vb)])
    if log:
        step(f"  national done ({len(stats):,} cells, {time.time() - t:.0f}s)")
    scoped = [n for n in names if n != "region"]
    st = col("state")
    for code in sorted(np.unique(st)):
        sm = st == code
        add(f"state={int(code)}", sm)
        for dn in scoped:
            for v in dims[dn][1]:
                add(build_key(f"state={int(code)}", {dn: v}), sm & eq[(dn, v)])
    if log:
        step(f"  states done ({len(stats):,} cells, {time.time() - t:.0f}s)")
    if "metro_area" in d:
        ma = col("metro_area")
        codes, counts = np.unique(ma, return_counts=True)
        for code, cnt in zip(codes, counts):
            if code == 0:
                continue
            mm = ma == code
            add(f"metro={int(code)}", mm)
            if cnt >= metro_min_n:
                for dn in scoped:
                    for v in dims[dn][1]:
                        add(build_key(f"metro={int(code)}", {dn: v}), mm & eq[(dn, v)])
        if log:
            step(f"  metro areas done ({len(stats):,} cells, {time.time() - t:.0f}s)")
    return stats


LOCAL_FIELDS = ("n", "n_rep", "med", "mean", "p25", "p75", "rel", "se_med")


def trim(c):
    """Local-area cells keep only what the page shows; there are ~200,000 of them."""
    return {k: c[k] for k in LOCAL_FIELDS if k in c}


def compute_local_stats(d, rep, dims, by="puma", group="state"):
    """Per-state dicts of local-area (PUMA) stats: overall and every 1-D value. {state: {key: cell}}."""
    out = {}
    for code in sorted(d[group].unique()):
        sel = (d[group] == code).values
        sd = d.loc[sel].reset_index(drop=True)
        cs = CellStats(sd["inc"].values, sd["weight"].values, rep[sel])
        cs.extra = wage_share_extra(sd, cs.order)
        loc = sd[by].values[cs.order]
        stats = {}
        for area in np.unique(loc):
            am = loc == area
            c = cs.cell(am)
            if not c:
                continue
            stats[f"{by}={int(area)}"] = trim(c)
            for dn, (colname, vals) in dims.items():
                if dn in ("region", "city"):
                    continue
                cv = sd[colname].values[cs.order]
                for v in vals:
                    c = cs.cell(am & (cv == v))
                    if c:
                        stats[build_key(f"{by}={int(area)}", {dn: v})] = trim(c)
        out[int(code)] = stats
    return out


def weighted_median(values, weights):
    o = np.argsort(values)
    cw = np.cumsum(weights[o])
    return float(values[o][min(int(np.searchsorted(cw, cw[-1] / 2)), len(o) - 1)])
