-- ============================================================
-- RailPulse ad hoc reporting queries
-- ============================================================
-- The questions that come up often enough to keep the SQL around, but not often
-- enough to build a view for. Run them against data/railpulse.db:
--
--     sqlite3 data/railpulse.db
--     .mode column
--     .headers on
--     .read sql/03_reporting_queries.sql
--
-- Or paste one at a time. Each is independent.
-- ============================================================


-- ------------------------------------------------------------
-- Q1. Bad orders and cost by month, last 12 months.
--     The default "how are we doing" query.
-- ------------------------------------------------------------
SELECT
    bad_order_month                          AS month,
    COUNT(*)                                 AS bad_orders,
    ROUND(SUM(labor_hours), 0)               AS labor_hours,
    ROUND(SUM(total_cost_usd), 0)            AS total_cost,
    ROUND(AVG(dwell_days), 2)                AS avg_dwell_days
FROM repair_events
WHERE bad_order_month >= '2025-01'
GROUP BY 1
ORDER BY 1;


-- ------------------------------------------------------------
-- Q2. Which shops are slow on which repair classes.
--     Compares each shop against the network for the same class, which is the
--     only fair way to do it. Raw dwell punishes heavy repair shops.
-- ------------------------------------------------------------
WITH class_avg AS (
    SELECT d.repair_class, AVG(e.dwell_days) AS net_dwell
    FROM repair_events e
    JOIN defect_codes d ON d.defect_code = e.defect_code
    GROUP BY 1
)
SELECT
    s.shop_name,
    d.repair_class,
    COUNT(*)                                        AS bad_orders,
    ROUND(AVG(e.dwell_days), 2)                     AS shop_dwell,
    ROUND(ca.net_dwell, 2)                          AS network_dwell,
    ROUND(AVG(e.dwell_days) / ca.net_dwell, 2)      AS ratio
FROM repair_events e
JOIN shops s        ON s.shop_id = e.shop_id
JOIN defect_codes d ON d.defect_code = e.defect_code
JOIN class_avg ca   ON ca.repair_class = d.repair_class
GROUP BY s.shop_id, d.repair_class
HAVING COUNT(*) >= 50
ORDER BY ratio DESC
LIMIT 15;


-- ------------------------------------------------------------
-- Q3. Cost per car per year by car type and age band.
--     Feeds the repair-or-retire conversation.
-- ------------------------------------------------------------
WITH banded AS (
    SELECT
        car_id, car_type,
        CASE
            WHEN 2025 - build_year < 10 THEN '00-09'
            WHEN 2025 - build_year < 20 THEN '10-19'
            WHEN 2025 - build_year < 30 THEN '20-29'
            WHEN 2025 - build_year < 40 THEN '30-39'
            ELSE '40+'
        END AS age_band
    FROM railcars
),
fleet AS (
    SELECT car_type, age_band, COUNT(*) AS fleet_size FROM banded GROUP BY 1, 2
)
SELECT
    f.car_type,
    f.age_band,
    f.fleet_size,
    COUNT(e.event_id)                                              AS bad_orders,
    ROUND(SUM(e.total_cost_usd) / (f.fleet_size * 3.0), 0)         AS cost_per_car_year,
    ROUND(COUNT(e.event_id) * 1.0 / (f.fleet_size * 3.0), 3)       AS bad_orders_per_car_year
FROM fleet f
JOIN banded b     ON b.car_type = f.car_type AND b.age_band = f.age_band
LEFT JOIN repair_events e ON e.car_id = b.car_id
GROUP BY f.car_type, f.age_band
HAVING f.fleet_size >= 50
ORDER BY cost_per_car_year DESC
LIMIT 20;


-- ------------------------------------------------------------
-- Q4. Repeat offenders worth pulling for full inspection.
--     Cars with 6 or more bad orders, ranked by days out of service.
-- ------------------------------------------------------------
SELECT
    e.car_id,
    c.car_type,
    2025 - c.build_year                     AS age_years,
    COUNT(*)                                AS bad_orders_3yr,
    SUM(e.dwell_days)                       AS days_out_of_service,
    ROUND(SUM(e.total_cost_usd), 0)         AS total_cost,
    GROUP_CONCAT(DISTINCT e.defect_code)    AS defect_codes
FROM repair_events e
JOIN railcars c ON c.car_id = e.car_id
GROUP BY e.car_id
HAVING COUNT(*) >= 6
ORDER BY days_out_of_service DESC
LIMIT 20;


-- ------------------------------------------------------------
-- Q5. Seasonality check by defect code.
--     Confirms winter volume is wheels and brakes rather than everything
--     rising together. Matters because it tells you what to stock.
-- ------------------------------------------------------------
WITH monthly AS (
    SELECT
        defect_code,
        CAST(SUBSTR(bad_order_month, 6, 2) AS INTEGER) AS mo,
        COUNT(*)                                       AS n
    FROM repair_events
    GROUP BY 1, 2
),
avg_per_code AS (
    SELECT defect_code, AVG(n) AS avg_n FROM monthly GROUP BY 1
)
SELECT
    d.defect_code,
    d.defect_description,
    ROUND(AVG(CASE WHEN m.mo IN (12, 1, 2) THEN m.n END) / a.avg_n, 2) AS winter_index,
    ROUND(AVG(CASE WHEN m.mo IN (6, 7, 8)  THEN m.n END) / a.avg_n, 2) AS summer_index
FROM monthly m
JOIN avg_per_code a  ON a.defect_code = m.defect_code
JOIN defect_codes d  ON d.defect_code = m.defect_code
GROUP BY d.defect_code
ORDER BY winter_index DESC;


-- ------------------------------------------------------------
-- Q6. How much repair work leaves its home region, and does it cost more.
--     This is the historical baseline the optimizer is measured against.
-- ------------------------------------------------------------
SELECT
    CASE WHEN c.home_region = s.region THEN 'in region' ELSE 'out of region' END AS routing,
    COUNT(*)                                        AS bad_orders,
    ROUND(100.0 * COUNT(*) / (SELECT COUNT(*) FROM repair_events), 1) AS pct_of_total,
    ROUND(AVG(e.dwell_days), 2)                     AS avg_dwell_days,
    ROUND(AVG(e.total_cost_usd), 2)                 AS avg_cost
FROM repair_events e
JOIN railcars c ON c.car_id = e.car_id
JOIN shops s    ON s.shop_id = e.shop_id
GROUP BY 1;


-- ------------------------------------------------------------
-- Q7. Imputation audit.
--     How many rows on this report had labor hours filled in by step 2. Any
--     number here above a few percent means the cost figures are softer than
--     they look and somebody should chase the shops for closeouts.
-- ------------------------------------------------------------
SELECT
    bad_order_month                                              AS month,
    COUNT(*)                                                     AS bad_orders,
    SUM(labor_hours_imputed)                                     AS imputed_rows,
    ROUND(100.0 * SUM(labor_hours_imputed) / COUNT(*), 2)        AS pct_imputed
FROM repair_events
GROUP BY 1
ORDER BY pct_imputed DESC
LIMIT 12;
