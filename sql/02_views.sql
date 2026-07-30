-- ============================================================
-- RailPulse reporting views
-- ============================================================
-- These are the "self-service data store" layer. The idea is that a planner
-- who knows some SQL but does not want to re-derive bad order rate every time
-- can query these directly, and every report in the project agrees on the
-- same definitions.
--
-- Definitions used everywhere:
--   bad order         a railcar pulled from service for repair
--   dwell days        release_date minus bad_order_date
--   bad order rate    bad orders per car per year, not percent of fleet
--   availability      1 minus (car days in shop / total car days)
-- ============================================================

DROP VIEW IF EXISTS v_monthly_demand;
DROP VIEW IF EXISTS v_fleet_health_by_type;
DROP VIEW IF EXISTS v_shop_scorecard;
DROP VIEW IF EXISTS v_defect_pareto;
DROP VIEW IF EXISTS v_age_band_reliability;
DROP VIEW IF EXISTS v_repeat_offenders;

-- ------------------------------------------------------------
-- 1. Monthly repair demand by car type and repair class.
--    This is the table the forecast model trains on.
-- ------------------------------------------------------------
CREATE VIEW v_monthly_demand AS
SELECT
    e.bad_order_month                        AS month,
    c.car_type                               AS car_type,
    d.repair_class                           AS repair_class,
    COUNT(*)                                 AS bad_orders,
    ROUND(SUM(e.labor_hours), 1)             AS labor_hours,
    ROUND(AVG(e.dwell_days), 2)              AS avg_dwell_days,
    ROUND(SUM(e.total_cost_usd), 2)          AS total_cost_usd
FROM repair_events e
JOIN railcars     c ON c.car_id = e.car_id
JOIN defect_codes d ON d.defect_code = e.defect_code
GROUP BY 1, 2, 3;

-- ------------------------------------------------------------
-- 2. Fleet health by car type.
--    Denominator is fleet size times years of history, so the rate is
--    comparable across types with different fleet counts.
-- ------------------------------------------------------------
CREATE VIEW v_fleet_health_by_type AS
WITH fleet AS (
    SELECT car_type, COUNT(*) AS fleet_size
    FROM railcars
    GROUP BY car_type
),
window_years AS (
    SELECT (JULIANDAY(MAX(bad_order_date)) - JULIANDAY(MIN(bad_order_date))) / 365.25 AS yrs
    FROM repair_events
),
activity AS (
    SELECT
        c.car_type,
        COUNT(*)                    AS bad_orders,
        SUM(e.dwell_days)           AS car_days_out,
        SUM(e.total_cost_usd)       AS total_cost_usd,
        AVG(e.dwell_days)           AS avg_dwell_days
    FROM repair_events e
    JOIN railcars c ON c.car_id = e.car_id
    GROUP BY c.car_type
)
SELECT
    f.car_type,
    f.fleet_size,
    a.bad_orders,
    ROUND(a.bad_orders * 1.0 / (f.fleet_size * w.yrs), 3)          AS bad_orders_per_car_year,
    ROUND(a.avg_dwell_days, 2)                                     AS avg_dwell_days,
    ROUND(100.0 * (1 - a.car_days_out * 1.0
          / (f.fleet_size * w.yrs * 365.25)), 2)                   AS availability_pct,
    ROUND(a.total_cost_usd, 0)                                     AS total_cost_usd,
    ROUND(a.total_cost_usd / a.bad_orders, 2)                      AS avg_cost_per_bad_order
FROM fleet f
JOIN activity a ON a.car_type = f.car_type
CROSS JOIN window_years w
ORDER BY bad_orders_per_car_year DESC;

-- ------------------------------------------------------------
-- 3. Shop scorecard.
--    Utilization compares car days actually handled against the shop's
--    stated daily capacity over the same window.
-- ------------------------------------------------------------
CREATE VIEW v_shop_scorecard AS
WITH window_days AS (
    SELECT JULIANDAY(MAX(bad_order_date)) - JULIANDAY(MIN(bad_order_date)) AS days
    FROM repair_events
)
SELECT
    s.shop_id,
    s.shop_name,
    s.region,
    s.primary_specialty,
    s.daily_capacity_cars,
    COUNT(e.event_id)                                   AS bad_orders,
    ROUND(AVG(e.dwell_days), 2)                         AS avg_dwell_days,
    ROUND(SUM(e.labor_hours), 0)                        AS labor_hours,
    ROUND(AVG(e.total_cost_usd), 2)                     AS avg_cost_per_repair,
    ROUND(100.0 * COUNT(e.event_id)
          / (s.daily_capacity_cars * w.days), 1)        AS capacity_used_pct
FROM shops s
LEFT JOIN repair_events e ON e.shop_id = s.shop_id
CROSS JOIN window_days w
GROUP BY s.shop_id
ORDER BY bad_orders DESC;

-- ------------------------------------------------------------
-- 4. Defect Pareto. Which defects drive the volume and the money.
-- ------------------------------------------------------------
CREATE VIEW v_defect_pareto AS
WITH totals AS (
    SELECT COUNT(*) AS n, SUM(total_cost_usd) AS c FROM repair_events
)
SELECT
    d.defect_code,
    d.defect_description,
    d.repair_class,
    COUNT(*)                                            AS bad_orders,
    ROUND(100.0 * COUNT(*) / t.n, 2)                    AS pct_of_bad_orders,
    ROUND(SUM(e.total_cost_usd), 0)                     AS total_cost_usd,
    ROUND(100.0 * SUM(e.total_cost_usd) / t.c, 2)       AS pct_of_cost,
    ROUND(AVG(e.labor_hours), 2)                        AS avg_labor_hours
FROM repair_events e
JOIN defect_codes d ON d.defect_code = e.defect_code
CROSS JOIN totals t
GROUP BY d.defect_code
ORDER BY bad_orders DESC;

-- ------------------------------------------------------------
-- 5. Reliability by age band. Supports fleet renewal conversations.
-- ------------------------------------------------------------
CREATE VIEW v_age_band_reliability AS
WITH banded AS (
    SELECT
        CASE
            WHEN 2025 - build_year < 10 THEN '00-09 yrs'
            WHEN 2025 - build_year < 20 THEN '10-19 yrs'
            WHEN 2025 - build_year < 30 THEN '20-29 yrs'
            WHEN 2025 - build_year < 40 THEN '30-39 yrs'
            ELSE '40+ yrs'
        END AS age_band,
        car_id
    FROM railcars
),
fleet AS (
    SELECT age_band, COUNT(*) AS fleet_size FROM banded GROUP BY age_band
),
acts AS (
    SELECT b.age_band, COUNT(*) AS bad_orders, AVG(e.total_cost_usd) AS avg_cost
    FROM repair_events e
    JOIN banded b ON b.car_id = e.car_id
    GROUP BY b.age_band
)
SELECT
    f.age_band,
    f.fleet_size,
    a.bad_orders,
    ROUND(a.bad_orders * 1.0 / (f.fleet_size * 3.0), 3) AS bad_orders_per_car_year,
    ROUND(a.avg_cost, 2)                               AS avg_cost_per_bad_order
FROM fleet f JOIN acts a ON a.age_band = f.age_band
ORDER BY f.age_band;

-- ------------------------------------------------------------
-- 6. Repeat offenders. Cars worth pulling for a full inspection
--    instead of patching again.
-- ------------------------------------------------------------
CREATE VIEW v_repeat_offenders AS
SELECT
    e.car_id,
    c.car_type,
    c.build_year,
    2025 - c.build_year                     AS car_age_years,
    COUNT(*)                                AS bad_orders_3yr,
    SUM(e.dwell_days)                       AS total_days_out,
    ROUND(SUM(e.total_cost_usd), 0)         AS total_cost_usd
FROM repair_events e
JOIN railcars c ON c.car_id = e.car_id
GROUP BY e.car_id
HAVING COUNT(*) >= 6
ORDER BY bad_orders_3yr DESC, total_cost_usd DESC;
