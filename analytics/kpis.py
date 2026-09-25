"""
Computes the 8 requested analytics views directly from PostgreSQL with SQL,
returning pandas DataFrames the dashboard/agent can render as tables/charts.

Run standalone to print all KPIs to stdout as a sanity check:
    python analytics/kpis.py
"""
import os
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./ev_energy_local.db")


def get_engine():
    return create_engine(DATABASE_URL)


def stations_per_state(engine) -> pd.DataFrame:
    q = """
    SELECT s.state_name, cs.state_code, COUNT(*) AS station_count,
           SUM(cs.num_charging_points) AS charging_points
    FROM charging_stations cs JOIN states s ON s.state_code = cs.state_code
    GROUP BY s.state_name, cs.state_code
    ORDER BY station_count DESC
    """
    return pd.read_sql(text(q), engine)


def chargers_per_100k(engine) -> pd.DataFrame:
    q = """
    SELECT s.state_name, cs.state_code,
           SUM(cs.num_charging_points) AS charging_points,
           MAX(rs.population) AS population,
           ROUND(SUM(cs.num_charging_points) * 100000.0 / NULLIF(MAX(rs.population), 0), 2) AS points_per_100k
    FROM charging_stations cs
    JOIN states s ON s.state_code = cs.state_code
    JOIN regional_stats rs ON rs.state_code = cs.state_code AND rs.year = (SELECT MAX(year) FROM regional_stats)
    GROUP BY s.state_name, cs.state_code
    ORDER BY points_per_100k DESC
    """
    return pd.read_sql(text(q), engine)


def fast_vs_slow(engine) -> pd.DataFrame:
    q = """
    SELECT s.state_name, cs.state_code,
           SUM(CASE WHEN cs.is_fast_charger THEN cs.num_charging_points ELSE 0 END) AS fast_points,
           SUM(CASE WHEN NOT cs.is_fast_charger THEN cs.num_charging_points ELSE 0 END) AS slow_points
    FROM charging_stations cs JOIN states s ON s.state_code = cs.state_code
    GROUP BY s.state_name, cs.state_code
    ORDER BY fast_points DESC
    """
    return pd.read_sql(text(q), engine)


def power_distribution(engine) -> pd.DataFrame:
    q = "SELECT power_kw, COUNT(*) AS n_stations FROM charging_stations GROUP BY power_kw ORDER BY power_kw"
    return pd.read_sql(text(q), engine)


def infrastructure_growth(engine) -> pd.DataFrame:
    q = """
    SELECT state_code,
           CAST(strftime('%Y', commissioning_date) AS INTEGER) AS year,
           COUNT(*) AS new_stations
    FROM charging_stations
    WHERE commissioning_date IS NOT NULL
    GROUP BY state_code, year
    ORDER BY year
    """
    try:
        return pd.read_sql(text(q), engine)
    except Exception:
        # Postgres date function fallback
        q_pg = """
        SELECT state_code, EXTRACT(YEAR FROM commissioning_date)::int AS year, COUNT(*) AS new_stations
        FROM charging_stations WHERE commissioning_date IS NOT NULL
        GROUP BY state_code, year ORDER BY year
        """
        return pd.read_sql(text(q_pg), engine)


def regional_gaps(engine, top_n: int = 5) -> pd.DataFrame:
    """States with the lowest chargers-per-100k — the headline 'underserved' view."""
    df = chargers_per_100k(engine)
    return df.sort_values("points_per_100k").head(top_n)


def electricity_demand_summary(engine) -> pd.DataFrame:
    q = """
    SELECT date(timestamp) AS day, AVG(load_mw) AS avg_load_mw,
           MAX(load_mw) AS peak_load_mw, MIN(load_mw) AS min_load_mw
    FROM electricity_timeseries GROUP BY day ORDER BY day
    """
    return pd.read_sql(text(q), engine)


def renewable_production(engine) -> pd.DataFrame:
    q = """
    SELECT date(timestamp) AS day,
           AVG(solar_mw) AS avg_solar_mw,
           AVG(wind_onshore_mw + COALESCE(wind_offshore_mw,0)) AS avg_wind_mw
    FROM electricity_timeseries GROUP BY day ORDER BY day
    """
    return pd.read_sql(text(q), engine)


ALL_KPIS = {
    "stations_per_state": stations_per_state,
    "chargers_per_100k": chargers_per_100k,
    "fast_vs_slow": fast_vs_slow,
    "power_distribution": power_distribution,
    "infrastructure_growth": infrastructure_growth,
    "regional_gaps": regional_gaps,
    "electricity_demand_summary": electricity_demand_summary,
    "renewable_production": renewable_production,
}


if __name__ == "__main__":
    engine = get_engine()
    for name, fn in ALL_KPIS.items():
        print(f"\n=== {name} ===")
        try:
            print(fn(engine).head(10).to_string(index=False))
        except Exception as e:
            print(f"  (skipped: {e})")
