#!/usr/bin/env python3
"""
Preprocessor for the American Income Explorer: turns IPUMS extracts (fixed-width .dat.gz + DDI .xml; see
EXTRACT.md) into the files the site loads.

    python preprocess.py --acs usa_00018.dat.gz --acs-ddi usa_00018.xml \\
                         --cps cps_00007.dat.gz --cps-ddi cps_00007.xml --output-dir ./docs/data

Either source can be rebuilt on its own; the other's files and codebook entry are kept. Output:

    codebook.json                 labels, states, and per source: years, columns, metros, local areas, notes
    <source>/national.arrow       stratified sample of households (by year x state) for the chart
    <source>/stats.json           exact statistics from ALL households, with replicate-weight standard errors
    acs/local/<state>.json        local-area (PUMA) statistics, loaded when an area is picked
    acs/local/<state>.arrow       up to 300 households per local area in that state, for its chart
"""

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from pipeline import acs, cps
from pipeline import common as C

SAMPLE = {"acs": 300_000, "cps": 300_000}
LOCAL_SAMPLE_PER_AREA = 300

SHARED_COLUMNS = ["id", "inc", "wage_inc", "passive_inc", "weight", "state", "year", "region", "age_bucket", "sex",
                  "marst", "educ", "metro", "kids", "youngest_child", "n_children", "work_status", "hours_category",
                  "weeks_worked", "earner_count", "breadwinner", "passive_pct", "passive_source", "race_ethnicity",
                  "housing", "topcoded", "has_roommate", "hh_size"]

SHARED_DIMS = {
    "age": ("age_bucket", list(range(8))), "sex": ("sex", [1, 2]), "marst": ("marst", list(range(5))),
    "educ": ("educ", list(range(5))), "region": ("region", [1, 2, 3, 4]), "city": ("city", [0, 1, 2]),
    "work": ("work_status", list(range(7))), "kids": ("kids", [0, 1]), "race": ("race_ethnicity", list(range(5))),
    "house": ("housing", [0, 1, 2]), "earners": ("earner_count", [0, 1, 2, 3]),
    "bread": ("breadwinner", list(range(5))), "ppct": ("passive_pct", list(range(5))),
    "psrc": ("passive_source", list(range(5))),
}
SOURCE_DIMS = {"acs": {"burden": ("burden", [0, 1, 2])}, "cps": {"mjob": ("multi_job_proxy", [0, 1, 2, 3])}}

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
    "multi_job_proxy": {"0": "No secondary work", "1": "1–14 hrs secondary", "2": "15–34 hrs secondary",
                        "3": "35+ hrs secondary"},
}

NOTES = {
    "acs": {
        "name": "American Community Survey",
        "short": "ACS",
        "about": "IPUMS USA, ACS 5-year sample 2020–2024 (about 5% of US households). Income covers the 12 months "
                 "before each interview, put into 2024 dollars with the Census Bureau's ADJINC.",
        "strengths": "Large enough for states, metro areas, local areas and narrow slices. Housing costs.",
        "se": "Standard errors from the 80 ACS household replicate weights (successive difference replication).",
        "topcodes": "Income items above a state's cutoff are replaced by the state mean of those values; "
                    "households with a member at that value are flagged as topcoded.",
    },
    "cps": {
        "name": "Current Population Survey (ASEC)",
        "short": "CPS",
        "about": "IPUMS CPS, Annual Social and Economic Supplement 2021–2025 (income years 2020–2024), in 2024 "
                 "dollars with the CPI-U. The Census Bureau's official source for national income.",
        "strengths": "About 50 income questions (the ACS has 8), so income sources such as pensions, interest and "
                     "dividends are measured better. Calendar-year income. Multiple jobs.",
        "se": "Standard errors from the 160 CPS household replicate weights (Fay's balanced repeated replication).",
        "topcodes": "The CPS swaps the highest values between similar records instead of capping them, so no "
                    "household is flagged.",
    },
}

SOURCES = {"acs": acs, "cps": cps}


def validate(name, d, meta):
    problems = []
    for col, allowed in {"work_status": range(7), "age_bucket": range(8), "marst": range(5), "educ": range(5),
                         "region": range(1, 5), "sex": (1, 2), "city": range(4), "housing": range(4),
                         "race_ethnicity": range(5), "breadwinner": range(5), "passive_pct": range(5),
                         "passive_source": range(5), "earner_count": range(4)}.items():
        bad = set(np.unique(d[col]).tolist()) - set(allowed)
        if bad:
            problems.append(f"{col} has unexpected values {sorted(bad)}")
    for y, med in meta["year_medians"].items():
        if not 55_000 <= med <= 95_000:
            problems.append(f"{y} median household income ${med:,.0f} is outside $55k-$95k")
    share = float(np.average(d["passive_pct"] == 0, weights=d["weight"]))
    if not 0.35 <= share <= 0.75:
        problems.append(f"wage-primary share {share:.1%} outside 35-75%")
    if (d["wage_inc"] > 20_000_000).any():
        problems.append("household wage income above $20M: NIU codes leaking into sums?")
    shares = np.bincount(d["educ"], weights=d["weight"], minlength=5) / d["weight"].sum()
    if not 0.15 <= shares[1] <= 0.40:
        problems.append(f"'HS diploma' is {shares[1]:.1%} of households; expected 15-40% (education coding?)")
    return [f"{name}: {p}" for p in problems]


def run_source(name, dat, ddi, out, args, codebook):
    mod = SOURCES[name]
    step = C.step
    step(f"{name.upper()}: reading the DDI codebook")
    spec = C.parse_ddi(ddi)
    mod.check(spec)
    step(f"{name.upper()}: reading {dat}")
    want = (mod.HOUSEHOLD_VARS + mod.PERSON_VARS + getattr(mod, "OPTIONAL_VARS", []) + getattr(mod, "EXTRA_INCOME", [])
            + getattr(mod, "PENSION_INCOME", []))
    p, rep_all = C.read_extract(dat, spec, want, mod.REP_PREFIX, mod.N_REP)
    step(f"{name.upper()}: building households")
    d, keep, meta = mod.build(p, spec, nominal=args.nominal)
    del p
    years = meta["years"]
    rep = rep_all[keep]
    if not meta.get("multiyear"):
        rep = rep / len(years)
    del rep_all
    print(f"  {len(d):,} households, years {years}")
    for y, m in meta["year_medians"].items():
        print(f"  {y}: median household income ${m:,.0f} (that year's dollars)")
    if "income_coverage" in meta:
        print(f"  tracked income items cover {meta['income_coverage']:.1%} of household income")
    shares = np.bincount(d["passive_source"], weights=d["weight"], minlength=5) / d["weight"].sum()
    print("  main non-wage source: " + ", ".join(f"{LABELS['passive_source'][str(i)]} {s:.1%}"
                                               for i, s in enumerate(shares)))

    problems = validate(name, d, meta)
    for pr in problems:
        print("  PROBLEM:", pr)
    if problems and not args.skip_validation:
        sys.exit("Stopping: fix the problems above or rerun with --skip-validation to inspect output.")

    sd = out / name
    sd.mkdir(parents=True, exist_ok=True)
    columns = SHARED_COLUMNS + mod.EXTRA_COLUMNS
    step(f"{name.upper()}: writing national.arrow (sample of {args.sample_size or SAMPLE[name]:,})")
    s = C.stratified_sample(d, args.sample_size or SAMPLE[name])
    C.write_arrow(s, columns, sd / "national.arrow")
    print(f"  {len(s):,} rows, {(sd / 'national.arrow').stat().st_size / 1e6:.1f}MB")

    dims = {**SHARED_DIMS, **SOURCE_DIMS[name], "year": ("year", list(range(len(years))))}
    entry = {
        **NOTES[name],
        "years": {str(i): str(y) for i, y in enumerate(years)},
        "columns": columns,
        "dims": {k: v[0] for k, v in dims.items()},
        "n_households": meta["n_households"],
        "dollars": meta["dollars"],
    }
    if name == "acs":
        met = spec["MET2013"]["labels"]
        counts = d.groupby("metro_area").size()
        entry["metros"] = {str(int(c)): {"name": met.get(int(c), str(int(c))), "n": int(n)}
                           for c, n in counts.items() if c != 0}
        if (d["puma"] > 0).any():
            names = json.loads((Path(__file__).parent / "geo" / "puma_names_2020.json").read_text())
            pc = d.groupby("puma").size()
            entry["local_areas"] = {str(int(c)): {"name": names.get(f"{int(c):07d}", f"Area {int(c)}"),
                                                  "state": int(c) // 100_000, "n": int(n)} for c, n in pc.items()}
    codebook["sources"][name] = entry

    if not args.skip_stats:
        step(f"{name.upper()}: statistics from all households")
        stats = C.compute_stats(d, rep, dims)
        (sd / "stats.json").write_text(json.dumps(stats, separators=(",", ":")))
        print(f"  {len(stats):,} cells, {(sd / 'stats.json').stat().st_size / 1e6:.1f}MB")
        if name == "acs" and (d["puma"] > 0).any():
            step("ACS: local-area statistics")
            ld = sd / "local"
            ld.mkdir(exist_ok=True)
            local_dims = {k: v for k, v in dims.items() if k not in ("region", "city", "year")}
            local = C.compute_local_stats(d, rep, local_dims)
            for st, cells in local.items():
                (ld / f"{st:02d}.json").write_text(json.dumps(cells, separators=(",", ":")))
                sub = d[d["state"] == st]
                parts = []
                for _, g in sub.groupby("puma"):
                    k = min(len(g), LOCAL_SAMPLE_PER_AREA)
                    pick = g.sample(n=k, random_state=1) if k < len(g) else g
                    pick = pick.copy()
                    pick["weight"] = (pick["weight"] * len(g) / k).astype(np.float32)
                    parts.append(pick)
                ls = pd.concat(parts).reset_index(drop=True)
                ls["id"] = np.arange(len(ls), dtype=np.uint32)
                C.write_arrow(ls, columns, ld / f"{st:02d}.arrow")
            total = sum(f.stat().st_size for f in ld.iterdir())
            print(f"  {len(local)} states, {sum(len(v) for v in local.values()):,} cells, {total / 1e6:.1f}MB")
    return d


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--acs")
    ap.add_argument("--acs-ddi")
    ap.add_argument("--cps")
    ap.add_argument("--cps-ddi")
    ap.add_argument("--output-dir", default="./docs/data")
    ap.add_argument("--sample-size", type=int, help="households in each national.arrow (default 300,000)")
    ap.add_argument("--nominal", action="store_true", help="keep each year's own dollars")
    ap.add_argument("--skip-stats", action="store_true")
    ap.add_argument("--skip-validation", action="store_true")
    args = ap.parse_args()
    if not (args.acs or args.cps):
        ap.error("give --acs/--acs-ddi and/or --cps/--cps-ddi")
    for s in ("acs", "cps"):
        if bool(getattr(args, s)) != bool(getattr(args, f"{s}_ddi")):
            ap.error(f"--{s} and --{s}-ddi go together")

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    cb_path = out / "codebook.json"
    codebook = json.loads(cb_path.read_text()) if cb_path.exists() else {}
    codebook.setdefault("sources", {})
    t0 = time.time()
    for s in ("acs", "cps"):
        if getattr(args, s):
            run_source(s, getattr(args, s), getattr(args, f"{s}_ddi"), out, args, codebook)
    codebook["labels"] = LABELS
    codebook["states"] = {str(k): {"name": v, "abbr": C.STATE_ABBR[k]} for k, v in C.FIPS_NAMES.items()}
    codebook["sources"] = {k: codebook["sources"][k] for k in ("acs", "cps") if k in codebook["sources"]}
    cb_path.write_text(json.dumps(codebook, indent=1, ensure_ascii=False))
    print(f"  codebook.json {cb_path.stat().st_size / 1024:.0f}KB")
    C.step(f"Done in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
