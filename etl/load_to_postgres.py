"""
Loads the CSVs in data/raw/ (either from fetch_real_data.py or
generate_sample_data.py — same schema either way) into PostgreSQL.

Usage:
    export DATABASE_URL="postgresql://postgres:pw@localhost:5432/ev_energy"
    psql $DATABASE_URL -f db/schema.sql
    python etl/load_to_postgres.py
"""
import os
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./ev_energy_local.db")


def get_engine():
    return create_engine(DATABASE_URL)


def load_states(engine):
    path = RAW_DIR / "states.csv"
    if not path.exists():
        print("states.csv missing — run etl/generate_sample_data.py or fetch_real_data.py first")
        return
    df = pd.read_csv(path)
    df.to_sql("states", engine, if_exists="append", index=False)
    print(f"Loaded {len(df)} states")


def load_charging_stations(engine):
    path = RAW_DIR / "ladesaeulenregister.csv"
    if not path.exists():
        print("ladesaeulenregister.csv missing — run ETL fetch/generate first")
        return
    df = pd.read_csv(path)
    # normalize German BNetzA raw columns to our schema if present (real-data path)
    rename_map = {
        "Betreiber": "operator", "Straße": "street", "Postleitzahl": "postal_code",
        "Ort": "city", "Bundesland": "state_name", "Breitengrad": "latitude",
        "Längengrad": "longitude", "Anzahl Ladepunkte": "num_charging_points",
        "Inbetriebnahmedatum": "commissioning_date",
    }
    df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})
    if "station_id" in df.columns:
        df = df.drop(columns=["station_id"])  # let DB assign serial PK
    df.to_sql("charging_stations", engine, if_exists="append", index=False)
    print(f"Loaded {len(df)} charging stations")


def load_electricity_timeseries(engine):
    path = RAW_DIR / "electricity_timeseries.csv"
    if not path.exists():
        print("electricity_timeseries.csv missing — run ETL fetch/generate first")
        return
    df = pd.read_csv(path, parse_dates=["timestamp"])
    df.to_sql("electricity_timeseries", engine, if_exists="append", index=False)
    print(f"Loaded {len(df)} electricity time-series rows")


def load_regional_stats(engine):
    path = RAW_DIR / "regional_stats.csv"
    if not path.exists():
        print("regional_stats.csv missing — run ETL fetch/generate first")
        return
    df = pd.read_csv(path)
    df.to_sql("regional_stats", engine, if_exists="append", index=False)
    print(f"Loaded {len(df)} regional-stat rows")


if __name__ == "__main__":
    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    print(f"Connected to {DATABASE_URL.split('@')[-1] if '@' in DATABASE_URL else DATABASE_URL}")
    load_states(engine)
    load_charging_stations(engine)
    load_electricity_timeseries(engine)
    load_regional_stats(engine)
    print("ETL load complete.")
