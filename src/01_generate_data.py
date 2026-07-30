"""
STEP 1: Generate the raw data
=============================

Real railcar maintenance data isn't public, so this script builds a realistic
stand-in. Everything downstream (SQL, forecasting, optimization) runs on these
files, so this is where the whole project starts.

What it creates in data/raw/:
  railcars.csv      one row per railcar in the fleet
  shops.csv         one row per repair shop
  defect_codes.csv  AAR-style "why did this car get pulled" codes
  repair_events.csv one row per bad order event (car pulled from service)

Two things worth knowing:

1. The numbers are anchored to how rail maintenance actually behaves. A car
   averages roughly one bad order a year, older cars fail more often, and
   volume rises in winter when cold weather chews up wheels and brakes. So the
   analysis has real patterns to find instead of noise.

2. The data is dirty on purpose. About 7 percent of repair event rows have a
   problem: duplicates, negative dwell times, missing labor hours, orphan car
   IDs, messy text. Step 3 finds and fixes those. Clean synthetic data would
   make the data quality work look fake.

Run:  python src/01_generate_data.py
"""

import os
import numpy as np
import pandas as pd

SEED = 42
rng = np.random.default_rng(SEED)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RAW = os.path.join(ROOT, "data", "raw")

FLEET_SIZE = 12000
START = pd.Timestamp("2023-01-01")
END = pd.Timestamp("2025-12-31")


# ---------------------------------------------------------------------------
# 1. Railcar master
# ---------------------------------------------------------------------------
# Car mix roughly mirrors a pooled flatcar and boxcar fleet. Each type has its
# own age profile and its own baseline failure rate, because an intermodal well
# car in daily service does not fail like a paper boxcar.

CAR_TYPES = {
    #                 share  min_yr max_yr capacity  bad orders per car per year
    "INTERMODAL_WELL": (0.34, 1998, 2024, 143, 0.78),
    "FLATCAR":         (0.26, 1979, 2023, 100, 0.62),
    "BOXCAR":          (0.22, 1975, 2021,  95, 0.86),
    "GONDOLA":         (0.12, 1981, 2022, 110, 0.70),
    "AUTORACK":        (0.06, 1990, 2024,  80, 0.55),
}

REGIONS = ["MIDWEST", "SOUTHEAST", "NORTHEAST", "SOUTHWEST", "WEST"]
REGION_SHARE = [0.28, 0.22, 0.14, 0.19, 0.17]


def build_railcars():
    rows = []
    car_number = 100000
    for car_type, (share, min_yr, max_yr, capacity, _) in CAR_TYPES.items():
        n = int(FLEET_SIZE * share)
        # Skew builds toward newer years so the age curve looks like a real fleet
        years = np.clip(
            np.round(rng.triangular(min_yr, max_yr - 4, max_yr, n)).astype(int),
            min_yr, max_yr,
        )
        for yr in years:
            car_number += 1
            rows.append({
                "car_id": f"TTX{car_number}",
                "car_type": car_type,
                "build_year": int(yr),
                "capacity_tons": capacity + int(rng.integers(-5, 6)),
                "home_region": rng.choice(REGIONS, p=REGION_SHARE),
            })
    df = pd.DataFrame(rows).sample(frac=1, random_state=SEED).reset_index(drop=True)
    return df


# ---------------------------------------------------------------------------
# 2. Repair shops
# ---------------------------------------------------------------------------
# Capacity is cars per day. Labor rate and specialty mix vary, which is what
# makes the assignment problem in step 6 non-trivial.

SHOPS = [
    # shop_id, name,          city,          state, region,      cap, $/hr, specialty
    ("SH01", "Bedford Park",  "Chicago",     "IL", "MIDWEST",      6, 82.0, "HEAVY"),
    ("SH02", "Rock Island",   "Rock Island", "IL", "MIDWEST",      4, 74.0, "RUNNING"),
    ("SH03", "Atlanta Yard",  "Atlanta",     "GA", "SOUTHEAST",    5, 71.0, "PROGRAM"),
    ("SH04", "Waycross",      "Waycross",    "GA", "SOUTHEAST",    3, 68.0, "RUNNING"),
    ("SH05", "Harrisburg",    "Harrisburg",  "PA", "NORTHEAST",    4, 89.0, "HEAVY"),
    ("SH06", "Fort Worth",    "Fort Worth",  "TX", "SOUTHWEST",    5, 70.0, "PROGRAM"),
    ("SH07", "Tucson",        "Tucson",      "AZ", "SOUTHWEST",    3, 73.0, "RUNNING"),
    ("SH08", "Roseville",     "Roseville",   "CA", "WEST",         4, 95.0, "HEAVY"),
    ("SH09", "Portland",      "Portland",    "OR", "WEST",         3, 88.0, "RUNNING"),
    ("SH10", "Kansas City",   "Kansas City", "MO", "MIDWEST",      4, 76.0, "PROGRAM"),
]

# Shops do not all run at the same speed. A shop short on staff or waiting on
# parts holds cars longer. This factor is deliberately NOT stored in shops.csv,
# because finding it is part of the analysis in step 4.
SHOP_DWELL_FACTOR = {
    "SH01": 0.88, "SH02": 1.02, "SH03": 0.94, "SH04": 1.41, "SH05": 1.34,
    "SH06": 0.91, "SH07": 1.08, "SH08": 0.97, "SH09": 1.16, "SH10": 0.86,
}


def build_shops():
    return pd.DataFrame(SHOPS, columns=[
        "shop_id", "shop_name", "city", "state", "region",
        "daily_capacity_cars", "labor_rate_usd", "primary_specialty",
    ])


# ---------------------------------------------------------------------------
# 3. Defect codes
# ---------------------------------------------------------------------------
# repair_class drives cost and dwell. Running repairs are quick and common,
# program repairs are planned, heavy repairs are rare and expensive.

DEFECTS = [
    # code, description,               class,     share, mean_hrs, mean_parts
    ("WH-101", "Wheel set thin flange",  "RUNNING", 0.155,  6.5,   1450),
    ("WH-107", "Wheel high impact",      "RUNNING", 0.092,  7.8,   1720),
    ("BR-210", "Brake shoe worn",        "RUNNING", 0.128,  3.2,    310),
    ("BR-224", "Brake valve failure",    "RUNNING", 0.061,  5.4,    880),
    ("BE-330", "Bearing overheated",     "HEAVY",   0.048, 14.2,   2650),
    ("CP-410", "Coupler knuckle broken", "RUNNING", 0.083,  4.1,    520),
    ("DR-455", "Draft gear damaged",     "HEAVY",   0.037, 18.6,   3400),
    ("SF-500", "Sill or frame cracked",  "HEAVY",   0.029, 41.5,   6100),
    ("DK-540", "Deck or floor damaged",  "PROGRAM", 0.074, 12.4,   1980),
    ("TR-610", "Truck side frame wear",  "PROGRAM", 0.055, 16.1,   2470),
    ("AR-700", "Air hose leak",          "RUNNING", 0.098,  2.4,    140),
    ("LD-750", "Lading damage repair",   "PROGRAM", 0.052,  9.7,   1230),
    ("PT-800", "Paint and stencil",      "PROGRAM", 0.043,  8.2,    640),
    ("MS-900", "Miscellaneous defect",   "RUNNING", 0.045,  4.8,    460),
]


def build_defects():
    return pd.DataFrame(DEFECTS, columns=[
        "defect_code", "defect_description", "repair_class",
        "occurrence_share", "mean_labor_hours", "mean_parts_cost_usd",
    ])


# ---------------------------------------------------------------------------
# 4. Repair events
# ---------------------------------------------------------------------------
# This is the fact table. For each car we draw a number of bad orders over the
# 3 year window using a Poisson process, where the rate depends on:
#     car type baseline  x  age factor  x  month seasonality  x  yearly drift
#
# Age factor: a 40 year old boxcar fails about twice as often as a new one.
# Seasonality: cold months damage wheels and brakes, so Dec to Feb runs high.
# Yearly drift: volume creeps up ~4 percent a year as the fleet ages.

# Not every defect is a winter defect. Cold weather cracks wheels, stiffens
# brake rigging and hardens air hoses. It does not make paint peel faster. This
# is the multiplier on how strongly each defect responds to the seasonal cycle,
# so January is not just "more of everything" but a different mix of work.
WINTER_SENSITIVITY = {
    "WH-101": 2.2, "WH-107": 2.2,          # wheels, the classic cold weather failure
    "BR-210": 1.8, "BR-224": 1.8,          # brakes
    "AR-700": 1.6,                          # air hoses harden and leak
    "BE-330": 1.5,                          # bearings
    "CP-410": 1.2, "DR-455": 1.2,          # couplers and draft gear, impact related
    "SF-500": 0.9,                          # frames, mostly load related
    "DK-540": 0.6, "TR-610": 0.6,          # decks and trucks, wear driven
    "LD-750": 0.2, "PT-800": 0.2, "MS-900": 0.2,   # barely seasonal
}

MONTH_FACTOR = {
    1: 1.24, 2: 1.19, 3: 1.06, 4: 0.94, 5: 0.90, 6: 0.88,
    7: 0.91, 8: 0.93, 9: 0.97, 10: 1.02, 11: 1.11, 12: 1.21,
}
YEAR_FACTOR = {2023: 1.00, 2024: 1.04, 2025: 1.085}


def build_repair_events(railcars, shops, defects):
    codes = defects["defect_code"].to_numpy()
    base_p = defects["occurrence_share"].to_numpy()
    base_p = base_p / base_p.sum()
    defect_lookup = defects.set_index("defect_code")

    # Precompute the defect mix for each of the 12 months once, instead of
    # renormalizing inside the loop 30,000 times.
    sens = np.array([WINTER_SENSITIVITY[c] for c in codes])
    month_defect_p = {}
    for m in range(1, 13):
        w = base_p * (1 + sens * (MONTH_FACTOR[m] - 1))
        month_defect_p[m] = w / w.sum()

    total_days = (END - START).days + 1
    events = []
    event_id = 500000

    base_rate = {k: v[4] for k, v in CAR_TYPES.items()}
    shops_by_region = shops.groupby("region")["shop_id"].apply(list).to_dict()

    for car in railcars.itertuples(index=False):
        age = 2025 - car.build_year
        # Age curve: flat until ~15 years, then climbs
        age_factor = 1.0 + 0.028 * max(0, age - 15)
        expected = base_rate[car.car_type] * age_factor * 3.0  # 3 year window
        n_events = rng.poisson(expected)
        if n_events == 0:
            continue

        # Place events in time, then reweight by month and year seasonality
        raw_days = rng.integers(0, total_days, size=n_events * 3)
        cand = START + pd.to_timedelta(raw_days, unit="D")
        weights = np.array([
            MONTH_FACTOR[d.month] * YEAR_FACTOR[d.year] for d in cand
        ])
        weights = weights / weights.sum()
        picked = rng.choice(len(cand), size=n_events, replace=False, p=weights)
        dates = sorted(cand[picked])

        for bo_date in dates:
            event_id += 1
            # Defect mix depends on the month, not just the overall share
            code = rng.choice(codes, p=month_defect_p[bo_date.month])
            d = defect_lookup.loc[code]

            # Labor hours: gamma so there is a right tail, like real repairs
            mean_h = float(d.mean_labor_hours)
            hours = float(rng.gamma(shape=4.0, scale=mean_h / 4.0))
            hours = round(max(0.5, hours), 1)

            parts = float(rng.gamma(shape=3.0, scale=d.mean_parts_cost_usd / 3.0))
            parts = round(max(20.0, parts), 2)

            # Shop: usually in the car's home region, sometimes routed out
            region = car.home_region if rng.random() > 0.18 else rng.choice(REGIONS)
            shop_id = rng.choice(shops_by_region[region])

            # Dwell days: hands-on time plus queue time. Heavy repairs wait for
            # parts, so they sit longer.
            queue = {"RUNNING": 1.6, "PROGRAM": 4.5, "HEAVY": 9.0}[d.repair_class]
            queue *= SHOP_DWELL_FACTOR[shop_id]
            dwell = max(1, int(round(rng.gamma(shape=2.2, scale=queue / 2.2) + hours / 8.0)))

            events.append({
                "event_id": f"E{event_id}",
                "car_id": car.car_id,
                "shop_id": shop_id,
                "defect_code": code,
                "bad_order_date": bo_date.strftime("%Y-%m-%d"),
                "release_date": (bo_date + pd.Timedelta(days=dwell)).strftime("%Y-%m-%d"),
                "labor_hours": hours,
                "parts_cost_usd": parts,
                "reported_by": rng.choice(["INSPECTOR", "CARRIER", "SHOP", "AUTOMATED"],
                                          p=[0.42, 0.29, 0.21, 0.08]),
            })

    df = pd.DataFrame(events).sort_values("bad_order_date").reset_index(drop=True)
    return df


# ---------------------------------------------------------------------------
# 5. Make it dirty
# ---------------------------------------------------------------------------
# Five failure modes that show up constantly in real operational data. Step 3
# has to catch every one of these.

def inject_quality_issues(events):
    df = events.copy()
    n = len(df)
    print(f"   clean rows before injection: {n:,}")

    # (a) Duplicate submissions, same event keyed twice
    dupes = df.sample(n=int(n * 0.021), random_state=SEED)
    df = pd.concat([df, dupes], ignore_index=True)
    print(f"   + {len(dupes):,} duplicate rows")

    # (b) Release date before bad order date, from data entry transposition
    idx = df.sample(n=int(n * 0.014), random_state=1).index
    df.loc[idx, "release_date"] = (
        pd.to_datetime(df.loc[idx, "bad_order_date"]) - pd.Timedelta(days=3)
    ).dt.strftime("%Y-%m-%d")
    print(f"   + {len(idx):,} rows with release before bad order")

    # (c) Missing labor hours, shop never closed out the billing record
    idx = df.sample(n=int(n * 0.031), random_state=2).index
    df.loc[idx, "labor_hours"] = np.nan
    print(f"   + {len(idx):,} rows with missing labor hours")

    # (d) Orphan car IDs not in the railcar master
    idx = df.sample(n=int(n * 0.008), random_state=3).index
    df.loc[idx, "car_id"] = ["TTX9" + str(900000 + i) for i in range(len(idx))]
    print(f"   + {len(idx):,} rows with orphan car IDs")

    # (e) Messy defect code text: casing and stray whitespace
    idx = df.sample(n=int(n * 0.026), random_state=4).index
    df.loc[idx, "defect_code"] = [
        (" " + c.lower() + " ") if i % 2 == 0 else c.replace("-", " ")
        for i, c in enumerate(df.loc[idx, "defect_code"])
    ]
    print(f"   + {len(idx):,} rows with malformed defect codes")

    # (f) A few extreme labor hour outliers, likely units entered wrong
    idx = df.sample(n=40, random_state=5).index
    df.loc[idx, "labor_hours"] = df.loc[idx, "labor_hours"].fillna(8) * 60
    print(f"   + {len(idx):,} rows with outlier labor hours")

    return df.sample(frac=1, random_state=SEED).reset_index(drop=True)


def main():
    os.makedirs(RAW, exist_ok=True)
    print("STEP 1: generating raw data")

    railcars = build_railcars()
    print(f"   railcars: {len(railcars):,}")

    shops = build_shops()
    defects = build_defects()

    events = build_repair_events(railcars, shops, defects)
    events = inject_quality_issues(events)

    railcars.to_csv(os.path.join(RAW, "railcars.csv"), index=False)
    shops.to_csv(os.path.join(RAW, "shops.csv"), index=False)
    defects.to_csv(os.path.join(RAW, "defect_codes.csv"), index=False)
    events.to_csv(os.path.join(RAW, "repair_events.csv"), index=False)

    print(f"   repair events written: {len(events):,}")
    print(f"   date range: {events.bad_order_date.min()} to {events.bad_order_date.max()}")
    print(f"   files in {RAW}")


if __name__ == "__main__":
    main()
