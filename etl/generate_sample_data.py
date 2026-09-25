"""
Generates realistic, schema-identical OFFLINE sample data so the whole
pipeline (ETL -> Postgres -> analytics -> ML -> agent -> dashboard) can be
demoed with zero internet access.

The generator is anchored to real published aggregates so the numbers are
directionally correct, not arbitrary:
  - BNetzA Ladesäulenregister (1 May 2026): 151,452 normal + 52,499 fast
    charging points nationally -> ~204k total. We distribute this total
    across states roughly proportional to population and known regional
    skew (Bavaria/BW/NRW have the densest networks).
  - State populations are 2024 Destatis estimates (millions), used to derive
    per-state charger counts, registered EVs and electricity load shares.

Swap this for etl/fetch_real_data.py output whenever you have internet
access on demo day — both scripts write the exact same CSV schemas into
data/raw/, so nothing downstream needs to change.
"""
import random
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

random.seed(42)
np.random.seed(42)

RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)

# state_code, name, population (millions, ~2024 Destatis), area_km2, gdp_per_capita_eur (approx)
STATES = [
    ("NW", "North Rhine-Westphalia", 18.14, 34113, 42600),
    ("BY", "Bavaria", 13.37, 70542, 49700),
    ("BW", "Baden-Württemberg", 11.28, 35748, 48900),
    ("NI", "Lower Saxony", 8.14, 47710, 39100),
    ("HE", "Hesse", 6.39, 21115, 48800),
    ("SN", "Saxony", 4.09, 18450, 33200),
    ("RP", "Rhineland-Palatinate", 4.16, 19854, 39900),
    ("BE", "Berlin", 3.85, 891, 43800),
    ("SH", "Schleswig-Holstein", 2.95, 15804, 36700),
    ("BB", "Brandenburg", 2.57, 29654, 33800),
    ("ST", "Saxony-Anhalt", 2.18, 20452, 31800),
    ("TH", "Thuringia", 2.11, 16172, 32000),
    ("HH", "Hamburg", 1.94, 755, 61200),
    ("MV", "Mecklenburg-Vorpommern", 1.61, 23295, 30800),
    ("SL", "Saarland", 0.99, 2570, 37600),
    ("HB", "Bremen", 0.68, 419, 46900),
]

TOTAL_NORMAL_POINTS = 151_452
TOTAL_FAST_POINTS = 52_499
TOTAL_POP = sum(s[2] for s in STATES)

OPERATORS = [
    "EnBW mobility+", "E.ON Drive", "Ionity", "Tesla Supercharger", "EWE Go",
    "Allego", "Aral pulse", "Fastned", "innogy eMobility Solutions",
    "Stadtwerke München", "Stadtwerke Leipzig", "RWE eMobility", "EnviaM",
    "Maingau Energie", "Pfalzwerke", "TotalEnergies", "Shell Recharge",
]

AC_POWERS = [3.7, 11, 22]
DC_POWERS = [50, 75, 100, 150, 175, 300]


def generate_states_csv():
    df = pd.DataFrame(STATES, columns=["state_code", "state_name", "population_m", "area_km2", "gdp_per_capita_eur"])
    df[["state_code", "state_name"]].to_csv(RAW_DIR / "states.csv", index=False)
    return df


def generate_charging_stations(states_df: pd.DataFrame, snapshot_date: str = "2026-08-01"):
    rows = []
    station_id = 1
    for _, s in states_df.iterrows():
        pop_share = s.population_m / TOTAL_POP
        # slight urban/tech skew so BY/BW/HH look a bit denser per capita, matching real reporting
        skew = {"BY": 1.15, "BW": 1.12, "HH": 1.2, "BE": 1.1, "NW": 1.0}.get(s.state_code, 0.9)
        n_normal = max(5, int(TOTAL_NORMAL_POINTS * pop_share * skew))
        n_fast = max(2, int(TOTAL_FAST_POINTS * pop_share * skew))

        # deliberately under-serve a couple of rural states to create a realistic "gap" story
        if s.state_code in ("BB", "MV", "ST", "TH"):
            n_normal = int(n_normal * 0.55)
            n_fast = int(n_fast * 0.5)

        n_stations = max(3, (n_normal + n_fast) // 4)  # ~4 charging points per station on average

        # rough bounding box per state for lat/lon scatter (approximate, good enough for demo maps)
        bbox = STATE_BBOX[s.state_code]
        for _ in range(n_stations):
            is_fast = random.random() < (n_fast / max(1, (n_normal + n_fast)))
            power = random.choice(DC_POWERS) if is_fast else random.choice(AC_POWERS)
            points = random.choice([1, 1, 2, 2, 4]) if not is_fast else random.choice([1, 2])
            commission_year = random.choices(
                [2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026],
                weights=[2, 3, 5, 8, 12, 16, 20, 20, 14],
            )[0]
            commission_date = f"{commission_year}-{random.randint(1,12):02d}-{random.randint(1,28):02d}"
            rows.append({
                "station_id": station_id,
                "operator": random.choice(OPERATORS),
                "street": f"Hauptstraße {random.randint(1,200)}",
                "city": f"{s.state_name} City {random.randint(1,50)}",
                "postal_code": f"{random.randint(10000,99999)}",
                "state_code": s.state_code,
                "latitude": round(random.uniform(bbox[0], bbox[1]), 5),
                "longitude": round(random.uniform(bbox[2], bbox[3]), 5),
                "num_charging_points": points,
                "power_kw": power,
                "charge_type": "DC" if is_fast else "AC",
                "is_fast_charger": is_fast,
                "commissioning_date": commission_date,
                "source_snapshot_date": snapshot_date,
            })
            station_id += 1
    df = pd.DataFrame(rows)
    df.to_csv(RAW_DIR / "ladesaeulenregister.csv", index=False)
    print(f"Generated {len(df)} charging stations -> data/raw/ladesaeulenregister.csv")
    return df


# approximate state bounding boxes: (lat_min, lat_max, lon_min, lon_max)
STATE_BBOX = {
    "NW": (50.3, 52.5, 5.9, 9.5), "BY": (47.3, 50.6, 9.0, 13.9),
    "BW": (47.5, 49.8, 7.5, 10.5), "NI": (51.3, 53.9, 6.7, 11.6),
    "HE": (49.4, 51.7, 7.8, 10.3), "SN": (50.2, 51.7, 11.9, 15.0),
    "RP": (48.9, 50.9, 6.1, 8.5), "BE": (52.3, 52.7, 13.1, 13.8),
    "SH": (53.4, 55.1, 7.9, 11.3), "BB": (51.4, 53.6, 11.2, 14.8),
    "ST": (50.9, 53.0, 10.6, 13.2), "TH": (50.2, 51.6, 9.9, 12.7),
    "HH": (53.4, 53.7, 9.7, 10.3), "MV": (53.1, 54.7, 10.6, 14.4),
    "SL": (49.1, 49.6, 6.4, 7.4), "HB": (53.0, 53.6, 8.5, 8.9),
}


def generate_electricity_timeseries(days: int = 60):
    """Hourly national load / solar / wind time series, realistic diurnal + seasonal shape."""
    start = datetime(2026, 7, 1)
    hours = days * 24
    timestamps = [start + timedelta(hours=h) for h in range(hours)]

    rows = []
    for ts in timestamps:
        hour = ts.hour
        day_of_year = ts.timetuple().tm_yday
        # base national load: ~45-75 GW diurnal curve, lower on weekends
        weekday_factor = 0.85 if ts.weekday() >= 5 else 1.0
        diurnal = 55 + 18 * np.sin((hour - 4) / 24 * 2 * np.pi - np.pi / 2)
        load = max(35, diurnal * weekday_factor + np.random.normal(0, 2.5)) * 1000  # MW

        # solar: bell curve around midday, seasonal amplitude
        solar_potential = max(0, np.sin((hour - 6) / 12 * np.pi)) if 6 <= hour <= 20 else 0
        seasonal = 0.6 + 0.4 * np.sin((day_of_year - 172) / 365 * 2 * np.pi)  # peak ~ summer solstice
        solar = solar_potential * 28000 * seasonal * max(0.2, np.random.normal(0.85, 0.2))

        # wind: noisier, less diurnal, onshore >> offshore
        wind_onshore = max(0, np.random.normal(14000, 6000))
        wind_offshore = max(0, np.random.normal(4500, 2200))

        rows.append({
            "timestamp": ts, "state_code": None,
            "load_mw": round(load, 1), "solar_mw": round(solar, 1),
            "wind_onshore_mw": round(wind_onshore, 1), "wind_offshore_mw": round(wind_offshore, 1),
        })
    df = pd.DataFrame(rows)
    df.to_csv(RAW_DIR / "electricity_timeseries.csv", index=False)
    print(f"Generated {len(df)} hourly electricity records -> data/raw/electricity_timeseries.csv")
    return df


def generate_regional_stats(states_df: pd.DataFrame):
    rows = []
    for _, s in states_df.iterrows():
        for year in (2023, 2024, 2025):
            growth = {2023: 0.75, 2024: 0.88, 2025: 1.0}[year]
            # registered BEVs roughly proportional to population & GDP, with EV-adoption growth over years
            base_evs_per_1000 = 9 + (s.gdp_per_capita_eur - 30000) / 4000
            registered_evs = int(max(500, base_evs_per_1000 * s.population_m * 1000 * growth / 10))
            rows.append({
                "state_code": s.state_code, "year": year,
                "population": int(s.population_m * 1_000_000 * (0.995 + 0.003 * (year - 2023))),
                "gdp_per_capita_eur": round(s.gdp_per_capita_eur * (0.97 + 0.015 * (year - 2023)), 0),
                "registered_evs": registered_evs,
                "area_km2": s.area_km2,
            })
    df = pd.DataFrame(rows)
    df.to_csv(RAW_DIR / "regional_stats.csv", index=False)
    print(f"Generated {len(df)} regional-stat rows -> data/raw/regional_stats.csv")
    return df


if __name__ == "__main__":
    print("Generating realistic OFFLINE sample data (schema-identical to real sources)...")
    states_df = generate_states_csv()
    generate_charging_stations(states_df)
    generate_electricity_timeseries()
    generate_regional_stats(states_df)
    print("\nDone. These CSVs in data/raw/ are drop-in compatible with etl/load_to_postgres.py")
