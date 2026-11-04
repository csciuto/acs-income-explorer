"""Current Population Survey, Annual Social and Economic Supplement (IPUMS CPS): extract checks, households,
derived variables. Survey years 2021-2025 = income years 2020-2024; the year filter uses the income year."""

import numpy as np
import pandas as pd

from . import common as C

SOURCE = "cps"
N_REP = 160
REP_PREFIX = "REPWT"
HOUSEHOLD_VARS = ["YEAR", "SERIAL", "ASECWTH", "CPI99", "STATEFIP", "METRO", "HHINCOME", "OWNERSHP"]
OPTIONAL_VARS = ["ASECFLAG", "REGION", "METFIPS"]
PERSON_VARS = ["PERNUM", "RELATE", "AGE", "SEX", "MARST", "RACE", "HISPAN", "EDUC", "EMPSTAT", "CLASSWKR",
               "WKSWORK2", "UHRSWORKLY", "UHRSWORKT", "UHRSWORK1", "NCHILD", "YNGCH", "SPMMORT",
               "INCWAGE", "INCBUS", "INCSS", "INCWELFR", "INCRETIR", "INCINT", "INCDIVID", "INCRENT"]
# Asked separately in the CPS; optional so an older extract still runs, but each one missing is reported
EXTRA_INCOME = ["INCFARM", "INCSSI", "INCDISAB", "INCSURV", "INCUNEMP", "INCWKCOM", "INCVET", "INCEDUC",
                "INCCHILD", "INCASIST", "INCOTHER"]
# Since the 2019 ASEC redesign, INCRETIR holds only retirement-account income (IRA, 401(k)) for people 58+;
# pensions and annuities are separate items. Without these, pension income is mostly missing.
# https://cps.ipums.org/cps/asec_2019_changes.shtml
PENSION_INCOME = ["INCPEN1", "INCPEN2", "INCRANN"]

REL_PARTNER = (1114, 1116, 1117)    # unmarried partner (1114 before the 2019 redesign, 1116/1117 after)
REL_ROOMMATE = (1113, 1115, 1241)   # partner/roommate, housemate/roommate, roomer/boarder/lodger

EXTRA_COLUMNS = ["city", "multi_job_proxy", "metro_area"]


def check(spec):
    C.require(spec, HOUSEHOLD_VARS + PERSON_VARS, REP_PREFIX, N_REP, "CPS")
    C.check_label(spec, "EDUC", 73, ["high school diploma"], "CPS")
    C.check_label(spec, "EDUC", 111, ["bachelor"], "CPS")
    C.check_label(spec, "RELATE", 1115, ["roommate", "housemate"], "CPS")
    C.check_label(spec, "EMPSTAT", 10, ["at work"], "CPS")
    missing = [v for v in PENSION_INCOME if v not in spec]
    if missing:
        raise SystemExit(f"The CPS extract lacks {', '.join(missing)}: since 2019 pensions and annuities are recorded "
                         "there, not in INCRETIR. Add them to the extract (see EXTRACT.md).")
    missing = [v for v in EXTRA_INCOME if v not in spec]
    if missing:
        print(f"  note: CPS extract lacks {', '.join(missing)}; they count as 0")


def build(p, spec, nominal=False):
    H = C.Households(p)
    if "ASECFLAG" in p and not (p["ASECFLAG"] == 1).all():
        raise SystemExit("CPS extract includes non-ASEC (March basic) records; select ASEC samples only.")
    inc = {v: C.income(p, spec, v) for v in PERSON_VARS + EXTRA_INCOME + PENSION_INCOME if v.startswith("INC")}
    earned = np.clip(inc["INCWAGE"] + inc["INCBUS"] + inc["INCFARM"], 0, None)

    h = {k: H.head(p[k]) for k in HOUSEHOLD_VARS + ["AGE", "SEX", "MARST", "RACE", "HISPAN", "EDUC", "EMPSTAT",
                                                     "CLASSWKR", "WKSWORK2", "UHRSWORKLY", "UHRSWORKT", "UHRSWORK1",
                                                     "NCHILD", "YNGCH", "SPMMORT"]}
    income_year = h["YEAR"] - 1
    years = sorted(np.unique(income_year).tolist())
    wt = h["ASECWTH"] / 10 ** spec["ASECWTH"]["dcml"]
    cpi = h["CPI99"] / 10 ** spec["CPI99"]["dcml"]
    # CPI99 in IPUMS CPS is for the income year; latest income year's factor puts everything in its dollars
    factor = np.ones(len(cpi)) if nominal else cpi / cpi[income_year == max(years)][0]
    keep = ~C.niu_mask(h["HHINCOME"], spec["HHINCOME"]["width"]) & (wt > 0)

    hhinc = h["HHINCOME"] * factor
    wage = H.sum(earned) * factor
    d = pd.DataFrame({
        "inc": C.dollars_u32(hhinc), "wage_inc": C.dollars_u32(wage), "passive_inc": C.dollars_u32(hhinc - wage),
        "weight": (wt / len(years)).astype(np.float32),
        "state": h["STATEFIP"].astype(np.uint8),
        "year": np.searchsorted(years, income_year).astype(np.uint8),
    })
    d["region"] = d["state"].map(C.REGION_OF_STATE).fillna(0).astype(np.uint8)
    d["age_bucket"] = C.age_bucket(h["AGE"])
    d["sex"] = h["SEX"].astype(np.uint8)
    d["marst"] = C.marst_code(h["MARST"], H.any(np.isin(p["RELATE"], REL_PARTNER)))

    e = h["EDUC"]  # 73 = high school diploma or equivalent; 81-92 some college/associate; 111 bachelor's; 123+ grad
    educ = np.zeros(len(e), dtype=np.uint8)
    educ[e == 73] = 1
    educ[(e >= 80) & (e <= 110)] = 2
    educ[e == 111] = 3
    educ[(e >= 120) & (e < 999)] = 4
    d["educ"] = educ

    mt = h["METRO"]   # 1 not in metro, 2 central city, 3 outside central city, 4 central city status unknown
    d["metro"] = np.where(mt == 1, 0, np.where(np.isin(mt, [2, 3, 4]), 1, 2)).astype(np.uint8)
    d["city"] = np.select([mt == 2, mt == 3, mt == 1], [0, 1, 2], 3).astype(np.uint8)
    # Metro area (CBSA code, same codes as the ACS's MET2013); 99998/99999 = not identified or missing -> 0.
    # The Census Bureau names only larger metros in the public CPS files.
    if "METFIPS" in p:
        mf = H.head(p["METFIPS"])
        d["metro_area"] = np.where(mf < 99998, mf, 0).astype(np.uint32)
    else:
        d["metro_area"] = np.zeros(len(d), np.uint32)

    d["kids"], d["youngest_child"], d["n_children"] = C.kids(h["NCHILD"], h["YNGCH"])

    emp, cls = h["EMPSTAT"], h["CLASSWKR"]
    hrs = np.where(h["UHRSWORKLY"] >= 997, 0, h["UHRSWORKLY"])
    working = np.isin(emp, [10, 12])
    d["work_status"], d["hours_category"] = C.work_status(
        working=working, unemployed=np.isin(emp, [20, 21, 22]),
        retired=(emp >= 30) & (emp <= 36) & (H.head(inc["INCSS"]) > 0) & (h["AGE"] >= 55),
        full_time=hrs >= 35, full_year=h["WKSWORK2"] >= 5,
        wage_worker=(cls >= 21) & (cls <= 28), self_employed=np.isin(cls, [13, 14]), hours=hrs)
    d["weeks_worked"] = pd.Series(h["WKSWORK2"]).map(C.WKSWORK2_MIDPOINTS).fillna(0).astype(np.uint8).values

    # multiple jobs: hours at all jobs minus hours at the main job (codes 997+ are "varies"/NIU)
    t, m1 = h["UHRSWORKT"], h["UHRSWORK1"]
    valid = (t < 997) & (m1 < 997) & working
    sec = np.where(valid, np.clip(t - m1, 0, None), 0)
    mj = np.zeros(len(sec), dtype=np.uint8)
    mj[valid & (sec >= 1) & (sec <= 14)] = 1
    mj[valid & (sec >= 15) & (sec <= 34)] = 2
    mj[valid & (sec >= 35)] = 3
    d["multi_job_proxy"] = mj

    d["earner_count"] = np.clip(H.sum(earned > 0), 0, 3).astype(np.uint8)
    d["breadwinner"] = C.breadwinner(H.head(earned), H.sum(earned))
    # the same four groups as the ACS: SS + SSI; retirement, survivor and disability pensions (the ACS asks these as
    # one item); interest + dividends + rent (one item in the ACS); public assistance
    d["passive_pct"], d["passive_source"] = C.income_mix(hhinc, wage, [
        H.sum(inc["INCSS"] + inc["INCSSI"]),
        H.sum(inc["INCRETIR"] + inc["INCPEN1"] + inc["INCPEN2"] + inc["INCRANN"] + inc["INCSURV"] + inc["INCDISAB"]),
        H.sum(np.clip(inc["INCINT"] + inc["INCDIVID"] + inc["INCRENT"], 0, None)),
        H.sum(inc["INCWELFR"])])

    race, hisp = h["RACE"], h["HISPAN"]
    is_hisp = (hisp >= 100) & (hisp < 900)
    re = np.full(len(race), 4, dtype=np.uint8)
    re[(race == 100) & ~is_hisp] = 0
    re[(race == 200) & ~is_hisp] = 1
    re[np.isin(race, [650, 651, 652]) & ~is_hisp] = 3
    re[is_hisp] = 2
    d["race_ethnicity"] = re

    spm = h["SPMMORT"]  # 1 owner with mortgage, 2 owner without, 3 renter
    housing = np.full(len(spm), 3, dtype=np.uint8)
    housing[spm == 1] = 0
    housing[spm == 2] = 1
    housing[spm == 3] = 2
    d["housing"] = housing

    d["topcoded"] = np.uint8(0)  # the CPS swaps top values between similar records instead of capping them
    d["has_roommate"] = H.any(np.isin(p["RELATE"], REL_ROOMMATE)).astype(np.uint8)
    d["hh_size"] = np.clip(H.size(), 1, 20).astype(np.uint8)

    d = d.loc[keep].reset_index(drop=True)
    d.insert(0, "id", np.arange(len(d), dtype=np.uint32))
    raw = pd.DataFrame({"year": income_year, "inc": h["HHINCOME"].astype(float), "w": wt}).loc[keep]
    year_medians = {int(y): C.weighted_median(g["inc"].values, g["w"].values) for y, g in raw.groupby("year")}
    # how much of HHINCOME the tracked items account for (checks that no income source is missing)
    tracked = sum(H.sum(inc[v]) for v in inc)
    coverage = float(np.average(np.clip(tracked[keep] / np.clip(h["HHINCOME"][keep], 1, None), 0, 2),
                                weights=wt[keep]))
    meta = {"years": years, "year_medians": year_medians, "dollars": f"{max(years)} dollars",
            "n_households": int(len(d)), "income_coverage": coverage}
    return d, keep, meta
