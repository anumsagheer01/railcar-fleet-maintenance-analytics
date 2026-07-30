# Data Dictionary

Every table, column, and metric definition in RailPulse. If two reports ever disagree about a number, the answer is in here.

---

## Domain terms

Rail maintenance has its own vocabulary. Four terms carry most of the weight:

| Term | Meaning |
|---|---|
| **Bad order** | A railcar pulled out of service because something is wrong with it. The core event this whole project counts. A car is "bad ordered" on the day the defect is found and "released" when the repair is done. |
| **Dwell** | Days between bad order and release. The car is earning nothing during this window, which is why it is the metric shop managers get asked about. |
| **Repair class** | How the work gets scheduled. `RUNNING` is quick and unplanned, `PROGRAM` is planned maintenance, `HEAVY` is major structural work that waits on parts. |
| **Deadhead** | Moving an empty car to get it somewhere, in this case to a repair shop. Costs money and earns nothing, so distance to shop is a real constraint. |

---

## Tables

### `railcars` (dimension, 12,000 rows)

One row per car in the fleet.

| Column | Type | Description |
|---|---|---|
| `car_id` | TEXT, PK | Reporting mark and number, e.g. `TTX104217` |
| `car_type` | TEXT | `INTERMODAL_WELL`, `FLATCAR`, `BOXCAR`, `GONDOLA`, `AUTORACK` |
| `build_year` | INTEGER | Year built, 1975 to 2024 |
| `capacity_tons` | INTEGER | Rated load capacity |
| `home_region` | TEXT | `MIDWEST`, `SOUTHEAST`, `NORTHEAST`, `SOUTHWEST`, `WEST`. Where the car normally works, which sets the deadhead distance to each shop. |

### `shops` (dimension, 10 rows)

One row per repair shop.

| Column | Type | Description |
|---|---|---|
| `shop_id` | TEXT, PK | `SH01` through `SH10` |
| `shop_name` | TEXT | Location name |
| `city`, `state` | TEXT | Physical location |
| `region` | TEXT | Which demand region the shop sits in |
| `daily_capacity_cars` | INTEGER | Cars the shop can start per day. Multiply by days in month for monthly capacity. |
| `labor_rate_usd` | REAL | Fully loaded labor cost per hour, $68 to $95 |
| `primary_specialty` | TEXT | `RUNNING`, `PROGRAM`, or `HEAVY`. Drives the specialty penalty in the optimizer. |

Note: shop turnaround speed is deliberately **not** a column here. It is a behavior you have to measure from the repair history, which is what step 4 does.

### `defect_codes` (dimension, 14 rows)

AAR-style job codes describing why a car was bad ordered.

| Column | Type | Description |
|---|---|---|
| `defect_code` | TEXT, PK | e.g. `WH-101` |
| `defect_description` | TEXT | Plain English, e.g. "Wheel set thin flange" |
| `repair_class` | TEXT | `RUNNING`, `PROGRAM`, or `HEAVY` |
| `occurrence_share` | REAL | Baseline share of all bad orders |
| `mean_labor_hours` | REAL | Typical hands-on hours |
| `mean_parts_cost_usd` | REAL | Typical parts cost |

### `repair_events` (fact, 28,822 rows)

**Grain: one row per bad order event.** One car, pulled on one date, for one defect, repaired at one shop.

| Column | Type | Description |
|---|---|---|
| `event_id` | TEXT, PK | Unique event key |
| `car_id` | TEXT, FK | Joins to `railcars` |
| `shop_id` | TEXT, FK | Joins to `shops` |
| `defect_code` | TEXT, FK | Joins to `defect_codes` |
| `bad_order_date` | TEXT | ISO date the car was pulled |
| `release_date` | TEXT | ISO date the repair finished |
| `bad_order_month` | TEXT | `YYYY-MM`, pre-computed because every report groups by it |
| `dwell_days` | INTEGER | `release_date` minus `bad_order_date` |
| `labor_hours` | REAL | Hours worked, capped at 240 by the quality gate |
| `labor_hours_imputed` | INTEGER | 1 if the value was filled in by step 2, 0 if reported. **Check this before trusting a cost figure.** |
| `parts_cost_usd` | REAL | Parts consumed |
| `labor_cost_usd` | REAL | `labor_hours` × the shop's `labor_rate_usd` |
| `total_cost_usd` | REAL | `labor_cost_usd` + `parts_cost_usd` |
| `car_age_years` | INTEGER | Age at time of repair |
| `reported_by` | TEXT | `INSPECTOR`, `CARRIER`, `SHOP`, or `AUTOMATED` |

`bad_order_month` is stored rather than derived on the fly. It duplicates information already in `bad_order_date`, which is normally bad practice, and it is worth it here because every single report groups by month and an indexed TEXT column beats a date function on every row.

---

## Metric definitions

These are the ones that cause arguments, so they are defined once in `sql/02_views.sql` and read from there by everything else.

### Bad order rate

```
bad orders per car per year  =  bad orders  /  (fleet size × years of history)
```

**Not** percent of fleet in bad order status, which is the other common definition and means something different. This version compares across fleets of different sizes, which is the whole point when boxcars number 2,640 and autoracks 720.

### Availability

```
availability %  =  100 × (1  -  car days in shop / (fleet size × 365.25 × years))
```

Sums `dwell_days` across all events and divides by total car days available. A car sitting in a shop is unavailable whether or not anyone is working on it, which is why this uses dwell and not labor hours.

### Mix adjusted dwell ratio

The one that took thought. Raw average dwell makes heavy repair shops look bad because frame work takes longer everywhere. So:

```
for each shop and repair class:
    ratio  =  shop's avg dwell for that class  /  network avg dwell for that class

mix adjusted ratio  =  average of that shop's ratios across classes
```

1.00 means average. Above 1.00 means slow **for the work it actually does**. What is left after the adjustment is the part of dwell the shop controls.

### Cost to volume ratio

```
cost to volume ratio  =  share of repair dollars  /  share of bad orders
```

Above 1.0 means the defect costs more than its frequency suggests. Cracked sills score 4.6x, which is why a report ranked by volume alone would bury them near the bottom of the page.

### Specialty penalty

Multiplier on labor hours when a shop works outside its specialty. A running repair shop can do a heavy frame job, it just takes longer.

| Shop specialty ↓ / Repair class → | RUNNING | PROGRAM | HEAVY |
|---|---|---|---|
| RUNNING | 1.00 | 1.10 | 1.25 |
| PROGRAM | 1.08 | 1.00 | 1.15 |
| HEAVY | 1.30 | 1.12 | 1.00 |

Heavy shops are worst at running repairs (1.30) because their setup is built for major work. This is a modeling assumption, not measured from data, and it is the input I would most want to validate against real shop records.

---

## Views

All in `sql/02_views.sql`.

| View | Grain | Used by |
|---|---|---|
| `v_monthly_demand` | month × car type × repair class | Forecast training data, optimizer demand mix |
| `v_fleet_health_by_type` | car type | Dashboard KPIs, fleet renewal analysis |
| `v_shop_scorecard` | shop | Shop performance review |
| `v_defect_pareto` | defect code | Which defects to attack first |
| `v_age_band_reliability` | 10-year age band | Repair or retire decisions |
| `v_repeat_offenders` | car, filtered to 6+ events | Inspection candidate list |

---

## Generated files

| File | Contents |
|---|---|
| `data/raw/*.csv` | Output of step 1, dirty on purpose |
| `data/clean/repair_events_clean.csv` | Rows that passed the quality gate |
| `data/clean/quarantine.csv` | Rows pulled out, with a `quarantine_reason` column |
| `data/railpulse.db` | SQLite database, query it directly |
| `outputs/data_quality_report.csv` | One row per check: severity, rows failed, action taken |
| `outputs/query_performance.csv` | Index benchmark, before and after |
| `outputs/key_findings.csv` | The findings step 4 wrote, in plain sentences |
| `outputs/forecast_model_comparison.csv` | All six models with holdout scores |
| `outputs/extrapolation_test.csv` | Gradient boosting vs linear, projected forward 12 months |
| `outputs/forecast_next_6_months.csv` | The shipped forecast with intervals |
| `outputs/forecast_by_car_type.csv` | Same, split by car type, with per-segment error |
| `outputs/optimizer_assignment_plan.csv` | The actual plan: which cars go where |
| `outputs/optimizer_utilization.csv` | Shop loading, baseline vs optimized |
| `outputs/optimizer_summary.csv` | Costs, savings, scenario result |
| `outputs/dashboard.html` | Everything above, assembled |
