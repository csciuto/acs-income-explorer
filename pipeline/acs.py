"""American Community Survey (IPUMS USA): extract checks, households, derived variables.

Handles the 5-year sample (one file, MULTYEAR gives each household's survey year, all on 2020 PUMAs, dollars already
in the final year's dollars, weights describing an average year) and pooled 1-year samples (the original build)."""

import sys

import numpy as np
import pandas as pd

from . import common as C

SOURCE = "acs"
N_REP = 80
REP_PREFIX = "REPWT"
HOUSEHOLD_VARS = ["YEAR", "SERIAL", "HHWT", "GQ", "CPI99", "STATEFIP", "MET2013", "METRO", "HHINCOME",
                  "OWNERSHP", "MORTGAGE", "RENTGRS", "OWNCOST"]
OPTIONAL_VARS = ["MULTYEAR", "ADJUST", "PUMA"]
PERSON_VARS = ["PERNUM", "RELATED", "AGE", "SEX", "MARST", "RACE", "HISPAN", "EDUCD", "EMPSTAT", "CLASSWKR",
               "WKSWORK2", "UHRSWORK", "NCHILD", "YNGCH", "INCWAGE", "INCBUS00", "INCSS", "INCSUPP", "INCWELFR",
               "INCRETIR", "INCINVST", "INCOTHER"]
TOPCODED_VARS = ["INCWAGE", "INCBUS00", "INCRETIR", "INCINVST"]

# Census ADJINC per 1-year sample (IPUMS ADJUST), used for 1-year extracts without ADJUST.
# Source: https://usa.ipums.org/usa/acsincadj.shtml
ADJUST_BY_YEAR = {2021: 1.029928, 2022: 1.042311, 2023: 1.019518, 2024: 1.015250}

REL_PARTNER = 1114           # Unmarried Partner
REL_ROOMMATE = (1115, 1241)  # Housemate/Roommate; Roomers/boarders/lodgers

# Columns written to the browser files, beyond the shared ones
EXTRA_COLUMNS = ["city", "metro_area", "puma", "burden"]


def check(spec):
    C.require(spec, HOUSEHOLD_VARS + PERSON_VARS, REP_PREFIX, N_REP, "ACS")
    C.check_label(spec, "RELATED", REL_PARTNER, ["partner"], "ACS")
    C.check_label(spec, "RELATED", 1115, ["room"], "ACS")
    C.check_label(spec, "RELATED", 1241, ["roomer"], "ACS")
    C.check_label(spec, "EDUCD", 101, ["bachelor"], "ACS")


def is_multiyear(p):
    return "MULTYEAR" in p and len(np.unique(p["YEAR"])) == 1 and len(np.unique(p["MULTYEAR"])) > 1


def build(p, spec, nominal=False):
    """One row per household (group quarters dropped) with the explorer's variables, plus the keep mask."""
    H = C.Households(p)
    inc = {v: C.income(p, spec, v) for v in ["INCWAGE", "INCBUS00", "INCSS", "INCSUPP", "INCWELFR", "INCRETIR",
                                            "INCINVST", "INCOTHER"]}
    wage_bus = np.clip(inc["INCWAGE"] + inc["INCBUS00"], 0, None)

    multi = is_multiyear(p)
    survey_year = p["MULTYEAR"] if multi else p["YEAR"]
    # topcodes: each item above a state's cutoff is replaced by the state's mean of those values, so a topcoded
    # amount is the (year, state) maximum
    key = (survey_year - 2000) * 100 + p["STATEFIP"]
    top = np.zeros(len(key), dtype=bool)
    for v in TOPCODED_VARS:
        mx = pd.Series(inc[v]).groupby(key).transform("max").values
        top |= (inc[v] == mx) & (inc[v] > 0)

    h = {k: H.head(p[k]) for k in HOUSEHOLD_VARS + ["AGE", "SEX", "MARST", "RACE", "HISPAN", "EDUCD", "EMPSTAT",
                                                     "CLASSWKR", "WKSWORK2", "UHRSWORK", "NCHILD", "YNGCH"]}
    year = H.head(survey_year)
    years = sorted(np.unique(year).tolist())
    hhwt = h["HHWT"] / 10 ** spec["HHWT"]["dcml"]

    # dollars: survey-year (or final-year, for 5-year files) dollars via ADJUST; 1-year pooled then x CPI99 ratio
    if "ADJUST" in p:
        adjust = H.head(p["ADJUST"]) / 10 ** spec["ADJUST"]["dcml"]
    else:
        missing = sorted(set(years) - set(ADJUST_BY_YEAR))
        if missing or multi:
            sys.exit(f"No ADJUST factor for {missing or 'this multi-year sample'}: add ADJUST to the extract "
                     "(values at https://usa.ipums.org/usa/acsincadj.shtml).")
        adjust = pd.Series(year).map(ADJUST_BY_YEAR).values
    if multi or nominal:
        factor = adjust
    else:
        cpi = h["CPI99"] / 10 ** spec["CPI99"]["dcml"]
        cpi_latest = cpi[year == max(years)][0]
        factor = adjust * cpi / cpi_latest

    keep = np.isin(h["GQ"], [1, 2, 5]) & ~C.niu_mask(h["HHINCOME"], spec["HHINCOME"]["width"])
    n_div = 1 if multi else len(years)   # 5-year weights already describe an average year

    hhinc = h["HHINCOME"] * factor
    wage = H.sum(wage_bus) * factor
    d = pd.DataFrame({
        "inc": C.dollars_u32(hhinc), "wage_inc": C.dollars_u32(wage), "passive_inc": C.dollars_u32(hhinc - wage),
        "weight": (hhwt / n_div).astype(np.float32),
        "state": h["STATEFIP"].astype(np.uint8),
        "year": np.searchsorted(years, year).astype(np.uint8),
    })
    d["region"] = d["state"].map(C.REGION_OF_STATE).fillna(0).astype(np.uint8)
    d["age_bucket"] = C.age_bucket(h["AGE"])
    d["sex"] = h["SEX"].astype(np.uint8)
    d["marst"] = C.marst_code(h["MARST"], H.any(p["RELATED"] == REL_PARTNER))

    e = h["EDUCD"]
    educ = np.zeros(len(e), dtype=np.uint8)              # less than high school
    educ[(e >= 62) & (e <= 64)] = 1                      # HS diploma or GED
    educ[(e >= 65) & (e <= 100)] = 2                     # some college, associate's
    educ[e == 101] = 3                                   # bachelor's
    educ[(e >= 110) & (e < 999)] = 4                     # graduate / professional
    d["educ"] = educ

    mt = h["METRO"]   # 1 not in metro, 3 suburb, 5 principal city, 2/4 can't tell
    d["metro"] = np.where(mt == 1, 0, np.where(np.isin(mt, [3, 4, 5]), 1, 2)).astype(np.uint8)
    d["city"] = np.select([mt == 5, mt == 3, mt == 1], [0, 1, 2], 3).astype(np.uint8)
    d["metro_area"] = h["MET2013"].astype(np.uint32)
    d["puma"] = (h["STATEFIP"] * 100_000 + H.head(p["PUMA"])).astype(np.uint32) if "PUMA" in p else np.uint32(0)

    d["kids"], d["youngest_child"], d["n_children"] = C.kids(h["NCHILD"], h["YNGCH"])

    emp, cls, hrs = h["EMPSTAT"], h["CLASSWKR"], h["UHRSWORK"]
    working = emp == 1
    d["work_status"], d["hours_category"] = C.work_status(
        working=working, unemployed=emp == 2,
        retired=(emp == 3) & (H.head(inc["INCSS"]) > 0) & (h["AGE"] >= 55),
        full_time=hrs >= 35, full_year=h["WKSWORK2"] >= 5, wage_worker=cls == 2, self_employed=cls == 1, hours=hrs)
    d["weeks_worked"] = pd.Series(h["WKSWORK2"]).map(C.WKSWORK2_MIDPOINTS).fillna(0).astype(np.uint8).values

    d["earner_count"] = np.clip(H.sum(wage_bus > 0), 0, 3).astype(np.uint8)
    d["breadwinner"] = C.breadwinner(H.head(wage_bus), H.sum(wage_bus))
    d["passive_pct"], d["passive_source"] = C.income_mix(hhinc, wage, [
        H.sum(inc["INCSS"] + inc["INCSUPP"]), H.sum(inc["INCRETIR"]),
        H.sum(np.clip(inc["INCINVST"], 0, None)), H.sum(inc["INCWELFR"])])

    race, hisp = h["RACE"], h["HISPAN"]
    nh = ~np.isin(hisp, [1, 2, 3, 4])
    re = np.full(len(race), 4, dtype=np.uint8)
    re[(race == 1) & nh] = 0
    re[(race == 2) & nh] = 1
    re[np.isin(race, [4, 5, 6]) & nh] = 3
    re[~nh] = 2
    d["race_ethnicity"] = re

    own, mort = h["OWNERSHP"], h["MORTGAGE"]
    housing = np.full(len(own), 3, dtype=np.uint8)
    housing[(own == 1) & np.isin(mort, [3, 4])] = 0
    housing[(own == 1) & (mort == 1)] = 1
    housing[own == 2] = 2
    d["housing"] = housing

    # housing cost burden: 12 x monthly gross rent or owner costs / household income (same dollars both sides)
    rent, oc = h["RENTGRS"], h["OWNCOST"]
    monthly = np.where(own == 2, rent, np.where((own == 1) & ~C.niu_mask(oc, spec["OWNCOST"]["width"]), oc, 0))
    adj_inc = h["HHINCOME"] * adjust
    ok = (monthly > 0) & (adj_inc > 0)
    share = 12 * monthly / np.clip(adj_inc, 1, None)
    burden = np.full(len(own), 3, dtype=np.uint8)
    burden[ok] = np.select([share[ok] < 0.30, share[ok] < 0.50], [0, 1], 2)
    d["burden"] = burden

    d["topcoded"] = H.any(top).astype(np.uint8)
    d["has_roommate"] = H.any(np.isin(p["RELATED"], REL_ROOMMATE)).astype(np.uint8)
    d["hh_size"] = np.clip(H.size(), 1, 20).astype(np.uint8)

    d = d.loc[keep].reset_index(drop=True)
    d.insert(0, "id", np.arange(len(d), dtype=np.uint32))
    raw = pd.DataFrame({"year": year, "inc": h["HHINCOME"] * adjust, "w": hhwt}).loc[keep]
    year_medians = {int(y): C.weighted_median(g["inc"].values.astype(float), g["w"].values)
                    for y, g in raw.groupby("year")}
    meta = {"years": years, "multiyear": bool(multi), "year_medians": year_medians,
            "dollars": f"{max(years)} dollars", "n_households": int(len(d))}
    return d, keep, meta
