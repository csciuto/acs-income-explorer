"""
Unit tests for the preprocessor (preprocess.py and pipeline/). They build small fake IPUMS extracts (DDI codebook +
fixed-width records) in a temp directory, so they run without the real multi-GB downloads.
"""
import gzip
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
import preprocess  # noqa: E402
from pipeline import acs, cps  # noqa: E402
from pipeline import common as C  # noqa: E402

# ---------------------------------------------------------------------------
# Fake extracts
# ---------------------------------------------------------------------------
ACS_LAYOUT = [("YEAR", 4, 0), ("SERIAL", 8, 0), ("HHWT", 10, 2), ("GQ", 1, 0), ("CPI99", 5, 3), ("STATEFIP", 2, 0),
              ("PUMA", 5, 0), ("MET2013", 5, 0), ("METRO", 1, 0), ("HHINCOME", 7, 0), ("OWNERSHP", 1, 0),
              ("MORTGAGE", 1, 0), ("RENTGRS", 5, 0), ("OWNCOST", 5, 0), ("PERNUM", 4, 0), ("RELATE", 2, 0),
              ("RELATED", 4, 0), ("AGE", 3, 0), ("SEX", 1, 0), ("MARST", 1, 0), ("RACE", 1, 0), ("HISPAN", 1, 0),
              ("EDUCD", 3, 0), ("EMPSTAT", 1, 0), ("CLASSWKR", 1, 0), ("WKSWORK2", 1, 0), ("UHRSWORK", 2, 0),
              ("NCHILD", 1, 0), ("YNGCH", 2, 0), ("INCTOT", 7, 0), ("INCWAGE", 6, 0), ("INCBUS00", 6, 0),
              ("INCSS", 5, 0), ("INCSUPP", 5, 0), ("INCWELFR", 5, 0), ("INCRETIR", 6, 0), ("INCINVST", 6, 0),
              ("INCOTHER", 5, 0)]
ACS_MULTI = ACS_LAYOUT[:1] + [("MULTYEAR", 4, 0), ("ADJUST", 7, 6)] + ACS_LAYOUT[1:]
CPS_LAYOUT = [("YEAR", 4, 0), ("SERIAL", 6, 0), ("ASECFLAG", 1, 0), ("ASECWTH", 11, 4), ("CPI99", 4, 3),
              ("STATEFIP", 2, 0), ("METRO", 1, 0), ("HHINCOME", 8, 0), ("OWNERSHP", 2, 0), ("PERNUM", 2, 0),
              ("RELATE", 4, 0), ("AGE", 2, 0), ("SEX", 1, 0), ("MARST", 1, 0), ("RACE", 3, 0), ("HISPAN", 3, 0),
              ("EDUC", 3, 0), ("EMPSTAT", 2, 0), ("CLASSWKR", 2, 0), ("WKSWORK2", 1, 0), ("UHRSWORKLY", 3, 0),
              ("UHRSWORKT", 3, 0), ("UHRSWORK1", 3, 0), ("NCHILD", 1, 0), ("YNGCH", 2, 0), ("SPMMORT", 1, 0),
              ("INCWAGE", 8, 0), ("INCBUS", 8, 0), ("INCFARM", 8, 0), ("INCSS", 6, 0), ("INCSSI", 6, 0),
              ("INCWELFR", 6, 0), ("INCRETIR", 8, 0), ("INCPEN1", 7, 0), ("INCPEN2", 7, 0), ("INCRANN", 7, 0),
              ("INCSURV", 7, 0), ("INCDISAB", 7, 0), ("INCINT", 7, 0), ("INCDIVID", 7, 0), ("INCRENT", 7, 0)]
LABELS = {
    "RELATED": {101: "Head/Householder", 201: "Spouse", 301: "Child", 1114: "Unmarried Partner",
                1115: "Housemate/Roomate", 1241: "Roomers/boarders/lodgers"},
    "MET2013": {0: "Not in identifiable area", 14460: "Boston-Cambridge-Newton, MA-NH"},
    "EDUCD": {101: "Bachelor's degree"},
    "EDUC": {73: "High school diploma or equivalent", 111: "Bachelor's degree"},
    "RELATE": {1115: "Housemate/roomate", 1116: "Opposite sex unmarried partner"},
    "EMPSTAT": {10: "At work"},
}
CPI = {2020: 0.95, 2021: 0.900, 2023: 0.84, 2024: 0.800}


def write_ddi(path, layout, n_rep, extra_labels=None):
    labels = {**LABELS, **(extra_labels or {})}
    pos, out = 1, ['<?xml version="1.0"?>', '<codeBook xmlns="ddi:codebook:2_5"><dataDscr>']
    full = list(layout) + [(f"REPWT{i}", 6, 0) for i in range(1, n_rep + 1)]
    for name, w, dc in full:
        cats = "".join(f"<catgry><catValu>{v}</catValu><labl>{lab}</labl></catgry>" for v, lab in labels.get(name, {}).items())
        out.append(f'<var name="{name}" dcml="{dc}"><location StartPos="{pos}" EndPos="{pos + w - 1}" width="{w}"/>{cats}</var>')
        pos += w
    out.append("</dataDscr></codeBook>")
    Path(path).write_text("".join(out))
    return full


def fmt(v, w):
    v = int(round(v))
    return ("-" + str(-v).zfill(w - 1)) if v < 0 else str(v).zfill(w)


ACS_P = dict(RELATE=1, RELATED=101, AGE=40, SEX=1, MARST=6, RACE=1, HISPAN=0, EDUCD=101, EMPSTAT=1, CLASSWKR=2,
             WKSWORK2=6, UHRSWORK=40, NCHILD=0, YNGCH=99, INCTOT=0, INCWAGE=0, INCBUS00=0, INCSS=0, INCSUPP=0,
             INCWELFR=0, INCRETIR=0, INCINVST=0, INCOTHER=0)
ACS_H = dict(YEAR=2024, HHWT=100, GQ=1, STATEFIP=25, PUMA=609, MET2013=14460, METRO=5, HHINCOME=0, OWNERSHP=2,
             MORTGAGE=0, RENTGRS=1000, OWNCOST=99999, MULTYEAR=2024, ADJUST=1.0)
CPS_P = dict(RELATE=101, AGE=40, SEX=1, MARST=6, RACE=100, HISPAN=0, EDUC=111, EMPSTAT=10, CLASSWKR=22, WKSWORK2=6,
             UHRSWORKLY=40, UHRSWORKT=40, UHRSWORK1=40, NCHILD=0, YNGCH=99, SPMMORT=3, INCWAGE=0, INCBUS=0, INCFARM=0,
             INCSS=0, INCSSI=0, INCWELFR=0, INCRETIR=0, INCPEN1=0, INCPEN2=0, INCRANN=0, INCSURV=0, INCDISAB=0,
             INCINT=0, INCDIVID=0, INCRENT=0)
CPS_H = dict(YEAR=2025, ASECFLAG=1, ASECWTH=1000, STATEFIP=25, METRO=2, HHINCOME=0, OWNERSHP=22)


def records(households, full, n_rep, hdef, pdef, wt_name, cpi_year):
    dc = {n: d for n, _, d in full}
    lines = []
    for serial, (hh, people) in enumerate(households, start=1):
        hv = {**hdef, **hh, "SERIAL": serial}
        hv["CPI99"] = CPI[cpi_year(hv["YEAR"])] * 10 ** dc["CPI99"]
        if "ADJUST" in dc:
            hv["ADJUST"] = hv["ADJUST"] * 10 ** dc["ADJUST"]
        wraw = hv[wt_name]
        hv[wt_name] = wraw * 10 ** dc[wt_name]
        for pn, person in enumerate(people, start=1):
            v = {**pdef, **hv, **person, "PERNUM": pn}
            for i in range(1, n_rep + 1):
                v[f"REPWT{i}"] = wraw
            lines.append("".join(fmt(v[name], w) for name, w, _ in full))
    return "\n".join(lines) + "\n"


@pytest.fixture
def make(tmp_path):
    def build(kind, households, gz=True, layout=None, labels=None, sub=""):
        d = tmp_path / sub
        d.mkdir(exist_ok=True)
        if kind == "acs":
            full = write_ddi(d / "x.xml", layout or ACS_LAYOUT, acs.N_REP, labels)
            text = records(households, full, acs.N_REP, ACS_H, ACS_P, "HHWT", lambda y: y)
        else:
            full = write_ddi(d / "x.xml", layout or CPS_LAYOUT, cps.N_REP, labels)
            text = records(households, full, cps.N_REP, CPS_H, CPS_P, "ASECWTH", lambda y: y - 1)
        dat = d / ("x.dat.gz" if gz else "x.dat")
        if gz:
            with gzip.open(dat, "wt") as f:
                f.write(text)
        else:
            dat.write_text(text)
        return dat, d / "x.xml"
    return build


def run(make, kind, households, **kw):
    mod = acs if kind == "acs" else cps
    dat, ddi = make(kind, households, **kw)
    spec = C.parse_ddi(ddi)
    mod.check(spec)
    want = mod.HOUSEHOLD_VARS + mod.PERSON_VARS + mod.OPTIONAL_VARS + getattr(mod, "EXTRA_INCOME", []) + \
        getattr(mod, "PENSION_INCOME", [])
    p, rep = C.read_extract(dat, spec, want, mod.REP_PREFIX, mod.N_REP, chunk_rows=3)  # households split across chunks
    d, keep, meta = mod.build(p, spec)
    return d, meta, rep[keep]


# ---------------------------------------------------------------------------
# Parsing and checks
# ---------------------------------------------------------------------------
def test_parse_int_handles_negatives_spaces_and_zero_padding():
    rows = np.frombuffer(b"000123-00045    79", dtype=np.uint8)
    block = np.stack([rows[0:6], rows[6:12], rows[12:18]])
    assert C.parse_int(block).tolist() == [123, -45, 79]


def test_niu_codes_are_all_nines_or_nine_eight():
    assert C.niu_mask(np.array([999999, 999998, 999997, 0]), 6).tolist() == [True, True, False, False]


def test_check_names_missing_variables(tmp_path):
    write_ddi(tmp_path / "x.xml", [c for c in ACS_LAYOUT if c[0] != "INCSS"], acs.N_REP)
    with pytest.raises(SystemExit, match="INCSS"):
        acs.check(C.parse_ddi(tmp_path / "x.xml"))


def test_check_requires_replicate_weights(tmp_path):
    write_ddi(tmp_path / "x.xml", ACS_LAYOUT, 10)
    with pytest.raises(SystemExit, match="replicate"):
        acs.check(C.parse_ddi(tmp_path / "x.xml"))


def test_check_rejects_renumbered_codes(tmp_path):
    write_ddi(tmp_path / "x.xml", ACS_LAYOUT, acs.N_REP, {"RELATED": {**LABELS["RELATED"], 1114: "Foster child"}})
    with pytest.raises(SystemExit, match="1114"):
        acs.check(C.parse_ddi(tmp_path / "x.xml"))


def test_cps_check_requires_pension_items(tmp_path):
    write_ddi(tmp_path / "x.xml", [c for c in CPS_LAYOUT if c[0] != "INCPEN1"], cps.N_REP)
    with pytest.raises(SystemExit, match="INCPEN1"):
        cps.check(C.parse_ddi(tmp_path / "x.xml"))


def test_reads_gzip_and_plain_and_keeps_households_whole_across_chunks(make):
    hh = [({"HHINCOME": 50_000}, [{"INCWAGE": 30_000}, {"RELATED": 201, "INCWAGE": 20_000}, {"RELATED": 301}]),
          ({"HHINCOME": 10_000}, [{"INCWAGE": 10_000}])] * 3
    adj = acs.ADJUST_BY_YEAR[2024]
    for gz in (True, False):
        d, _, rep = run(make, "acs", hh, gz=gz)
        assert len(d) == 6 and rep.shape == (6, 80)
        assert d["hh_size"].tolist() == [3, 1] * 3
        assert d["wage_inc"].tolist()[:2] == [round(50_000 * adj), round(10_000 * adj)]


# ---------------------------------------------------------------------------
# ACS derivations
# ---------------------------------------------------------------------------
def test_acs_group_quarters_dropped_and_niu_members_ignored(make):
    adj = acs.ADJUST_BY_YEAR[2024]
    d, *_ = run(make, "acs", [({"HHINCOME": 60_000}, [{"INCWAGE": 60_000}, {"RELATED": 301, "AGE": 5, "INCWAGE": 999999,
                                                                          "INCBUS00": 999999}]),
                              ({"GQ": 3, "HHINCOME": 9999999}, [{}]), ({"GQ": 5, "HHINCOME": 20_000}, [{}])])
    assert d["inc"].tolist() == [round(60_000 * adj), round(20_000 * adj)]
    assert d["earner_count"].tolist() == [1, 0]


def test_acs_one_year_samples_use_adjust_and_cpi(make):
    d, meta, _ = run(make, "acs", [({"YEAR": 2021, "HHINCOME": 100_000}, [{}]), ({"YEAR": 2024, "HHINCOME": 100_000}, [{}])])
    f21 = acs.ADJUST_BY_YEAR[2021] * CPI[2021] / CPI[2024]
    assert d["inc"].tolist() == [round(100_000 * f21), round(100_000 * acs.ADJUST_BY_YEAR[2024])]
    assert d["weight"].tolist() == [50.0, 50.0]  # divided by the 2 pooled years
    assert meta["years"] == [2021, 2024] and not meta["multiyear"]


def test_acs_five_year_sample_uses_multyear_adjust_and_keeps_weights(make):
    hh = [({"YEAR": 2024, "MULTYEAR": 2020, "ADJUST": 1.081, "HHINCOME": 100_000}, [{}]),
          ({"YEAR": 2024, "MULTYEAR": 2024, "ADJUST": 1.012, "HHINCOME": 100_000}, [{}])]
    d, meta, _ = run(make, "acs", hh, layout=ACS_MULTI)
    assert meta["multiyear"] and meta["years"] == [2020, 2024]
    assert d["inc"].tolist() == [108_100, 101_200]          # already final-year dollars: ADJUST only, no CPI
    assert d["weight"].tolist() == [100.0, 100.0]           # 5-year weights already describe an average year
    assert d["year"].tolist() == [0, 1]
    assert d["puma"].tolist() == [2500609, 2500609]


def test_acs_cohabiting_roommates_education_race_city(make):
    d, *_ = run(make, "acs", [
        ({"HHINCOME": 1, "STATEFIP": 6, "METRO": 3}, [{"MARST": 6, "EDUCD": 61}, {"RELATED": 1114}]),
        ({"HHINCOME": 1, "STATEFIP": 48, "METRO": 1, "MET2013": 0}, [{"MARST": 1, "EDUCD": 63, "RACE": 2}, {"RELATED": 201}]),
        ({"HHINCOME": 1, "STATEFIP": 36, "METRO": 5}, [{"MARST": 4, "EDUCD": 81, "HISPAN": 1}, {"RELATED": 1115}]),
        ({"HHINCOME": 1, "STATEFIP": 17, "METRO": 4}, [{"MARST": 6, "EDUCD": 101, "RACE": 6}, {"RELATED": 1241}]),
        ({"HHINCOME": 1, "STATEFIP": 25, "METRO": 2}, [{"EDUCD": 116, "RACE": 8}]),
    ])
    assert d["marst"].tolist() == [1, 0, 2, 4, 4]
    assert d["has_roommate"].tolist() == [0, 0, 1, 1, 0]
    assert d["educ"].tolist() == [0, 1, 2, 3, 4]
    assert d["race_ethnicity"].tolist() == [0, 1, 2, 3, 4]
    assert d["region"].tolist() == [4, 3, 1, 2, 1]
    assert d["city"].tolist() == [1, 2, 0, 3, 3]


def test_acs_work_status_hierarchy(make):
    d, *_ = run(make, "acs", [
        ({"HHINCOME": 1}, [{"EMPSTAT": 1, "CLASSWKR": 2, "UHRSWORK": 40, "WKSWORK2": 6}]),
        ({"HHINCOME": 1}, [{"EMPSTAT": 1, "CLASSWKR": 1, "UHRSWORK": 50, "WKSWORK2": 5}]),
        ({"HHINCOME": 1}, [{"EMPSTAT": 1, "CLASSWKR": 2, "UHRSWORK": 40, "WKSWORK2": 3}]),
        ({"HHINCOME": 1}, [{"EMPSTAT": 1, "CLASSWKR": 2, "UHRSWORK": 20, "WKSWORK2": 6}]),
        ({"HHINCOME": 1}, [{"EMPSTAT": 2, "CLASSWKR": 0, "UHRSWORK": 0, "WKSWORK2": 0}]),
        ({"HHINCOME": 1}, [{"EMPSTAT": 3, "AGE": 70, "INCSS": 20_000, "UHRSWORK": 0}]),
        ({"HHINCOME": 1}, [{"EMPSTAT": 3, "AGE": 30, "UHRSWORK": 0}]),
    ])
    assert d["work_status"].tolist() == [0, 1, 2, 3, 4, 5, 6]


def test_acs_income_mix_and_sources(make):
    d, *_ = run(make, "acs", [
        ({"HHINCOME": 100_000}, [{"INCWAGE": 95_000}, {"RELATED": 201, "INCWAGE": 5_000}]),
        ({"HHINCOME": 100_000}, [{"INCWAGE": 50_000}, {"RELATED": 201, "INCWAGE": 50_000}]),
        ({"HHINCOME": 40_000}, [{"INCSS": 20_000, "EMPSTAT": 3}, {"RELATED": 201, "INCSUPP": 5_000, "INCRETIR": 15_000,
                                                                     "EMPSTAT": 3}]),
        ({"HHINCOME": 60_000}, [{"INCWAGE": 10_000, "INCINVST": 50_000}]),
    ])
    assert d["breadwinner"].tolist() == [0, 2, 4, 0]
    assert d["passive_pct"].tolist() == [0, 0, 4, 3]
    assert d["passive_source"].tolist() == [4, 4, 0, 2]


def test_acs_housing_and_cost_burden(make):
    d, *_ = run(make, "acs", [
        ({"HHINCOME": 120_000, "OWNERSHP": 2, "RENTGRS": 2000}, [{}]),
        ({"HHINCOME": 60_000, "OWNERSHP": 2, "RENTGRS": 2000}, [{}]),
        ({"HHINCOME": 40_000, "OWNERSHP": 1, "MORTGAGE": 3, "OWNCOST": 2000}, [{}]),
        ({"HHINCOME": 40_000, "OWNERSHP": 1, "MORTGAGE": 1, "OWNCOST": 99999}, [{}]),
        ({"HHINCOME": 0, "OWNERSHP": 2, "RENTGRS": 900}, [{}]),
    ])
    assert d["housing"].tolist() == [2, 2, 0, 1, 2]
    assert d["burden"].tolist() == [0, 1, 2, 3, 3]


def test_acs_topcoded_flag_marks_households_at_the_state_max(make):
    d, *_ = run(make, "acs", [({"HHINCOME": 700_000}, [{"INCWAGE": 650_000}]), ({"HHINCOME": 700_000}, [{"INCWAGE": 650_000}]),
                              ({"HHINCOME": 80_000}, [{"INCWAGE": 80_000}])])
    assert d["topcoded"].tolist() == [1, 1, 0]


# ---------------------------------------------------------------------------
# CPS derivations
# ---------------------------------------------------------------------------
def test_cps_education_codes_put_graduates_in_hs_diploma(make):
    d, *_ = run(make, "cps", [({"HHINCOME": 1}, [{"EDUC": e}]) for e in [60, 71, 73, 81, 92, 111, 123, 125]])
    assert d["educ"].tolist() == [0, 0, 1, 2, 2, 3, 4, 4]


def test_cps_dollars_income_year_and_weights(make):
    d, meta, _ = run(make, "cps", [({"YEAR": 2021, "HHINCOME": 100_000}, [{"INCWAGE": 100_000}]),
                                   ({"YEAR": 2025, "HHINCOME": 100_000}, [{"INCWAGE": 100_000}])])
    assert meta["years"] == [2020, 2024]                  # labelled by income year
    assert d["inc"].tolist() == [round(100_000 * CPI[2020] / CPI[2024]), 100_000]
    assert d["weight"].tolist() == [500.0, 500.0]         # ASECWTH / 2 pooled years
    assert d["year"].tolist() == [0, 1]


def test_cps_pensions_count_as_retirement_and_partners_roommates(make):
    d, meta, _ = run(make, "cps", [
        ({"HHINCOME": 40_000}, [{"EMPSTAT": 36, "AGE": 70, "INCSS": 15_000, "INCPEN1": 20_000, "INCRANN": 5_000}]),
        ({"HHINCOME": 40_000}, [{"EMPSTAT": 36, "AGE": 70, "INCSS": 25_000, "INCRETIR": 15_000}]),
        ({"HHINCOME": 50_000}, [{"INCWAGE": 10_000, "INCINT": 15_000, "INCDIVID": 15_000, "INCRENT": 10_000}]),
        ({"HHINCOME": 60_000}, [{"MARST": 6, "INCWAGE": 30_000}, {"RELATE": 1116, "INCWAGE": 30_000}]),
        ({"HHINCOME": 60_000}, [{"INCWAGE": 30_000}, {"RELATE": 1241, "INCWAGE": 30_000}]),
    ])
    assert d["passive_source"].tolist() == [1, 0, 2, 4, 4]
    assert d["work_status"].tolist()[:2] == [5, 5]
    assert d["marst"].tolist()[3] == 1
    assert d["has_roommate"].tolist() == [0, 0, 0, 0, 1]
    assert d["earner_count"].tolist()[3:] == [2, 2]


def test_cps_multiple_jobs_and_city(make):
    d, *_ = run(make, "cps", [({"HHINCOME": 1, "METRO": 3}, [{"UHRSWORKT": 50, "UHRSWORK1": 40}]),
                              ({"HHINCOME": 1, "METRO": 1}, [{"UHRSWORKT": 997, "UHRSWORK1": 40}]),
                              ({"HHINCOME": 1, "METRO": 2}, [{"UHRSWORKT": 80, "UHRSWORK1": 40}])])
    assert d["multi_job_proxy"].tolist() == [1, 0, 3]
    assert d["city"].tolist() == [1, 2, 0]


def test_cps_rejects_non_asec_records(make):
    with pytest.raises(SystemExit, match="ASEC"):
        run(make, "cps", [({"HHINCOME": 1, "ASECFLAG": 2}, [{}])])


# ---------------------------------------------------------------------------
# Browser sample and statistics
# ---------------------------------------------------------------------------
def test_stratified_sample_keeps_each_stratum_total_weight():
    rng = np.random.default_rng(1)
    d = pd.DataFrame({"year": rng.integers(0, 4, 20_000).astype(np.uint8), "state": rng.choice([6, 25, 56], 20_000).astype(np.uint8),
                      "weight": rng.uniform(50, 150, 20_000).astype(np.float32), "id": 0})
    s = C.stratified_sample(d, 2_000)
    assert abs(len(s) - 2_000) <= 12
    full, samp = d.groupby(["year", "state"])["weight"].sum(), s.groupby(["year", "state"])["weight"].sum()
    assert ((samp / full - 1).abs() < 0.15).all()


def naive(v, w, q):
    o = np.argsort(v, kind="stable")
    cw = np.cumsum(w[o])
    return v[o][min(np.searchsorted(cw, q * cw[-1]), len(v) - 1)]


def naive_binned_median(v, w, width=2_500):
    x = naive(v, w, 0.5)
    lo = np.floor(x / width) * width
    below, inside = w[v < lo].sum(), w[(v >= lo) & (v < lo + width)].sum()
    return lo + width * (w.sum() / 2 - below) / inside


@pytest.mark.parametrize("n_rep", [80, 160])
def test_cell_stats_match_a_brute_force_replicate_calculation(n_rep):
    rng = np.random.default_rng(7)
    n = 3_000
    inc = np.round(rng.lognormal(11, 0.8, n))
    w = rng.uniform(20, 200, n)
    rep = (w[:, None] * rng.uniform(0.3, 1.7, (n, n_rep))).astype(np.float32)
    cs = C.CellStats(inc, w, rep)
    mask = rng.random(n) < 0.6
    c = cs.cell(cs.sorted_mask(mask))
    v, ww, R = inc[mask], w[mask], rep[mask].astype(np.float64)
    med, mean = naive_binned_median(v, ww), (v * ww).sum() / ww.sum()
    rmed = np.array([naive_binned_median(v, R[:, r]) for r in range(n_rep)])
    rmean = (v @ R) / R.sum(0)
    assert c["med"] == round(med) and c["mean"] == round(mean)
    assert c["se_med"] == round(np.sqrt(4 / n_rep * ((rmed - med) ** 2).sum()))
    assert c["se_mean"] == round(np.sqrt(4 / n_rep * ((rmean - mean) ** 2).sum()))


def test_median_is_not_pinned_by_heaped_round_numbers():
    rng = np.random.default_rng(11)
    n = 4_000
    inc = np.where(rng.random(n) < 0.3, 80_000, np.round(rng.uniform(40_000, 120_000, n), -2))
    rep = rng.uniform(0.5, 1.5, (n, 80)).astype(np.float32)
    cs = C.CellStats(inc, np.ones(n), rep)
    c = cs.cell(cs.sorted_mask(np.ones(n, bool)))
    assert all(naive(inc, rep[:, r].astype(float), 0.5) == 80_000 for r in range(80))
    assert c["se_med"] > 0 and c["med"] != 80_000


def test_small_cells_are_suppressed_and_reliability_tiers():
    inc = np.arange(600, dtype=float)
    cs = C.CellStats(inc, np.ones(600), np.ones((600, 80), np.float32))
    assert cs.cell(cs.sorted_mask(inc < 49)) is None
    assert cs.cell(cs.sorted_mask(inc < 60), with_se=False)["rel"] == 1
    assert cs.cell(cs.sorted_mask(inc < 300), with_se=False)["rel"] == 2


def fake_derived(n, rng):
    d = pd.DataFrame({c: rng.integers(0, 2, n).astype(np.uint8) for c, _ in preprocess.SHARED_DIMS.values()})
    d["sex"] = rng.integers(1, 3, n).astype(np.uint8)
    d["region"] = rng.integers(1, 5, n).astype(np.uint8)
    d["state"] = np.where(d["region"] == 1, 25, 6).astype(np.uint8)
    d["year"] = rng.integers(0, 2, n).astype(np.uint8)
    d["metro_area"] = np.where(rng.random(n) < 0.5, 14460, 0).astype(np.uint32)
    d["puma"] = (d["state"].astype(np.uint32) * 100_000 + rng.choice([609, 610], n)).astype(np.uint32)
    d["inc"] = rng.integers(0, 200_000, n).astype(np.uint32)
    d["weight"] = np.float32(1)
    d["passive_pct"] = 0
    return d


def test_compute_stats_scopes_and_keys():
    rng = np.random.default_rng(3)
    d = fake_derived(4_000, rng)
    dims = {**preprocess.SHARED_DIMS, "year": ("year", [0, 1])}
    stats = C.compute_stats(d, np.ones((len(d), 80), np.float32), dims, metro_min_n=100, log=False)
    for key in ["national", "national|age=1", "national|sex=2|work=1", "state=25", "state=6|age=0", "metro=14460",
                "metro=14460|kids=1", "national|region=2|work=1", "national|year=1"]:
        assert key in stats, key
    assert "metro=0" not in stats
    assert stats["national"]["wage_pct"] == 1.0 and stats["national"]["se_med"] == 0


def test_local_stats_are_split_by_state():
    rng = np.random.default_rng(4)
    d = fake_derived(3_000, rng)
    local = C.compute_local_stats(d, np.ones((len(d), 80), np.float32), {"age": ("age_bucket", [0, 1])})
    assert set(local) == {6, 25}
    assert "puma=2500609" in local[25] and "puma=2500609|age=1" in local[25]
    assert not any(k.startswith("puma=6") for k in local[25])


# ---------------------------------------------------------------------------
# End to end
# ---------------------------------------------------------------------------
def test_main_writes_both_sources(make, tmp_path, monkeypatch):
    rng = np.random.default_rng(5)
    acs_hh, cps_hh = [], []
    for i in range(400):
        inc = int(rng.integers(20_000, 150_000))
        acs_hh.append(({"YEAR": 2021 if i % 2 else 2024, "HHINCOME": inc, "STATEFIP": [6, 25, 36][i % 3]},
                       [{"INCWAGE": int(inc * 0.9), "EDUCD": [63, 81, 101][i % 3]}, {"RELATED": 201, "AGE": 38}]))
        cps_hh.append(({"YEAR": 2021 if i % 2 else 2025, "HHINCOME": inc, "STATEFIP": [6, 25, 36][i % 3]},
                       [{"INCWAGE": int(inc * 0.9), "EDUC": [73, 81, 111][i % 3]}]))
    a_dat, a_ddi = make("acs", acs_hh, sub="a")
    c_dat, c_ddi = make("cps", cps_hh, sub="c")
    out = tmp_path / "out"
    monkeypatch.setattr(sys, "argv", ["preprocess.py", "--acs", str(a_dat), "--acs-ddi", str(a_ddi), "--cps", str(c_dat),
                                      "--cps-ddi", str(c_ddi), "--output-dir", str(out), "--sample-size", "200",
                                      "--skip-validation"])
    preprocess.main()
    import pyarrow.ipc as ipc
    ta = ipc.open_file(str(out / "acs" / "national.arrow")).read_all()
    tc = ipc.open_file(str(out / "cps" / "national.arrow")).read_all()
    assert "burden" in ta.column_names and "puma" in ta.column_names and "burden" not in tc.column_names
    assert "multi_job_proxy" in tc.column_names
    cb = json.loads((out / "codebook.json").read_text())
    assert cb["sources"]["acs"]["years"] == {"0": "2021", "1": "2024"}
    assert cb["sources"]["cps"]["years"] == {"0": "2020", "1": "2024"}
    assert cb["sources"]["acs"]["local_areas"]["2500609"]["name"] == "Middlesex County (East)--Malden & Medford"
    assert json.loads((out / "acs" / "stats.json").read_text())["national"]["n"] == 400
    assert json.loads((out / "cps" / "stats.json").read_text())["national"]["n"] == 400
    assert (out / "acs" / "local" / "25.json").exists() and (out / "acs" / "local" / "25.arrow").exists()
