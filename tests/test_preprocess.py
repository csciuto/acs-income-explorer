"""
Unit tests for preprocess.py. They build a tiny fake IPUMS extract (DDI codebook + fixed-width records)
in a temp directory, so they run without the real multi-GB download.
"""
import gzip
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
import preprocess as pp  # noqa: E402

# ---------------------------------------------------------------------------
# Fake extract
# ---------------------------------------------------------------------------
# (name, width, dcml). Order is the record layout; REPWT1..80 are appended after these.
LAYOUT = [("YEAR", 4, 0), ("SERIAL", 8, 0), ("HHWT", 10, 2), ("GQ", 1, 0), ("CPI99", 5, 3),
          ("STATEFIP", 2, 0), ("MET2013", 5, 0), ("METRO", 1, 0), ("HHINCOME", 7, 0), ("OWNERSHP", 1, 0),
          ("MORTGAGE", 1, 0), ("RENTGRS", 5, 0), ("OWNCOST", 5, 0), ("PERNUM", 4, 0), ("RELATE", 2, 0),
          ("RELATED", 4, 0), ("AGE", 3, 0), ("SEX", 1, 0), ("MARST", 1, 0), ("RACE", 1, 0), ("HISPAN", 1, 0),
          ("EDUCD", 3, 0), ("EMPSTAT", 1, 0), ("CLASSWKR", 1, 0), ("WKSWORK2", 1, 0), ("UHRSWORK", 2, 0),
          ("NCHILD", 1, 0), ("YNGCH", 2, 0), ("INCTOT", 7, 0), ("INCWAGE", 6, 0), ("INCBUS00", 6, 0),
          ("INCSS", 5, 0), ("INCSUPP", 5, 0), ("INCWELFR", 5, 0), ("INCRETIR", 6, 0), ("INCINVST", 6, 0),
          ("INCOTHER", 5, 0)]
RELATED_LABELS = {101: "Head/Householder", 201: "Spouse", 301: "Child", 1114: "Unmarried Partner",
                  1115: "Housemate/Roomate", 1241: "Roomers/boarders/lodgers"}
MET_LABELS = {0: "Not in identifiable area", 14460: "Boston-Cambridge-Newton, MA-NH"}
CPI = {2021: 0.900, 2024: 0.800}  # CPI99 per year (dollars of that year -> 1999 dollars)


def write_ddi(path, layout=LAYOUT, n_rep=pp.N_REP, extra_labels=None):
    labels = {"RELATED": RELATED_LABELS, "MET2013": MET_LABELS, **(extra_labels or {})}
    pos, out = 1, ['<?xml version="1.0"?>', '<codeBook xmlns="ddi:codebook:2_5"><dataDscr>']
    full = list(layout) + [(f"REPWT{i}", 6, 0) for i in range(1, n_rep + 1)]
    for name, w, dc in full:
        cats = "".join(f"<catgry><catValu>{v}</catValu><labl>{lab}</labl></catgry>"
                       for v, lab in labels.get(name, {}).items())
        out.append(f'<var name="{name}" dcml="{dc}"><location StartPos="{pos}" EndPos="{pos + w - 1}" '
                   f'width="{w}"/>{cats}</var>')
        pos += w
    out.append("</dataDscr></codeBook>")
    Path(path).write_text("".join(out))
    return full


def fmt(v, w):
    v = int(v)
    return ("-" + str(-v).zfill(w - 1)) if v < 0 else str(v).zfill(w)


PERSON_DEFAULTS = dict(RELATE=1, RELATED=101, AGE=40, SEX=1, MARST=6, RACE=1, HISPAN=0, EDUCD=101, EMPSTAT=1,
                       CLASSWKR=2, WKSWORK2=6, UHRSWORK=40, NCHILD=0, YNGCH=99, INCTOT=0, INCWAGE=0,
                       INCBUS00=0, INCSS=0, INCSUPP=0, INCWELFR=0, INCRETIR=0, INCINVST=0, INCOTHER=0)
HH_DEFAULTS = dict(YEAR=2024, HHWT=100, GQ=1, STATEFIP=25, MET2013=14460, METRO=5, HHINCOME=0, OWNERSHP=2,
                   MORTGAGE=0, RENTGRS=1000, OWNCOST=99999)


def make_records(households, full_layout, rep=None):
    """households: list of (hh_fields, [person_fields...]). Returns the fixed-width text."""
    lines = []
    for serial, (hh, people) in enumerate(households, start=1):
        hv = {**HH_DEFAULTS, **hh, "SERIAL": serial}
        hv["CPI99"] = round(CPI[hv["YEAR"]] * 1000)
        hv["HHWT"] = round(hv["HHWT"] * 100)
        reps = rep[serial - 1] if rep is not None else [round(hh.get("HHWT", 100))] * pp.N_REP
        for pn, person in enumerate(people, start=1):
            v = {**PERSON_DEFAULTS, **hv, **person, "PERNUM": pn}
            for i in range(1, pp.N_REP + 1):
                v[f"REPWT{i}"] = reps[i - 1]
            lines.append("".join(fmt(v[name], w) for name, w, _ in full_layout))
    return "\n".join(lines) + "\n"


@pytest.fixture
def extract(tmp_path):
    def build(households, gz=True, rep=None, layout=LAYOUT):
        ddi = tmp_path / "x.xml"
        full = write_ddi(ddi, layout)
        text = make_records(households, full, rep)
        dat = tmp_path / ("x.dat.gz" if gz else "x.dat")
        if gz:
            with gzip.open(dat, "wt") as f:
                f.write(text)
        else:
            dat.write_text(text)
        return dat, ddi
    return build


def run(extract, households, **kw):
    dat, ddi = extract(households, **kw)
    spec = pp.parse_ddi(ddi)
    pp.check_extract(spec)
    persons, rep = pp.read_extract(dat, spec, chunk_rows=3)  # tiny chunks: households split across chunks
    h = pp.build_households(persons, spec)
    d, keep, years = pp.derive(h, spec)
    return d, h, keep, years, rep


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------
def test_parse_int_handles_negatives_spaces_and_zero_padding():
    rows = np.frombuffer(b"000123-00045    79", dtype=np.uint8)
    block = np.stack([rows[0:6], rows[6:12], rows[12:18]])
    assert pp.parse_int(block).tolist() == [123, -45, 79]


def test_niu_codes_are_all_nines_or_nine_eight():
    assert pp.niu_mask(np.array([999999, 999998, 999997, 0]), 6).tolist() == [True, True, False, False]


def test_check_extract_names_missing_variables(tmp_path):
    ddi = tmp_path / "x.xml"
    write_ddi(ddi, [c for c in LAYOUT if c[0] != "INCSS"])
    with pytest.raises(SystemExit, match="INCSS"):
        pp.check_extract(pp.parse_ddi(ddi))


def test_check_extract_requires_replicate_weights(tmp_path):
    ddi = tmp_path / "x.xml"
    write_ddi(ddi, n_rep=10)
    with pytest.raises(SystemExit, match="replicate"):
        pp.check_extract(pp.parse_ddi(ddi))


def test_check_extract_rejects_renumbered_relationship_codes(tmp_path):
    ddi = tmp_path / "x.xml"
    write_ddi(ddi, extra_labels={"RELATED": {**RELATED_LABELS, 1114: "Foster child"}})
    with pytest.raises(SystemExit, match="1114"):
        pp.check_extract(pp.parse_ddi(ddi))


def test_reads_gzip_and_plain_and_keeps_households_whole_across_chunks(extract):
    hh = [({"HHINCOME": 50_000}, [{"INCWAGE": 30_000}, {"RELATED": 201, "INCWAGE": 20_000}, {"RELATED": 301}]),
          ({"HHINCOME": 10_000}, [{"INCWAGE": 10_000}])] * 3
    for gz in (True, False):
        d, h, *_ = run(extract, hh, gz=gz)
        assert len(d) == 6
        assert d["hh_size"].tolist() == [3, 1] * 3
        adj = pp.ADJUST_BY_YEAR[2024]
        assert d["wage_inc"].tolist()[:2] == [round(50_000 * adj), round(10_000 * adj)]


# ---------------------------------------------------------------------------
# Households and derived variables
# ---------------------------------------------------------------------------
def test_group_quarters_and_vacant_units_are_dropped(extract):
    d, *_ = run(extract, [({"HHINCOME": 40_000}, [{}]), ({"GQ": 3, "HHINCOME": 9999999}, [{}]),
                          ({"GQ": 4, "HHINCOME": 9999999}, [{}]), ({"GQ": 5, "HHINCOME": 20_000}, [{}])])
    adj = pp.ADJUST_BY_YEAR[2024]
    assert d["inc"].tolist() == [round(40_000 * adj), round(20_000 * adj)]


def test_niu_members_do_not_inflate_household_sums(extract):
    d, *_ = run(extract, [({"HHINCOME": 60_000}, [{"INCWAGE": 60_000}, {"RELATED": 301, "AGE": 5, "INCWAGE": 999999,
                                                    "INCBUS00": 999999, "INCSS": 99999}])])
    assert d["wage_inc"].tolist() == [round(60_000 * pp.ADJUST_BY_YEAR[2024])]
    assert d["earner_count"].tolist() == [1]


def test_adjust_and_cpi_put_every_year_in_latest_year_dollars(extract):
    d, *_ = run(extract, [({"YEAR": 2021, "HHINCOME": 100_000}, [{"INCWAGE": 100_000}]),
                          ({"YEAR": 2024, "HHINCOME": 100_000}, [{"INCWAGE": 100_000}])])
    f21 = pp.ADJUST_BY_YEAR[2021] * CPI[2021] / CPI[2024]
    assert d["inc"].tolist() == [round(100_000 * f21), round(100_000 * pp.ADJUST_BY_YEAR[2024])]
    assert d["year"].tolist() == [0, 1]
    assert d["weight"].tolist() == [50.0, 50.0]  # divided by the 2 pooled years


def test_missing_adjust_factor_for_a_year_stops(extract, monkeypatch):
    monkeypatch.setattr(pp, "ADJUST_BY_YEAR", {2024: 1.0})
    with pytest.raises(SystemExit, match="ADJUST"):
        run(extract, [({"YEAR": 2021, "HHINCOME": 1}, [{}]), ({"YEAR": 2024, "HHINCOME": 1}, [{}])])


def test_cohabiting_and_roommates_from_related_codes(extract):
    d, *_ = run(extract, [
        ({"HHINCOME": 1}, [{"MARST": 6}, {"RELATED": 1114}]),                 # cohabiting
        ({"HHINCOME": 1}, [{"MARST": 1}, {"RELATED": 201}]),                  # married
        ({"HHINCOME": 1}, [{"MARST": 4}, {"RELATED": 1115}]),                 # divorced, housemate
        ({"HHINCOME": 1}, [{"MARST": 6}, {"RELATED": 1241}]),                 # never married, roomer
    ])
    assert d["marst"].tolist() == [1, 0, 2, 4]
    assert d["has_roommate"].tolist() == [0, 0, 1, 1]


def test_education_race_region_and_city(extract):
    d, *_ = run(extract, [
        ({"HHINCOME": 1, "STATEFIP": 6, "METRO": 3}, [{"EDUCD": 61, "RACE": 1, "HISPAN": 0}]),
        ({"HHINCOME": 1, "STATEFIP": 48, "METRO": 1, "MET2013": 0}, [{"EDUCD": 63, "RACE": 2, "HISPAN": 0}]),
        ({"HHINCOME": 1, "STATEFIP": 36, "METRO": 5}, [{"EDUCD": 81, "RACE": 1, "HISPAN": 1}]),
        ({"HHINCOME": 1, "STATEFIP": 17, "METRO": 4}, [{"EDUCD": 101, "RACE": 6, "HISPAN": 0}]),
        ({"HHINCOME": 1, "STATEFIP": 25, "METRO": 2}, [{"EDUCD": 116, "RACE": 8, "HISPAN": 0}]),
    ])
    assert d["educ"].tolist() == [0, 1, 2, 3, 4]
    assert d["race_ethnicity"].tolist() == [0, 1, 2, 3, 4]
    assert d["region"].tolist() == [4, 3, 1, 2, 1]
    assert d["city"].tolist() == [1, 2, 0, 3, 3]
    assert d["metro"].tolist() == [1, 0, 1, 1, 2]
    assert d["metro_area"].tolist() == [14460, 0, 14460, 14460, 14460]


def test_work_status_hierarchy(extract):
    d, *_ = run(extract, [
        ({"HHINCOME": 1}, [{"EMPSTAT": 1, "CLASSWKR": 2, "UHRSWORK": 40, "WKSWORK2": 6}]),  # FT wage
        ({"HHINCOME": 1}, [{"EMPSTAT": 1, "CLASSWKR": 1, "UHRSWORK": 50, "WKSWORK2": 5}]),  # FT self-employed
        ({"HHINCOME": 1}, [{"EMPSTAT": 1, "CLASSWKR": 2, "UHRSWORK": 40, "WKSWORK2": 3}]),  # FT part-year
        ({"HHINCOME": 1}, [{"EMPSTAT": 1, "CLASSWKR": 2, "UHRSWORK": 20, "WKSWORK2": 6}]),  # part-time
        ({"HHINCOME": 1}, [{"EMPSTAT": 2, "CLASSWKR": 0, "UHRSWORK": 0, "WKSWORK2": 0}]),   # unemployed
        ({"HHINCOME": 1}, [{"EMPSTAT": 3, "AGE": 70, "INCSS": 20_000, "UHRSWORK": 0}]),     # retired
        ({"HHINCOME": 1}, [{"EMPSTAT": 3, "AGE": 30, "UHRSWORK": 0}]),                      # not working
    ])
    assert d["work_status"].tolist() == [0, 1, 2, 3, 4, 5, 6]
    assert d["hours_category"].tolist() == [0, 0, 0, 1, 3, 3, 3]


def test_breadwinner_income_mix_and_passive_source(extract):
    d, *_ = run(extract, [
        ({"HHINCOME": 100_000}, [{"INCWAGE": 95_000}, {"RELATED": 201, "INCWAGE": 5_000}]),   # sole, wages
        ({"HHINCOME": 100_000}, [{"INCWAGE": 50_000}, {"RELATED": 201, "INCWAGE": 50_000}]),  # co-earner
        ({"HHINCOME": 40_000}, [{"INCSS": 20_000, "EMPSTAT": 3}, {"RELATED": 201, "INCSUPP": 5_000, "EMPSTAT": 3,
                                                                     "INCRETIR": 15_000}]),     # SS+SSI wins
        ({"HHINCOME": 60_000}, [{"INCWAGE": 10_000, "INCINVST": 50_000}]),                      # capital
    ])
    assert d["breadwinner"].tolist() == [0, 2, 4, 0]
    assert d["passive_pct"].tolist() == [0, 0, 4, 3]
    assert d["passive_source"].tolist() == [4, 4, 0, 2]
    assert d["passive_inc"].tolist()[2] == round(40_000 * pp.ADJUST_BY_YEAR[2024])


def test_housing_and_cost_burden(extract):
    adj = pp.ADJUST_BY_YEAR[2024]
    d, *_ = run(extract, [
        ({"HHINCOME": 120_000, "OWNERSHP": 2, "RENTGRS": 2000}, [{}]),                  # 20%: under 30
        ({"HHINCOME": 60_000, "OWNERSHP": 2, "RENTGRS": 2000}, [{}]),                   # 40%
        ({"HHINCOME": 40_000, "OWNERSHP": 1, "MORTGAGE": 3, "OWNCOST": 2000}, [{}]),    # 60%, mortgage
        ({"HHINCOME": 40_000, "OWNERSHP": 1, "MORTGAGE": 1, "OWNCOST": 99999}, [{}]),   # free & clear, no cost: N/A
        ({"HHINCOME": 0, "OWNERSHP": 2, "RENTGRS": 900}, [{}]),                          # no income: N/A
    ])
    assert d["housing"].tolist() == [2, 2, 0, 1, 2]
    assert d["burden"].tolist() == [0, 1, 2, 3, 3]
    assert 12 * 2000 / (60_000 * adj) < 0.5  # the 40% case stays under 50% after ADJUST


def test_kids_and_youngest_child(extract):
    d, *_ = run(extract, [({"HHINCOME": 1}, [{"NCHILD": 2, "YNGCH": 3}]), ({"HHINCOME": 1}, [{"NCHILD": 1, "YNGCH": 15}]),
                          ({"HHINCOME": 1}, [{"NCHILD": 0, "YNGCH": 99}])])
    assert d["kids"].tolist() == [1, 1, 0]
    assert d["youngest_child"].tolist() == [1, 3, 0]


def test_topcoded_flag_marks_households_at_the_state_max(extract):
    hh = [({"HHINCOME": 700_000}, [{"INCWAGE": 650_000}]), ({"HHINCOME": 700_000}, [{"INCWAGE": 650_000}]),
          ({"HHINCOME": 80_000}, [{"INCWAGE": 80_000}]), ({"STATEFIP": 6, "HHINCOME": 90_000}, [{"INCWAGE": 90_000}])]
    d, *_ = run(extract, hh)
    assert d["topcoded"].tolist() == [1, 1, 0, 1]


# ---------------------------------------------------------------------------
# Browser sample
# ---------------------------------------------------------------------------
def test_stratified_sample_keeps_each_stratum_total_weight():
    rng = np.random.default_rng(1)
    d = pd.DataFrame({"year": rng.integers(0, 4, 20_000).astype(np.uint8),
                      "state": rng.choice([6, 25, 56], 20_000).astype(np.uint8),
                      "weight": rng.uniform(50, 150, 20_000).astype(np.float32), "id": 0})
    s = pp.stratified_sample(d, 2_000)
    assert abs(len(s) - 2_000) <= 12
    full = d.groupby(["year", "state"])["weight"].sum()
    samp = s.groupby(["year", "state"])["weight"].sum()
    assert ((samp / full - 1).abs() < 0.15).all()
    assert s["id"].tolist() == list(range(len(s)))


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------
def naive(v, w, q):
    o = np.argsort(v, kind="stable")
    cw = np.cumsum(w[o])
    return v[o][min(np.searchsorted(cw, q * cw[-1]), len(v) - 1)]


def naive_binned_median(v, w, width=2_500):
    """Census-style: find the $2,500 interval holding the median and interpolate linearly inside it."""
    x = naive(v, w, 0.5)
    lo = np.floor(x / width) * width
    below, inside = w[v < lo].sum(), w[(v >= lo) & (v < lo + width)].sum()
    return lo + width * (w.sum() / 2 - below) / inside


def test_cell_stats_match_a_brute_force_replicate_calculation():
    rng = np.random.default_rng(7)
    n = 3_000
    inc = np.round(rng.lognormal(11, 0.8, n))
    w = rng.uniform(20, 200, n)
    rep = (w[:, None] * rng.uniform(0.3, 1.7, (n, pp.N_REP))).astype(np.float32)
    cs = pp.CellStats(inc, w, rep)
    mask = rng.random(n) < 0.6
    c = cs.cell(cs.sorted_mask(mask))
    v, ww, R = inc[mask], w[mask], rep[mask].astype(np.float64)
    med = naive_binned_median(v, ww)
    mean = (v * ww).sum() / ww.sum()
    rmed = np.array([naive_binned_median(v, R[:, r]) for r in range(pp.N_REP)])
    rmean = (v @ R) / R.sum(0)
    assert c["med"] == round(med) and c["mean"] == round(mean)
    assert naive(v, ww, 0.5) - 2_500 <= med <= naive(v, ww, 0.5) + 2_500
    assert c["p25"] == round(naive(v, ww, 0.25)) and c["p75"] == round(naive(v, ww, 0.75))
    assert c["se_med"] == round(np.sqrt(4 / pp.N_REP * ((rmed - med) ** 2).sum()))
    assert c["se_mean"] == round(np.sqrt(4 / pp.N_REP * ((rmean - mean) ** 2).sum()))
    assert c["rel"] == 3 and c["n"] == mask.sum()


def test_small_cells_are_suppressed_and_reliability_tiers():
    inc = np.arange(600, dtype=float)
    cs = pp.CellStats(inc, np.ones(600), np.ones((600, pp.N_REP), np.float32))
    assert cs.cell(cs.sorted_mask(inc < 49)) is None
    assert cs.cell(cs.sorted_mask(inc < 60), with_se=False)["rel"] == 1
    assert cs.cell(cs.sorted_mask(inc < 300), with_se=False)["rel"] == 2


def test_build_key_sorts_dimensions():
    assert pp.build_key("national", {"work": 0, "age": 2}) == "national|age=2|work=0"
    assert pp.build_key("metro=14460", {}) == "metro=14460"


def test_compute_stats_scopes_and_keys():
    rng = np.random.default_rng(3)
    n = 4_000
    d = pd.DataFrame({c: rng.integers(0, 2, n).astype(np.uint8) for c, _ in pp.DIMS.values()})
    d["sex"] = rng.integers(1, 3, n).astype(np.uint8)
    d["region"] = rng.integers(1, 5, n).astype(np.uint8)
    d["state"] = np.where(d["region"] == 1, 25, 6).astype(np.uint8)
    d["metro_area"] = np.where(rng.random(n) < 0.5, 14460, 0).astype(np.uint32)
    d["inc"] = rng.integers(0, 200_000, n).astype(np.uint32)
    d["weight"] = np.float32(1)
    d["passive_pct"] = 0
    rep = np.ones((n, pp.N_REP), np.float32)
    stats = pp.compute_stats(d, rep, [2023, 2024], metro_min_n=100)
    for key in ["national", "national|age=1", "national|sex=2|work=1", "state=25", "state=6|age=0",
                "metro=14460", "metro=14460|kids=1", "national|region=2|work=1", "national|year=1"]:
        assert key in stats, key
    assert "metro=0" not in stats
    assert stats["national"]["wage_pct"] == 1.0
    assert stats["national"]["se_med"] == 0  # identical replicates: no variance


def test_median_is_not_pinned_by_heaped_round_numbers():
    # half the households report exactly $80,000: a plain weighted median sits on it for every replicate,
    # the interpolated one moves with the weights
    rng = np.random.default_rng(11)
    n = 4_000
    inc = np.where(rng.random(n) < 0.3, 80_000, np.round(rng.uniform(40_000, 120_000, n), -2))
    w = np.ones(n)
    rep = rng.uniform(0.5, 1.5, (n, pp.N_REP)).astype(np.float32)
    cs = pp.CellStats(inc, w, rep)
    c = cs.cell(cs.sorted_mask(np.ones(n, bool)))
    assert all(naive(inc, rep[:, r].astype(float), 0.5) == 80_000 for r in range(pp.N_REP))  # plain: stuck
    assert c["se_med"] > 0 and c["med"] != 80_000


# ---------------------------------------------------------------------------
# End to end on the fake extract
# ---------------------------------------------------------------------------
def test_main_writes_outputs(extract, tmp_path, monkeypatch):
    rng = np.random.default_rng(5)
    hh = []
    for i in range(400):
        inc = int(rng.integers(20_000, 150_000))
        hh.append(({"YEAR": 2021 if i % 2 else 2024, "HHINCOME": inc, "STATEFIP": [6, 25, 36][i % 3]},
                   [{"INCWAGE": int(inc * 0.9)}, {"RELATED": 201, "AGE": 38}]))
    dat, ddi = extract(hh)
    out = tmp_path / "out"
    monkeypatch.setattr(sys, "argv", ["preprocess.py", "--input", str(dat), "--ddi", str(ddi),
                                      "--output-dir", str(out), "--sample-size", "200", "--skip-validation"])
    pp.main()
    import json
    import pyarrow.ipc as ipc
    t = ipc.open_file(str(out / "national.arrow")).read_all()
    assert abs(t.num_rows - 200) <= 6 and "metro_area" in t.column_names and "burden" in t.column_names
    cb = json.loads((out / "codebook.json").read_text())
    assert cb["years"] == {"0": "2021", "1": "2024"}
    assert cb["metros"]["14460"]["name"].startswith("Boston")
    stats = json.loads((out / "stats_precomputed.json").read_text())
    assert stats["national"]["n"] == 400
