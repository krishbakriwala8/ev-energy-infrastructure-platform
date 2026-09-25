-- German Energy & EV Infrastructure Intelligence Platform
-- PostgreSQL schema

DROP TABLE IF EXISTS need_scores CASCADE;
DROP TABLE IF EXISTS forecasts CASCADE;
DROP TABLE IF EXISTS clusters CASCADE;
DROP TABLE IF EXISTS charging_stations CASCADE;
DROP TABLE IF EXISTS electricity_timeseries CASCADE;
DROP TABLE IF EXISTS regional_stats CASCADE;
DROP TABLE IF EXISTS states CASCADE;

-- 16 German federal states (Bundesländer)
CREATE TABLE states (
    state_code   VARCHAR(2) PRIMARY KEY,      -- e.g. 'BY', 'BB'
    state_name   VARCHAR(50) NOT NULL          -- e.g. 'Bavaria', 'Brandenburg'
);

-- Bundesnetzagentur Ladesäulenregister (charging station register)
CREATE TABLE charging_stations (
    station_id       SERIAL PRIMARY KEY,
    operator         VARCHAR(200),
    street           VARCHAR(200),
    city             VARCHAR(100),
    postal_code      VARCHAR(10),
    state_code       VARCHAR(2) REFERENCES states(state_code),
    latitude         DOUBLE PRECISION,
    longitude        DOUBLE PRECISION,
    num_charging_points INTEGER,
    power_kw          DOUBLE PRECISION,          -- rated power per charging point
    charge_type       VARCHAR(20),                -- 'AC' or 'DC'
    is_fast_charger   BOOLEAN,                     -- power_kw >= 43 kW convention
    commissioning_date DATE,
    source_snapshot_date DATE NOT NULL             -- which monthly BNetzA export this row is from
);

CREATE INDEX idx_stations_state ON charging_stations(state_code);
CREATE INDEX idx_stations_snapshot ON charging_stations(source_snapshot_date);
CREATE INDEX idx_stations_geo ON charging_stations(latitude, longitude);

-- Open Power System Data: national/regional electricity time series
CREATE TABLE electricity_timeseries (
    ts_id            SERIAL PRIMARY KEY,
    timestamp        TIMESTAMP NOT NULL,
    state_code       VARCHAR(2) REFERENCES states(state_code), -- NULL = national aggregate
    load_mw          DOUBLE PRECISION,
    solar_mw         DOUBLE PRECISION,
    wind_onshore_mw  DOUBLE PRECISION,
    wind_offshore_mw DOUBLE PRECISION,
    UNIQUE(timestamp, state_code)
);

CREATE INDEX idx_elec_ts ON electricity_timeseries(timestamp);
CREATE INDEX idx_elec_state ON electricity_timeseries(state_code);

-- Destatis regional statistics (population, economy)
CREATE TABLE regional_stats (
    state_code        VARCHAR(2) REFERENCES states(state_code),
    year              INTEGER,
    population        BIGINT,
    gdp_per_capita_eur DOUBLE PRECISION,
    registered_evs    INTEGER,             -- registered battery-electric vehicles
    area_km2          DOUBLE PRECISION,
    PRIMARY KEY (state_code, year)
);

-- Derived: clustering results (coverage-gap analysis)
CREATE TABLE clusters (
    cluster_run_id   SERIAL PRIMARY KEY,
    run_date         DATE NOT NULL,
    algorithm        VARCHAR(20),           -- 'DBSCAN' or 'KMEANS'
    state_code       VARCHAR(2),
    cluster_label    INTEGER,               -- -1 = DBSCAN noise/gap point
    centroid_lat     DOUBLE PRECISION,
    centroid_lon     DOUBLE PRECISION,
    station_count     INTEGER,
    is_coverage_gap   BOOLEAN
);

-- Derived: load forecasts
CREATE TABLE forecasts (
    forecast_id      SERIAL PRIMARY KEY,
    run_date         DATE NOT NULL,
    target_timestamp TIMESTAMP NOT NULL,
    model            VARCHAR(20),           -- 'xgboost' | 'lightgbm'
    predicted_load_mw DOUBLE PRECISION,
    actual_load_mw    DOUBLE PRECISION,      -- filled in once known, for MAE/RMSE tracking
    mae               DOUBLE PRECISION,
    rmse              DOUBLE PRECISION
);

-- Derived: EV Infrastructure Need Score per state
CREATE TABLE need_scores (
    state_code        VARCHAR(2) REFERENCES states(state_code),
    run_date          DATE NOT NULL,
    population_score       DOUBLE PRECISION,
    availability_score     DOUBLE PRECISION,
    capacity_score         DOUBLE PRECISION,
    electricity_score      DOUBLE PRECISION,
    growth_score            DOUBLE PRECISION,
    need_score               DOUBLE PRECISION,   -- weighted composite, 0-100
    rank                      INTEGER,
    PRIMARY KEY (state_code, run_date)
);
