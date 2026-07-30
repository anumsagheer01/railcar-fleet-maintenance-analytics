-- ============================================================
-- RailPulse schema
-- ============================================================
-- Three dimension tables and one fact table. Small enough to read in one
-- sitting, shaped the way an operational reporting mart usually is.
--
-- The fact grain is one row per bad order event: one railcar, pulled from
-- service on one date, for one defect, repaired at one shop.
-- ============================================================

DROP TABLE IF EXISTS repair_events;
DROP TABLE IF EXISTS railcars;
DROP TABLE IF EXISTS shops;
DROP TABLE IF EXISTS defect_codes;

-- ---------- dimensions ----------

CREATE TABLE railcars (
    car_id          TEXT PRIMARY KEY,
    car_type        TEXT NOT NULL,
    build_year      INTEGER NOT NULL,
    capacity_tons   INTEGER,
    home_region     TEXT NOT NULL
);

CREATE TABLE shops (
    shop_id             TEXT PRIMARY KEY,
    shop_name           TEXT NOT NULL,
    city                TEXT,
    state               TEXT,
    region              TEXT NOT NULL,
    daily_capacity_cars INTEGER NOT NULL,
    labor_rate_usd      REAL NOT NULL,
    primary_specialty   TEXT
);

CREATE TABLE defect_codes (
    defect_code          TEXT PRIMARY KEY,
    defect_description   TEXT NOT NULL,
    repair_class         TEXT NOT NULL,
    occurrence_share     REAL,
    mean_labor_hours     REAL,
    mean_parts_cost_usd  REAL
);

-- ---------- fact ----------

CREATE TABLE repair_events (
    event_id             TEXT PRIMARY KEY,
    car_id               TEXT NOT NULL,
    shop_id              TEXT NOT NULL,
    defect_code          TEXT NOT NULL,
    bad_order_date       TEXT NOT NULL,   -- ISO date, stored as TEXT in SQLite
    release_date         TEXT NOT NULL,
    bad_order_month      TEXT NOT NULL,   -- YYYY-MM, pre-computed for grouping
    dwell_days           INTEGER NOT NULL,
    labor_hours          REAL NOT NULL,
    labor_hours_imputed  INTEGER NOT NULL DEFAULT 0,
    parts_cost_usd       REAL NOT NULL,
    labor_cost_usd       REAL NOT NULL,
    total_cost_usd       REAL NOT NULL,
    car_age_years        INTEGER,
    reported_by          TEXT,
    FOREIGN KEY (car_id)      REFERENCES railcars(car_id),
    FOREIGN KEY (shop_id)     REFERENCES shops(shop_id),
    FOREIGN KEY (defect_code) REFERENCES defect_codes(defect_code)
);

-- ---------- indexes ----------
-- Chosen from how the reports actually query the table, not by indexing
-- everything. Step 3 times a real dashboard query with and without these.
--
--   idx_events_month     every dashboard tile groups by month
--   idx_events_shop      shop scorecard filters by shop then month
--   idx_events_car       repeat offender lookups filter by car
--   idx_events_defect    Pareto chart groups by defect

CREATE INDEX idx_events_month  ON repair_events(bad_order_month);
CREATE INDEX idx_events_shop   ON repair_events(shop_id, bad_order_month);
CREATE INDEX idx_events_car    ON repair_events(car_id);
CREATE INDEX idx_events_defect ON repair_events(defect_code);
