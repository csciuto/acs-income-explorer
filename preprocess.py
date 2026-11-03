#!/usr/bin/env python3
"""
ACS preprocessor for the ACS Income Explorer.

Reads an IPUMS USA extract (fixed-width .dat.gz + DDI .xml; see EXTRACT.md), builds one row per
household, derives the explorer's variables, and writes to the output directory:

    national.arrow           stratified sample of households (by year x state) for the browser
    stats_precomputed.json   exact weighted stats from ALL households, with replicate-weight SEs
    codebook.json            labels, states, metro areas, years

Usage:
    python preprocess.py --input usa_00017.dat.gz --ddi usa_00017.xml --output-dir ./docs/data

Dollar amounts are converted to constant dollars of the latest survey year with CPI99
(--nominal keeps each year's own dollars). Weights are divided by the number of pooled years, so
weighted counts describe an average year.
"""

import argparse
import gzip
import json
import sys
import time
import xml.etree.ElementTree as ET
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.ipc

N_REP = 80                  # ACS household replicate weights (successive difference replication)
SDR_FACTOR = 4 / N_REP      # Var = 4/80 * sum((theta_r - theta)^2)
MIN_N = 50                  # cells with fewer sample households are suppressed
DEFAULT_SAMPLE = 300_000    # households in national.arrow

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
# Census regions: 1 Northeast, 2 Midwest, 3 South, 4 West
REGION_OF_STATE = {
    **{f: 1 for f in (9, 23, 25, 33, 44, 50, 34, 36, 42)},
    **{f: 2 for f in (17, 18, 26, 39, 55, 19, 20, 27, 29, 31, 38, 46)},
    **{f: 3 for f in (10, 11, 12, 13, 24, 37, 45, 51, 54, 1, 21, 28, 47, 5, 22, 40, 48)},
    **{f: 4 for f in (4, 8, 16, 30, 32, 35, 49, 56, 2, 6, 15, 41, 53)},
}
WKSWORK2_MIDPOINTS = {0: 0, 1: 7, 2: 20, 3: 33, 4: 43, 5: 48, 6: 51}

# Variables the extract must contain (EXTRACT.md). REPWT1..80 are checked separately.
HOUSEHOLD_VARS = ["YEAR", "SERIAL", "HHWT", "GQ", "CPI99", "STATEFIP", "MET2013", "METRO",
                  "HHINCOME", "OWNERSHP", "MORTGAGE", "RENTGRS", "OWNCOST"]
PERSON_VARS = ["PERNUM", "RELATE", "RELATED", "AGE", "SEX", "MARST", "RACE", "HISPAN", "EDUCD",
               "EMPSTAT", "CLASSWKR", "WKSWORK2", "UHRSWORK", "NCHILD", "YNGCH",
               "INCTOT", "INCWAGE", "INCBUS00", "INCSS", "INCSUPP", "INCWELFR", "INCRETIR",
               "INCINVST", "INCOTHER"]
INCOME_VARS = ["INCWAGE", "INCBUS00", "INCSS", "INCSUPP", "INCWELFR", "INCRETIR", "INCINVST", "INCOTHER"]
TOPCODED_VARS = ["INCWAGE", "INCBUS00", "INCRETIR", "INCINVST"]

# The Census Bureau's ADJINC for each 1-year sample, which IPUMS offers as ADJUST but does not apply: ACS incomes
# are in dollars of the months each household was interviewed, and ADJUST puts them into the survey year's dollars.
# Source: https://usa.ipums.org/usa/acsincadj.shtml. Used when the extract doesn't include ADJUST itself.
ADJUST_BY_YEAR = {2021: 1.029928, 2022: 1.042311, 2023: 1.019518, 2024: 1.015250}

# RELATED codes (checked against the DDI labels at load time)
REL_PARTNER = 1114          # Unmarried Partner
REL_ROOMMATE = (1115, 1241)  # Housemate/Roommate; Roomers/boarders/lodgers


def step(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ---------------------------------------------------------------------------
# DDI
# ---------------------------------------------------------------------------
def parse_ddi(ddi_path):
    """{name: {start (0-based), width, dcml, labels{int: str}}} for every single-location variable."""
    root = ET.parse(ddi_path).getroot()
    ns = {"d": root.tag.split("}")[0].strip("{")}
    out = {}
    for var in root.findall(".//d:var", ns):
        locs = var.findall("d:location", ns)
        if len(locs) != 1:
            continue  # group entries such as REPWT itself; REPWT1..80 have their own
        loc = locs[0]
        labels = {}
        for c in var.findall("d:catgry", ns):
            v, lab = c.find("d:catValu", ns), c.find("d:labl", ns)
            if v is not None and lab is not None and v.text and v.text.strip().lstrip("-").isdigit():
                labels[int(v.text)] = (lab.text or "").strip()
        out[var.get("name")] = {"start": int(loc.get("StartPos")) - 1, "width": int(loc.get("width")),
                                "dcml": int(var.get("dcml") or 0), "labels": labels}
    return out


def check_extract(spec):
    """Stop with a clear message if the extract doesn't have what EXTRACT.md asks for."""
    missing = [v for v in HOUSEHOLD_VARS + PERSON_VARS if v not in spec]
    reps = [f"REPWT{i}" for i in range(1, N_REP + 1)]
    if any(r not in spec for r in reps):
        missing.append(f"REPWT1-{N_REP} (household replicate weights)")
    if missing:
        sys.exit("The extract is missing required variables: " + ", ".join(missing) + ". See EXTRACT.md.")
    rel = spec["RELATED"]["labels"]
    expect = {REL_PARTNER: "partner", 1115: "room", 1241: "roomer"}
    for code, word in expect.items():
        if word not in rel.get(code, "").lower():
            sys.exit(f"RELATED code {code} is labelled {rel.get(code)!r}; expected it to mention '{word}'. "
                     "IPUMS may have renumbered relationship codes; update REL_* in preprocess.py.")


# ---------------------------------------------------------------------------
# Fixed-width reading: every record has the same length, so a chunk of bytes is a 2-D uint8 array
# ---------------------------------------------------------------------------
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


def read_extract(dat_path, spec, chunk_rows=400_000):
    """Returns (persons: dict of int64 arrays, rep: float32 [households x 80], one row per PERNUM==1)."""
    want = HOUSEHOLD_VARS + PERSON_VARS + (["ADJUST"] if "ADJUST" in spec else [])
    reps = [spec[f"REPWT{i}"] for i in range(1, N_REP + 1)]
    opener = gzip.open if str(dat_path).endswith(".gz") else open
    with opener(dat_path, "rb") as fh:
        first = fh.readline()
    reclen = len(first)  # including the newline
    cols = {v: [] for v in want}
    rep_chunks = []
    n = 0
    with opener(dat_path, "rb") as fh:
        while True:
            buf = fh.read(chunk_rows * reclen)
            if not buf:
                break
            if len(buf) % reclen:
                sys.exit(f"Record length mismatch: {len(buf)} bytes is not a multiple of {reclen}.")
            a = np.frombuffer(buf, dtype=np.uint8).reshape(-1, reclen)
            if not (a[:, -1] == 10).all():
                sys.exit("Records are not all the same length; is this an IPUMS rectangular .dat file?")
            for v in want:
                s = spec[v]
                cols[v].append(parse_int(a[:, s["start"]:s["start"] + s["width"]]))
            hh = cols["PERNUM"][-1] == 1
            ah = a[hh]
            rep = np.empty((len(ah), N_REP), dtype=np.float32)
            for i, s in enumerate(reps):
                rep[:, i] = parse_int(ah[:, s["start"]:s["start"] + s["width"]]) / 10 ** s["dcml"]
            rep_chunks.append(rep)
            n += len(a)
            print(f"  {n:,} person records", end="\r", flush=True)
    print()
    persons = {v: np.concatenate(c) for v, c in cols.items()}
    return persons, np.concatenate(rep_chunks)


# ---------------------------------------------------------------------------
# Households
# ---------------------------------------------------------------------------
def build_households(p, spec, nominal=False):
    """Collapse person records into one row per household. Returns a DataFrame (households incl. GQ)."""
    first = p["PERNUM"] == 1
    if first.sum() == 0 or not first[0]:
        sys.exit("The first record isn't a household's first person; is the file sorted as IPUMS delivers it?")
    hid = np.cumsum(first) - 1
    nh = int(first.sum())

    def hsum(x):
        return np.bincount(hid, weights=x.astype(np.float64), minlength=nh)

    inc = {}
    for v in INCOME_VARS:
        raw = p[v]
        inc[v] = np.where(niu_mask(raw, spec[v]["width"]), 0, raw)
    wage_bus = np.clip(inc["INCWAGE"] + inc["INCBUS00"], 0, None)

    # topcodes: ACS replaces each income item above a state's cutoff with the state's mean of those values,
    # so a topcoded amount is the (year, state) maximum and shows up for several people
    key = (p["YEAR"] - 2000) * 100 + p["STATEFIP"]
    top = np.zeros(len(key), dtype=bool)
    for v in TOPCODED_VARS:
        s = pd.Series(inc[v]).groupby(key).transform("max").values
        top |= (inc[v] == s) & (inc[v] > 0)
    rel = p["RELATED"]

    h = pd.DataFrame({k: p[k][first] for k in HOUSEHOLD_VARS})
    # ADJUST is optional; read it if the extract has it
    for k in ["RELATE", "AGE", "SEX", "MARST", "RACE", "HISPAN", "EDUCD", "EMPSTAT", "CLASSWKR",
              "WKSWORK2", "UHRSWORK", "NCHILD", "YNGCH"]:
        h[k] = p[k][first]
    h["own_ss"] = inc["INCSS"][first]
    h["own_wage"] = wage_bus[first]
    h["hh_wage"] = hsum(wage_bus)
    h["hh_ss"] = hsum(inc["INCSS"] + inc["INCSUPP"])
    h["hh_retir"] = hsum(inc["INCRETIR"])
    h["hh_capital"] = hsum(np.clip(inc["INCINVST"], 0, None))
    h["hh_welfare"] = hsum(inc["INCWELFR"])
    h["earners"] = hsum((wage_bus > 0).astype(np.int8))
    h["size"] = np.bincount(hid, minlength=nh)
    h["partner"] = hsum(rel == REL_PARTNER) > 0
    h["roommate"] = hsum(np.isin(rel, REL_ROOMMATE)) > 0
    h["topcoded"] = hsum(top) > 0
    h["HHWT"] = h["HHWT"] / 10 ** spec["HHWT"]["dcml"]
    h["CPI99"] = h["CPI99"] / 10 ** spec["CPI99"]["dcml"]

    # survey-year dollars: ADJUST (Census ADJINC); constant dollars: then x CPI99(year) / CPI99(latest year)
    if "ADJUST" in spec:
        h["adjust"] = p["ADJUST"][first] / 10 ** spec["ADJUST"]["dcml"]
    else:
        missing = sorted(set(h["YEAR"].unique()) - set(ADJUST_BY_YEAR))
        if missing:
            sys.exit(f"No ADJUST factor for {missing}: add ADJUST to the extract or to ADJUST_BY_YEAR "
                     "(values at https://usa.ipums.org/usa/acsincadj.shtml).")
        h["adjust"] = h["YEAR"].map(ADJUST_BY_YEAR)
    latest = h["YEAR"].max()
    cpi_latest = h.loc[h["YEAR"] == latest, "CPI99"].iloc[0]
    h["dollar_factor"] = h["adjust"] * (1.0 if nominal else h["CPI99"] / cpi_latest)
    return h


def derive(h, spec):
    """The explorer's variables, one row per household (only real households, GQ excluded)."""
    keep = h["GQ"].isin([1, 2, 5]).values & ~niu_mask(h["HHINCOME"].values, spec["HHINCOME"]["width"])
    h = h.loc[keep].reset_index(drop=True)
    years = sorted(h["YEAR"].unique())
    f = h["dollar_factor"].values
    d = pd.DataFrame({"id": np.arange(len(h), dtype=np.uint32)})
    hhinc = h["HHINCOME"].values * f
    wage = h["hh_wage"].values * f
    d["inc"] = np.clip(np.round(hhinc), 0, 2**32 - 1).astype(np.uint32)
    d["wage_inc"] = np.clip(np.round(wage), 0, 2**32 - 1).astype(np.uint32)
    d["passive_inc"] = np.clip(np.round(hhinc - wage), 0, 2**32 - 1).astype(np.uint32)
    d["weight"] = (h["HHWT"].values / len(years)).astype(np.float32)
    d["state"] = h["STATEFIP"].astype(np.uint8)
    d["year"] = np.searchsorted(years, h["YEAR"].values).astype(np.uint8)
    d["region"] = h["STATEFIP"].map(REGION_OF_STATE).fillna(0).astype(np.uint8)

    age = h["AGE"].values
    d["age_bucket"] = np.digitize(age, [25, 30, 35, 40, 45, 55, 65]).astype(np.uint8)  # 0=<25 ... 7=65+
    d["sex"] = h["SEX"].astype(np.uint8)

    m = h["MARST"].values
    partner = h["partner"].values
    marst = np.full(len(h), 4, dtype=np.uint8)          # never married
    marst[m == 1] = 0                                    # married, spouse present
    marst[np.isin(m, [2, 3, 4])] = 2                     # separated / divorced / spouse absent
    marst[m == 5] = 3                                    # widowed
    marst[partner & (m != 1)] = 1                        # cohabiting with an unmarried partner
    d["marst"] = marst

    e = h["EDUCD"].values
    educ = np.zeros(len(h), dtype=np.uint8)              # less than high school
    educ[(e >= 62) & (e <= 64)] = 1                      # HS diploma or GED
    educ[(e >= 65) & (e <= 100)] = 2                     # some college, associate's
    educ[e == 101] = 3                                   # bachelor's
    educ[(e >= 110) & (e < 999)] = 4                     # graduate / professional
    d["educ"] = educ

    # METRO: 1 not in metro, 3 suburb, 5 principal city, 2/4 can't tell
    mt = h["METRO"].values
    d["metro"] = np.where(mt == 1, 0, np.where(np.isin(mt, [3, 4, 5]), 1, 2)).astype(np.uint8)
    d["city"] = np.select([mt == 5, mt == 3, mt == 1], [0, 1, 2], 3).astype(np.uint8)
    d["metro_area"] = h["MET2013"].astype(np.uint32)

    nchild = h["NCHILD"].values
    yng = h["YNGCH"].values
    d["kids"] = (nchild > 0).astype(np.uint8)
    yc = np.zeros(len(h), dtype=np.uint8)
    yc[(nchild > 0) & (yng <= 4)] = 1
    yc[(nchild > 0) & (yng >= 5) & (yng <= 12)] = 2
    yc[(nchild > 0) & (yng >= 13) & (yng < 99)] = 3
    d["youngest_child"] = yc
    d["n_children"] = np.clip(nchild, 0, 9).astype(np.uint8)

    emp, cls = h["EMPSTAT"].values, h["CLASSWKR"].values
    wks, hrs = h["WKSWORK2"].values, h["UHRSWORK"].values
    working = emp == 1
    full_time, full_year = hrs >= 35, wks >= 5
    ws = np.full(len(h), 6, dtype=np.uint8)              # not working
    ws[(emp == 3) & (h["own_ss"].values > 0) & (age >= 55)] = 5  # retired
    ws[emp == 2] = 4                                     # unemployed
    ws[working & ~full_time] = 3                         # part-time
    ws[working & full_time & ~full_year] = 2             # full-time, part-year
    ws[working & full_time & full_year & (cls == 1)] = 1  # full-time self-employed
    ws[working & full_time & full_year & (cls == 2)] = 0  # full-time wage
    d["work_status"] = ws
    hc = np.full(len(h), 3, dtype=np.uint8)
    hc[working & (hrs >= 35)] = 0
    hc[working & (hrs >= 15) & (hrs < 35)] = 1
    hc[working & (hrs < 15)] = 2
    d["hours_category"] = hc
    d["weeks_worked"] = pd.Series(wks).map(WKSWORK2_MIDPOINTS).fillna(0).astype(np.uint8).values

    d["earner_count"] = np.clip(h["earners"].values, 0, 3).astype(np.uint8)
    hw = h["own_wage"].values
    ratio = np.clip(hw / np.clip(h["hh_wage"].values, 1, None), 0, 1)
    has_w = h["hh_wage"].values > 0
    bw = np.full(len(h), 4, dtype=np.uint8)
    bw[has_w & (ratio > 0)] = 3
    bw[has_w & (ratio >= 0.40)] = 2
    bw[has_w & (ratio >= 0.60)] = 1
    bw[has_w & (ratio >= 0.90)] = 0
    d["breadwinner"] = bw

    share = wage / np.clip(hhinc, 1, None)
    pos = hhinc > 0
    pp = np.full(len(h), 4, dtype=np.uint8)
    pp[pos & (share > 0)] = 3
    pp[pos & (share >= 0.25)] = 2
    pp[pos & (share >= 0.50)] = 1
    pp[pos & (share >= 0.75)] = 0
    d["passive_pct"] = pp

    src = np.column_stack([h["hh_ss"], h["hh_retir"], h["hh_capital"], h["hh_welfare"]]).astype(np.float64)
    has_passive = (share < 0.75) & (src.sum(1) > 0) & pos
    d["passive_source"] = np.where(has_passive, src.argmax(1), 4).astype(np.uint8)

    re = np.full(len(h), 4, dtype=np.uint8)
    race, hisp = h["RACE"].values, h["HISPAN"].values
    nh = ~np.isin(hisp, [1, 2, 3, 4])
    re[(race == 1) & nh] = 0
    re[(race == 2) & nh] = 1
    re[np.isin(race, [4, 5, 6]) & nh] = 3
    re[~nh] = 2
    d["race_ethnicity"] = re

    own, mort = h["OWNERSHP"].values, h["MORTGAGE"].values
    housing = np.full(len(h), 3, dtype=np.uint8)
    housing[(own == 1) & np.isin(mort, [3, 4])] = 0
    housing[(own == 1) & (mort == 1)] = 1
    housing[own == 2] = 2
    d["housing"] = housing

    # housing cost burden: 12 x monthly gross rent or owner costs, as a share of household income
    rent, oc = h["RENTGRS"].values, h["OWNCOST"].values
    monthly = np.where(own == 2, rent, np.where((own == 1) & ~niu_mask(oc, spec["OWNCOST"]["width"]), oc, 0))
    cost_share = 12 * monthly / np.clip(h["HHINCOME"].values * h["adjust"].values, 1, None)  # survey-year dollars
    burden = np.full(len(h), 3, dtype=np.uint8)          # N/A: no cash costs recorded, or no income
    ok = (monthly > 0) & (h["HHINCOME"].values > 0)
    burden[ok] = np.select([cost_share[ok] < 0.30, cost_share[ok] < 0.50], [0, 1], 2)
    d["burden"] = burden

    d["topcoded"] = h["topcoded"].astype(np.uint8)
    d["has_roommate"] = h["roommate"].astype(np.uint8)
    d["hh_size"] = np.clip(h["size"].values, 1, 20).astype(np.uint8)
    return d, keep, years


# ---------------------------------------------------------------------------
# Browser sample
# ---------------------------------------------------------------------------
def stratified_sample(d, n_target, seed=20260101):
    """Sample households within each year x state stratum in proportion to its size; reweight N_h / n_h."""
    rng = np.random.default_rng(seed)
    strata = d["year"].astype(np.int64).values * 100 + d["state"].values
    frac = min(1.0, n_target / len(d))
    picks, wscale = [], []
    for s, idx in pd.Series(np.arange(len(d))).groupby(strata):
        idx = idx.values
        k = max(1, int(round(len(idx) * frac)))
        sel = rng.choice(idx, size=min(k, len(idx)), replace=False)
        picks.append(sel)
        wscale.append(np.full(len(sel), len(idx) / len(sel)))
    sel = np.concatenate(picks)
    out = d.iloc[sel].copy()
    out["weight"] = (out["weight"].values * np.concatenate(wscale)).astype(np.float32)
    out = out.sort_values(["year", "state"], kind="stable").reset_index(drop=True)
    out["id"] = np.arange(len(out), dtype=np.uint32)
    return out


ARROW_SCHEMA = pa.schema([
    ("id", pa.uint32()), ("inc", pa.uint32()), ("wage_inc", pa.uint32()), ("weight", pa.float32()),
    ("state", pa.uint8()), ("year", pa.uint8()), ("age_bucket", pa.uint8()), ("sex", pa.uint8()),
    ("marst", pa.uint8()), ("educ", pa.uint8()), ("region", pa.uint8()), ("metro", pa.uint8()),
    ("city", pa.uint8()), ("metro_area", pa.uint32()),
    ("kids", pa.uint8()), ("youngest_child", pa.uint8()), ("work_status", pa.uint8()),
    ("hours_category", pa.uint8()), ("weeks_worked", pa.uint8()), ("topcoded", pa.uint8()),
    ("race_ethnicity", pa.uint8()), ("housing", pa.uint8()), ("burden", pa.uint8()),
    ("has_roommate", pa.uint8()), ("earner_count", pa.uint8()), ("breadwinner", pa.uint8()),
    ("passive_pct", pa.uint8()), ("passive_source", pa.uint8()), ("hh_size", pa.uint8()),
    ("n_children", pa.uint8()), ("passive_inc", pa.uint32()),
])


def write_arrow(df, path):
    table = pa.Table.from_pandas(df[ARROW_SCHEMA.names], schema=ARROW_SCHEMA, preserve_index=False)
    with pa.OSFile(str(path), "wb") as sink, pa.ipc.new_file(sink, table.schema) as w:
        w.write_table(table)


# ---------------------------------------------------------------------------
# Weighted stats with replicate-weight standard errors
# ---------------------------------------------------------------------------
def w_quantile_sorted(v, cw, q):
    """v sorted ascending, cw its cumulative weights: smallest v with cw >= q * total."""
    i = int(np.searchsorted(cw, q * cw[-1]))
    return float(v[min(i, len(v) - 1)])


MEDIAN_BIN = 2_500  # the Census Bureau interpolates medians linearly within $2,500 income intervals


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


class CellStats:
    """Holds households sorted by income once; computes stats for any subset given as a boolean mask."""

    def __init__(self, inc, weight, rep):
        order = np.argsort(inc, kind="stable")
        self.order = order
        self.v = inc[order].astype(np.float64)
        self.w = weight[order].astype(np.float64)
        self.rep = rep[order]

    def sorted_mask(self, mask):
        return mask[self.order]

    def cell(self, smask, with_se=True, extra=None):
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
        if extra:
            c.update(extra(idx, w, tot))
        if with_se:
            R = self.rep[idx]                                  # n x 80, float32
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
            rmed = np.empty(N_REP)
            for r in range(N_REP):
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
            se_med = float(np.sqrt(SDR_FACTOR * ((rmed - med) ** 2).sum()))
            se_mean = float(np.sqrt(SDR_FACTOR * ((rmean - mean) ** 2).sum()))
            c["se_med"] = round(se_med)
            c["se_mean"] = round(se_mean)
            c["ci_lo"] = round(mean - 1.96 * se_mean)
            c["ci_hi"] = round(mean + 1.96 * se_mean)
        return c


def _chunked_dot(v, R, chunk=500_000):
    out = np.zeros(R.shape[1])
    for s in range(0, len(v), chunk):
        out += v[s:s + chunk] @ R[s:s + chunk].astype(np.float64)
    return out


# dim short name -> (column, values). Order is the order keys are built in (keys sort them anyway).
DIMS = {
    "age": ("age_bucket", list(range(8))),
    "sex": ("sex", [1, 2]),
    "marst": ("marst", list(range(5))),
    "educ": ("educ", list(range(5))),
    "region": ("region", [1, 2, 3, 4]),
    "city": ("city", [0, 1, 2]),
    "work": ("work_status", list(range(7))),
    "kids": ("kids", [0, 1]),
    "race": ("race_ethnicity", list(range(5))),
    "house": ("housing", [0, 1, 2]),
    "burden": ("burden", [0, 1, 2]),
    "earners": ("earner_count", [0, 1, 2, 3]),
    "bread": ("breadwinner", list(range(5))),
    "ppct": ("passive_pct", list(range(5))),
    "psrc": ("passive_source", list(range(5))),
    "year": ("year", None),  # values filled in from the data
}


def build_key(scope, filt):
    return "|".join(([scope] if scope else []) + [f"{k}={v}" for k, v in sorted(filt.items())])


def compute_stats(d, rep, years, metro_min_n=2000):
    dims = dict(DIMS)
    dims["year"] = ("year", list(range(len(years))))
    cs = CellStats(d["inc"].values, d["weight"].values, rep)
    sorted_col = {col: d[col].values[cs.order] for col, _ in dims.values()}
    sorted_col["state"] = d["state"].values[cs.order]
    sorted_col["metro_area"] = d["metro_area"].values[cs.order]
    wage0 = (d["passive_pct"].values == 0)[cs.order]

    def extra(idx, w, tot):
        return {"wage_pct": round(float(w[wage0[idx]].sum() / tot), 4)}

    stats = {}
    t = time.time()

    def add(key, mask, se=True):
        c = cs.cell(mask, with_se=se, extra=extra)
        if c:
            stats[key] = c
        return c

    allm = np.ones(len(d), dtype=bool)
    add("national", allm)
    eq = {}
    for dn, (col, vals) in dims.items():
        for v in vals:
            eq[(dn, v)] = sorted_col[col] == v
            add(build_key("national", {dn: v}), eq[(dn, v)])
    step(f"  national 1-D done ({len(stats)} cells, {time.time() - t:.0f}s)")
    names = list(dims)
    for a, b in combinations(names, 2):
        for va in dims[a][1]:
            for vb in dims[b][1]:
                add(build_key("national", {a: va, b: vb}), eq[(a, va)] & eq[(b, vb)])
    step(f"  national 2-D done ({len(stats)} cells, {time.time() - t:.0f}s)")

    scoped = [n for n in names if n != "region"]
    for code in sorted(np.unique(sorted_col["state"])):
        sm = sorted_col["state"] == code
        add(f"state={int(code)}", sm)
        for dn in scoped:
            for v in dims[dn][1]:
                add(build_key(f"state={int(code)}", {dn: v}), sm & eq[(dn, v)])
    step(f"  states done ({len(stats)} cells, {time.time() - t:.0f}s)")

    ma, counts = np.unique(sorted_col["metro_area"], return_counts=True)
    for code, cnt in zip(ma, counts):
        if code == 0:
            continue  # not in an identifiable metro area
        mm = sorted_col["metro_area"] == code
        add(f"metro={int(code)}", mm)
        if cnt >= metro_min_n:
            for dn in scoped:
                for v in dims[dn][1]:
                    add(build_key(f"metro={int(code)}", {dn: v}), mm & eq[(dn, v)])
    step(f"  metro areas done ({len(stats)} cells, {time.time() - t:.0f}s)")

    return stats


# ---------------------------------------------------------------------------
# Codebook
# ---------------------------------------------------------------------------
LABELS = {
    "age_bucket": {"0": "Under 25", "1": "25–29", "2": "30–34", "3": "35–39", "4": "40–44", "5": "45–54",
                   "6": "55–64", "7": "65+"},
    "sex": {"1": "Male", "2": "Female"},
    "marst": {"0": "Married", "1": "Cohabiting", "2": "Sep./Divorced", "3": "Widowed", "4": "Never married"},
    "educ": {"0": "< HS", "1": "HS diploma", "2": "Some college", "3": "Bachelor's", "4": "Graduate"},
    "region": {"1": "Northeast", "2": "Midwest", "3": "South", "4": "West"},
    "metro": {"0": "Non-metro", "1": "Metro", "2": "Mixed/unknown"},
    "city": {"0": "Principal city", "1": "Suburb", "2": "Non-metro", "3": "Metro, city status unknown"},
    "work_status": {"0": "FT wage", "1": "FT self-emp", "2": "FT part-year", "3": "Part-time", "4": "Unemployed",
                    "5": "Retired", "6": "Not working"},
    "earner_count": {"0": "No earners", "1": "One earner", "2": "Two earners", "3": "Three or more"},
    "breadwinner": {"0": "Sole/dominant", "1": "Primary earner", "2": "Co-earner", "3": "Secondary earner",
                    "4": "Non-earner"},
    "passive_pct": {"0": "≥75% wages", "1": "50–74% wages", "2": "25–49% mixed", "3": "<25% wages",
                    "4": "Entirely passive"},
    "passive_source": {"0": "SS/SSI", "1": "Retirement/pension", "2": "Capital (int/div/rent)",
                       "3": "Public assistance", "4": "Primarily wages"},
    "kids": {"0": "No children", "1": "Kids present"},
    "youngest_child": {"0": "No children", "1": "Under 5", "2": "5–12", "3": "13–17"},
    "hours_category": {"0": "Full-time", "1": "Part-time", "2": "Marginal", "3": "N/A"},
    "race_ethnicity": {"0": "White non-Hisp", "1": "Black non-Hisp", "2": "Hispanic", "3": "Asian/PI non-Hisp",
                       "4": "Other/Multiracial"},
    "has_roommate": {"0": "No roommates", "1": "Has roommate"},
    "housing": {"0": "Owner w/ mortgage", "1": "Owner, free & clear", "2": "Renter", "3": "N/A"},
    "burden": {"0": "Under 30%", "1": "30–49%", "2": "50%+", "3": "N/A"},
}


def write_codebook(d, years, spec, nominal, output_dir):
    met_labels = spec["MET2013"]["labels"]
    present = np.unique(d["metro_area"].values)
    counts = d.groupby("metro_area").size()
    cb = {
        "source": "IPUMS USA, American Community Survey 1-year samples",
        "dollars": "each survey year's dollars" if nominal else f"constant {max(years)} dollars",
        "years": {str(i): str(y) for i, y in enumerate(years)},
        "year_display": {str(i): str(y) for i, y in enumerate(years)},
        "notes": {
            "dollars": "Incomes are put into each survey year's dollars with the Census Bureau's ADJINC (IPUMS ADJUST), "
                       "then into constant dollars of the latest year with the CPI-U (IPUMS CPI99).",
            "years": "ACS survey years. Income is for the 12 months before each interview, spread through the year.",
            "weights": f"Weights are divided by the {len(years)} pooled years, so counts describe an average year.",
            "se": "Standard errors use the 80 ACS household replicate weights (successive difference replication).",
            "topcodes": "The ACS replaces each income item above a state's cutoff with the mean of those values. "
                        "Households with a member at that value are flagged as topcoded.",
            "cohabiting": "Cohabiting: an unmarried partner of the householder is present (RELATED 1114).",
            "burden": "12 × monthly gross rent or selected owner costs, divided by household income.",
            "sample": "The chart shows a stratified sample of households; precomputed statistics use every household.",
        },
        "labels": LABELS,
        "states": {str(k): {"name": v} for k, v in FIPS_NAMES.items() if k in set(d["state"].unique().tolist())},
        "metros": {str(int(c)): {"name": met_labels.get(int(c), str(int(c))), "n": int(counts.get(c, 0))}
                   for c in present if c != 0},
    }
    p = output_dir / "codebook.json"
    p.write_text(json.dumps(cb, indent=1, ensure_ascii=False))
    print(f"  codebook.json {p.stat().st_size / 1024:.0f}KB")


# ---------------------------------------------------------------------------
# Validation: sanity checks that stop the run before anything is written
# ---------------------------------------------------------------------------
def weighted_median(values, weights):
    o = np.argsort(values)
    cw = np.cumsum(weights[o])
    return float(values[o][min(int(np.searchsorted(cw, cw[-1] / 2)), len(o) - 1)])


def validate(d, years, raw_year_medians):
    problems = []
    for col, allowed in {"work_status": range(7), "age_bucket": range(8), "marst": range(5), "educ": range(5),
                         "region": range(1, 5), "sex": (1, 2), "city": range(4), "burden": range(4),
                         "housing": range(4), "race_ethnicity": range(5), "breadwinner": range(5),
                         "passive_pct": range(5), "passive_source": range(5), "earner_count": range(4)}.items():
        bad = set(np.unique(d[col]).tolist()) - set(allowed)
        if bad:
            problems.append(f"{col} has unexpected values {sorted(bad)}")
    # nominal medians by year should be in the range the Census Bureau publishes (roughly $65k-$90k)
    for y, med in raw_year_medians.items():
        if not 60_000 <= med <= 95_000:
            problems.append(f"{y} median household income ${med:,.0f} is outside $60k-$95k")
    share_wage = float(np.average(d["passive_pct"] == 0, weights=d["weight"]))
    if not 0.35 <= share_wage <= 0.75:
        problems.append(f"wage-primary share {share_wage:.1%} outside 35-75%")
    if (d["wage_inc"] > 20_000_000).any():
        problems.append("household wage income above $20M: NIU codes leaking into sums?")
    return problems


# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", required=True)
    ap.add_argument("--ddi", required=True)
    ap.add_argument("--output-dir", default="./docs/data")
    ap.add_argument("--sample-size", type=int, default=DEFAULT_SAMPLE)
    ap.add_argument("--nominal", action="store_true", help="keep each year's own dollars")
    ap.add_argument("--skip-stats", action="store_true")
    ap.add_argument("--skip-validation", action="store_true")
    args = ap.parse_args()
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    step("Reading the DDI codebook")
    spec = parse_ddi(args.ddi)
    check_extract(spec)

    step(f"Reading {args.input}")
    persons, rep_all = read_extract(args.input, spec)

    step("Building households")
    h = build_households(persons, spec, nominal=args.nominal)
    del persons
    d, keep, years = derive(h, spec)
    rep = rep_all[keep] / len(years)
    del rep_all
    print(f"  {len(h):,} household records, {len(d):,} households after dropping group quarters; years {years}")
    raw = h.loc[keep].reset_index(drop=True)
    year_meds = {int(y): weighted_median((raw["HHINCOME"] * raw["adjust"]).loc[raw["YEAR"] == y].values.astype(float),
                                         raw.loc[raw["YEAR"] == y, "HHWT"].values) for y in years}
    for y, m in year_meds.items():
        print(f"  {y}: median household income ${m:,.0f} ({y} dollars; Census publishes the same statistic)")
    print(f"  topcoded households: {d['topcoded'].mean():.2%}")

    step("Validating")
    problems = validate(d, years, year_meds)
    for p in problems:
        print("  PROBLEM:", p)
    if problems and not args.skip_validation:
        sys.exit("Stopping: fix the problems above or rerun with --skip-validation to inspect output.")

    step(f"Writing national.arrow (stratified sample of {args.sample_size:,})")
    s = stratified_sample(d, args.sample_size)
    write_arrow(s, out / "national.arrow")
    print(f"  {len(s):,} rows, {(out / 'national.arrow').stat().st_size / 1e6:.1f}MB")

    write_codebook(d, years, spec, args.nominal, out)

    if not args.skip_stats:
        step("Computing statistics from all households")
        stats = compute_stats(d, rep, years)
        p = out / "stats_precomputed.json"
        p.write_text(json.dumps(stats, separators=(",", ":")))
        print(f"  {len(stats):,} cells, {p.stat().st_size / 1e6:.1f}MB")
    step(f"Done in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
