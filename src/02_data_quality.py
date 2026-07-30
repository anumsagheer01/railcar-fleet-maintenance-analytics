"""
STEP 2: Validate and clean
==========================

The job description asks for someone who can "identify trends, validate results,
and flag data quality concerns that may affect analytical outcomes." This step is
that, written down.

It runs eight checks against the raw repair events, writes a report saying what
failed and how much, then produces a clean table for everything downstream.

The rule I follow: never silently drop a row. Every record either passes, gets
repaired with a documented rule, or gets quarantined to its own file so someone
can go ask the shop what happened.

Outputs:
  data/clean/repair_events_clean.csv   rows safe to model on
  data/clean/quarantine.csv            rows pulled out, with a reason column
  outputs/data_quality_report.csv      one row per check, for the dashboard

Run:  python src/02_data_quality.py
"""

import os
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RAW = os.path.join(ROOT, "data", "raw")
CLEAN = os.path.join(ROOT, "data", "clean")
OUT = os.path.join(ROOT, "outputs")

# A repair taking more than this many hours is almost certainly a units error.
# The worst real defect in the code table averages 41 hours, so 240 is generous.
LABOR_HOURS_CEILING = 240
DWELL_DAYS_CEILING = 180

checks = []


def log(check, severity, failed, total, action):
    pct = round(100 * failed / total, 3) if total else 0.0
    checks.append({
        "check_name": check,
        "severity": severity,
        "rows_failed": failed,
        "rows_scanned": total,
        "pct_failed": pct,
        "action_taken": action,
    })
    flag = {"HIGH": "!!", "MEDIUM": " !", "LOW": "  "}[severity]
    print(f"  {flag} {check:<34} {failed:>6,} rows ({pct:>6.3f}%)  ->  {action}")


def main():
    os.makedirs(CLEAN, exist_ok=True)
    os.makedirs(OUT, exist_ok=True)

    events = pd.read_csv(os.path.join(RAW, "repair_events.csv"))
    railcars = pd.read_csv(os.path.join(RAW, "railcars.csv"))
    defects = pd.read_csv(os.path.join(RAW, "defect_codes.csv"))
    shops = pd.read_csv(os.path.join(RAW, "shops.csv"))

    n0 = len(events)
    print(f"STEP 2: validating {n0:,} raw repair event rows\n")

    quarantine = []

    def quarantine_rows(mask, reason):
        if mask.sum():
            bad = events.loc[mask].copy()
            bad["quarantine_reason"] = reason
            quarantine.append(bad)

    # -- Check 1: exact duplicate event IDs -----------------------------------
    # Shops resubmit billing records. Keep the first, drop the rest.
    dup_mask = events.duplicated(subset=["event_id"], keep="first")
    log("duplicate_event_id", "HIGH", int(dup_mask.sum()), n0, "dropped duplicates")
    events = events.loc[~dup_mask].reset_index(drop=True)

    # -- Check 2: defect code formatting -------------------------------------
    # Fix casing and whitespace before joining, or the join quietly loses rows.
    valid_codes = set(defects["defect_code"])
    raw_code = events["defect_code"].astype(str)
    normalized = (raw_code.str.strip().str.upper().str.replace(" ", "-", regex=False))
    fixed = (raw_code != normalized) & normalized.isin(valid_codes)
    log("defect_code_format", "MEDIUM", int(fixed.sum()), len(events),
        "normalized casing and separators")
    events["defect_code"] = normalized

    # -- Check 3: defect codes that still don't match the master -------------
    unknown = ~events["defect_code"].isin(valid_codes)
    log("defect_code_not_in_master", "HIGH", int(unknown.sum()), len(events),
        "quarantined" if unknown.sum() else "none found")
    quarantine_rows(unknown, "defect_code not in master")
    events = events.loc[~unknown].reset_index(drop=True)

    # -- Check 4: orphan car IDs ---------------------------------------------
    # A repair billed against a car we don't own. Real cause is usually a
    # mistyped reporting mark. These cannot be joined to car type or age, so
    # they would silently distort any per-type analysis.
    known_cars = set(railcars["car_id"])
    orphan = ~events["car_id"].isin(known_cars)
    log("orphan_car_id", "HIGH", int(orphan.sum()), len(events), "quarantined")
    quarantine_rows(orphan, "car_id not in railcar master")
    events = events.loc[~orphan].reset_index(drop=True)

    # -- Check 5: orphan shop IDs -------------------------------------------
    known_shops = set(shops["shop_id"])
    bad_shop = ~events["shop_id"].isin(known_shops)
    log("orphan_shop_id", "HIGH", int(bad_shop.sum()), len(events),
        "quarantined" if bad_shop.sum() else "none found")
    quarantine_rows(bad_shop, "shop_id not in shop master")
    events = events.loc[~bad_shop].reset_index(drop=True)

    # -- Check 6: date logic -------------------------------------------------
    # Release before bad order means dwell is negative, which would drag down
    # every average dwell number on the dashboard.
    events["bad_order_date"] = pd.to_datetime(events["bad_order_date"], errors="coerce")
    events["release_date"] = pd.to_datetime(events["release_date"], errors="coerce")
    events["dwell_days"] = (events["release_date"] - events["bad_order_date"]).dt.days

    bad_dates = events["dwell_days"].isna() | (events["dwell_days"] < 0)
    log("negative_or_missing_dwell", "HIGH", int(bad_dates.sum()), len(events),
        "quarantined")
    quarantine_rows(bad_dates, "release_date before bad_order_date")
    events = events.loc[~bad_dates].reset_index(drop=True)

    long_dwell = events["dwell_days"] > DWELL_DAYS_CEILING
    log("dwell_over_180_days", "LOW", int(long_dwell.sum()), len(events),
        "flagged, kept in dataset")

    # -- Check 7: labor hour outliers ---------------------------------------
    # Capping instead of dropping. The repair happened, only the number is
    # wrong, so throwing the row away would understate repair volume.
    outlier = events["labor_hours"] > LABOR_HOURS_CEILING
    log("labor_hours_outlier", "MEDIUM", int(outlier.sum()), len(events),
        f"capped at {LABOR_HOURS_CEILING} hours")
    events.loc[outlier, "labor_hours"] = LABOR_HOURS_CEILING

    # -- Check 8: missing labor hours ---------------------------------------
    # Filled with the median for that defect code, not the overall median. A
    # missing brake shoe job and a missing frame repair are not the same size.
    missing = events["labor_hours"].isna()
    med_by_code = events.groupby("defect_code")["labor_hours"].median()
    events["labor_hours"] = events["labor_hours"].fillna(
        events["defect_code"].map(med_by_code)
    )
    events["labor_hours_imputed"] = missing
    log("missing_labor_hours", "MEDIUM", int(missing.sum()), len(events),
        "imputed with median for that defect code")

    # -- Build the modeling table -------------------------------------------
    events = events.merge(
        railcars[["car_id", "car_type", "build_year", "home_region"]],
        on="car_id", how="left",
    ).merge(
        defects[["defect_code", "defect_description", "repair_class"]],
        on="defect_code", how="left",
    ).merge(
        shops[["shop_id", "shop_name", "region", "labor_rate_usd"]],
        on="shop_id", how="left",
    )

    events["car_age_years"] = events["bad_order_date"].dt.year - events["build_year"]
    events["labor_cost_usd"] = (events["labor_hours"] * events["labor_rate_usd"]).round(2)
    events["total_cost_usd"] = (events["labor_cost_usd"] + events["parts_cost_usd"]).round(2)
    events["bad_order_month"] = events["bad_order_date"].dt.to_period("M").astype(str)
    events["routed_out_of_region"] = events["home_region"] != events["region"]

    n1 = len(events)
    qdf = pd.concat(quarantine, ignore_index=True) if quarantine else pd.DataFrame()

    events.to_csv(os.path.join(CLEAN, "repair_events_clean.csv"), index=False)
    if len(qdf):
        qdf.to_csv(os.path.join(CLEAN, "quarantine.csv"), index=False)
    pd.DataFrame(checks).to_csv(os.path.join(OUT, "data_quality_report.csv"), index=False)

    total_flagged = sum(c["rows_failed"] for c in checks)
    print(f"\n  rows in:            {n0:,}")
    print(f"  rows out:           {n1:,}  ({100*n1/n0:.1f}% retained)")
    print(f"  rows quarantined:   {len(qdf):,}")
    print(f"  total checks failed:{total_flagged:,} across {len(checks)} checks")
    print(f"  clean table:        data/clean/repair_events_clean.csv")


if __name__ == "__main__":
    main()
