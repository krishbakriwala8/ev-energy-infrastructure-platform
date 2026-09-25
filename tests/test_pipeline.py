"""
Smoke test: runs the ENTIRE pipeline (generate data -> load -> KPIs -> ML)
against a throwaway SQLite database, so you can verify everything works in
under a minute, with zero internet and without needing Postgres running.

    python tests/test_pipeline.py

Note: SQLite is only used here for a fast local check. The real project
targets PostgreSQL (see db/schema.sql) — SQLite doesn't enforce foreign
keys or the exact column types, but exercises every code path.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TEST_DB = ROOT / "tests" / "_smoke_test.db"
if TEST_DB.exists():
    TEST_DB.unlink()
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB}"

from sqlalchemy import create_engine, text  # noqa: E402

engine = create_engine(os.environ["DATABASE_URL"])


def create_sqlite_schema():
    """SQLite-compatible subset of db/schema.sql (no SERIAL/foreign key syntax)."""
    ddl = """
    CREATE TABLE states (state_code TEXT PRIMARY KEY, state_name TEXT);
    CREATE TABLE charging_stations (
        station_id INTEGER PRIMARY KEY AUTOINCREMENT, operator TEXT, street TEXT, city TEXT,
        postal_code TEXT, state_code TEXT, latitude REAL, longitude REAL,
        num_charging_points INTEGER, power_kw REAL, charge_type TEXT, is_fast_charger INTEGER,
        commissioning_date TEXT, source_snapshot_date TEXT);
    CREATE TABLE electricity_timeseries (
        ts_id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, state_code TEXT,
        load_mw REAL, solar_mw REAL, wind_onshore_mw REAL, wind_offshore_mw REAL);
    CREATE TABLE regional_stats (
        state_code TEXT, year INTEGER, population INTEGER, gdp_per_capita_eur REAL,
        registered_evs INTEGER, area_km2 REAL);
    CREATE TABLE clusters (
        cluster_run_id INTEGER PRIMARY KEY AUTOINCREMENT, run_date TEXT, algorithm TEXT,
        state_code TEXT, cluster_label INTEGER, centroid_lat REAL, centroid_lon REAL,
        station_count INTEGER, is_coverage_gap INTEGER);
    CREATE TABLE forecasts (
        forecast_id INTEGER PRIMARY KEY AUTOINCREMENT, run_date TEXT, target_timestamp TEXT,
        model TEXT, predicted_load_mw REAL, actual_load_mw REAL, mae REAL, rmse REAL);
    CREATE TABLE need_scores (
        state_code TEXT, run_date TEXT, population_score REAL, availability_score REAL,
        capacity_score REAL, electricity_score REAL, growth_score REAL, need_score REAL, rank INTEGER);
    """
    with engine.begin() as conn:
        for stmt in ddl.strip().split(";"):
            if stmt.strip():
                conn.execute(text(stmt))


def step(name, fn):
    print(f"\n{'='*60}\n{name}\n{'='*60}")
    fn()
    print(f"[OK] {name}")


def test_generate_sample_data():
    from etl import generate_sample_data as g
    states_df = g.generate_states_csv()
    g.generate_charging_stations(states_df)
    g.generate_electricity_timeseries(days=14)  # shorter window for a fast smoke test
    g.generate_regional_stats(states_df)


def test_load_to_postgres():
    os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB}"
    from etl import load_to_postgres as l
    l.load_states(engine)
    l.load_charging_stations(engine)
    l.load_electricity_timeseries(engine)
    l.load_regional_stats(engine)


def test_kpis():
    from analytics import kpis
    for name, fn in kpis.ALL_KPIS.items():
        df = fn(engine)
        assert df is not None
        print(f"  {name}: {len(df)} rows")


def test_clustering():
    from ml import clustering
    out = clustering.run_clustering(engine)
    assert out is not None and len(out) > 0


def test_forecast():
    from ml import load_forecast
    load_forecast.train_and_forecast(engine)


def test_scoring():
    from ml import scoring
    out = scoring.compute_need_scores(engine)
    assert out is not None and len(out) == 16


if __name__ == "__main__":
    create_sqlite_schema()
    step("1/6 Generate sample data", test_generate_sample_data)
    step("2/6 Load into DB", test_load_to_postgres)
    step("3/6 Compute KPIs", test_kpis)
    step("4/6 Run clustering", test_clustering)
    step("5/6 Run load forecast", test_forecast)
    step("6/6 Compute Need Score", test_scoring)
    print("\nALL SMOKE TESTS PASSED — the pipeline runs end-to-end without error.")
    print("(The GenAI agent step needs a live GROQ_API_KEY so it isn't included here — "
          "test it separately with: python agents/llm_agent.py \"your question\")")
