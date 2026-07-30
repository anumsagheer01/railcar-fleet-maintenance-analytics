"""
STEP 3: Load into SQLite and build the reporting views
=====================================================

Loads the clean data into a real database so the analysis is done in SQL where
SQL belongs, then creates the six reporting views.

It also benchmarks one dashboard query with and without indexes. The job
description asks about improving "table structures to increase reporting
efficiency and query performance," and this is the smallest honest way to show
that work: measure, add the index, measure again.

SQLite is used so the whole project runs with no database server to install.
The SQL is standard enough to move to Azure SQL or Fabric with small edits.

Outputs:
  data/railpulse.db
  outputs/query_performance.csv

Run:  python src/03_build_database.py
"""

import os
import sqlite3
import time
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RAW = os.path.join(ROOT, "data", "raw")
CLEAN = os.path.join(ROOT, "data", "clean")
SQL = os.path.join(ROOT, "sql")
OUT = os.path.join(ROOT, "outputs")
DB = os.path.join(ROOT, "data", "railpulse.db")

FACT_COLUMNS = [
    "event_id", "car_id", "shop_id", "defect_code", "bad_order_date",
    "release_date", "bad_order_month", "dwell_days", "labor_hours",
    "labor_hours_imputed", "parts_cost_usd", "labor_cost_usd",
    "total_cost_usd", "car_age_years", "reported_by",
]

# The heaviest query the dashboard runs: monthly volume and cost for one shop,
# joined to two dimensions. Realistic shape for a shop manager's report page.
BENCH_QUERY = """
SELECT e.bad_order_month, c.car_type, COUNT(*) AS n, SUM(e.total_cost_usd) AS cost
FROM repair_events e
JOIN railcars c     ON c.car_id = e.car_id
JOIN defect_codes d ON d.defect_code = e.defect_code
WHERE e.shop_id = 'SH01' AND e.bad_order_month >= '2024-06'
GROUP BY 1, 2
ORDER BY 1, 2;
"""


def run_script(conn, filename):
    with open(os.path.join(SQL, filename)) as f:
        conn.executescript(f.read())
    print(f"   ran sql/{filename}")


def time_query(conn, query, runs=60):
    """Median of many runs. Median instead of mean so one slow run from an OS
    hiccup does not move the number."""
    for _ in range(5):
        conn.execute(query).fetchall()   # warm the page cache first
    times = []
    for _ in range(runs):
        t0 = time.perf_counter()
        conn.execute(query).fetchall()
        times.append((time.perf_counter() - t0) * 1000)
    times.sort()
    return times[len(times) // 2]        # milliseconds


def main():
    os.makedirs(OUT, exist_ok=True)
    if os.path.exists(DB):
        os.remove(DB)

    conn = sqlite3.connect(DB)
    print("STEP 3: building data/railpulse.db")

    # --- schema (includes the indexes) -----------------------------------
    run_script(conn, "01_schema.sql")

    # --- load dimensions ---------------------------------------------------
    pd.read_csv(os.path.join(RAW, "railcars.csv")).to_sql(
        "railcars", conn, if_exists="append", index=False)
    pd.read_csv(os.path.join(RAW, "shops.csv")).to_sql(
        "shops", conn, if_exists="append", index=False)
    pd.read_csv(os.path.join(RAW, "defect_codes.csv")).to_sql(
        "defect_codes", conn, if_exists="append", index=False)

    # --- load fact ---------------------------------------------------------
    events = pd.read_csv(os.path.join(CLEAN, "repair_events_clean.csv"))
    events["labor_hours_imputed"] = events["labor_hours_imputed"].astype(int)
    events["bad_order_date"] = pd.to_datetime(events["bad_order_date"]).dt.strftime("%Y-%m-%d")
    events["release_date"] = pd.to_datetime(events["release_date"]).dt.strftime("%Y-%m-%d")
    events[FACT_COLUMNS].to_sql("repair_events", conn, if_exists="append", index=False)

    counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
              for t in ["railcars", "shops", "defect_codes", "repair_events"]}
    print("   loaded:", ", ".join(f"{k}={v:,}" for k, v in counts.items()))

    # --- views -------------------------------------------------------------
    run_script(conn, "02_views.sql")

    # --- index benchmark ---------------------------------------------------
    # Drop the indexes, time the query, put them back, time it again.
    print("\n   index benchmark on the shop report query")
    index_sql = [r[0] for r in conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='index' AND sql IS NOT NULL"
    ).fetchall()]

    for name in ["idx_events_month", "idx_events_shop", "idx_events_car", "idx_events_defect"]:
        conn.execute(f"DROP INDEX IF EXISTS {name}")
    conn.execute("ANALYZE")
    before = time_query(conn, BENCH_QUERY)
    plan_before = conn.execute("EXPLAIN QUERY PLAN " + BENCH_QUERY).fetchall()

    for stmt in index_sql:
        conn.execute(stmt)
    conn.execute("ANALYZE")
    after = time_query(conn, BENCH_QUERY)
    plan_after = conn.execute("EXPLAIN QUERY PLAN " + BENCH_QUERY).fetchall()

    speedup = before / after if after else 0
    print(f"     without indexes: {before:7.2f} ms  (median of 60 runs)")
    print(f"     with indexes:    {after:7.2f} ms")
    print(f"     speedup:         {speedup:7.1f}x  ({100*(1-after/before):.0f}% faster)")
    print(f"     scan before: {plan_before[0][-1][:60]}")
    print(f"     scan after:  {plan_after[0][-1][:60]}")

    pd.DataFrame([{
        "query": "shop monthly volume and cost report",
        "rows_in_fact_table": counts["repair_events"],
        "avg_ms_without_indexes": round(before, 2),
        "avg_ms_with_indexes": round(after, 2),
        "speedup_x": round(speedup, 1),
        "pct_faster": round(100 * (1 - after / before), 1),
    }]).to_csv(os.path.join(OUT, "query_performance.csv"), index=False)

    # --- smoke test the views ---------------------------------------------
    print("\n   view row counts")
    for v in ["v_monthly_demand", "v_fleet_health_by_type", "v_shop_scorecard",
              "v_defect_pareto", "v_age_band_reliability", "v_repeat_offenders"]:
        n = conn.execute(f"SELECT COUNT(*) FROM {v}").fetchone()[0]
        print(f"     {v:<26} {n:>6,} rows")

    conn.commit()
    conn.close()
    print(f"\n   database ready: data/railpulse.db")


if __name__ == "__main__":
    main()
