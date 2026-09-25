"""
EV Infrastructure Need Score: a 0-100 composite ranking of which German
states most need new public charging investment, combining:

  population_score    - larger population, un-served by current infra -> higher need
  availability_score   - fewer chargers per capita -> higher need
  capacity_score        - lower average charging power (fewer fast chargers) -> higher need
  electricity_score      - lower renewable share / more grid headroom -> more capacity to add
  growth_score             - slower recent infrastructure growth relative to EV growth -> higher need

Each sub-score is min-max normalized to 0-100 across states, then combined
with weights that can be tuned in WEIGHTS below. Higher need_score = higher
investment priority.

Run:  python ml/scoring.py
"""
import os
from datetime import date

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./ev_energy_local.db")

WEIGHTS = {
    "population_score": 0.20,
    "availability_score": 0.30,
    "capacity_score": 0.20,
    "electricity_score": 0.10,
    "growth_score": 0.20,
}


def minmax_0_100(series: pd.Series, invert: bool = False) -> pd.Series:
    lo, hi = series.min(), series.max()
    if hi == lo:
        return pd.Series([50.0] * len(series), index=series.index)
    scaled = (series - lo) / (hi - lo) * 100
    return 100 - scaled if invert else scaled


def compute_need_scores(engine) -> pd.DataFrame:
    latest_year = pd.read_sql(text("SELECT MAX(year) AS y FROM regional_stats"), engine)["y"].iat[0]

    stations = pd.read_sql(text("""
        SELECT state_code,
               COUNT(*) AS n_stations,
               SUM(num_charging_points) AS n_points,
               AVG(power_kw) AS avg_power_kw
        FROM charging_stations GROUP BY state_code
    """), engine)

    regional = pd.read_sql(text(f"SELECT * FROM regional_stats WHERE year = {int(latest_year)}"), engine)

    growth = pd.read_sql(text("""
        SELECT state_code, COUNT(*) AS recent_new_stations
        FROM charging_stations
        WHERE commissioning_date >= '2025-01-01'
        GROUP BY state_code
    """), engine)

    df = regional.merge(stations, on="state_code", how="left").merge(growth, on="state_code", how="left")
    df[["n_stations", "n_points", "avg_power_kw", "recent_new_stations"]] = df[["n_stations", "n_points", "avg_power_kw", "recent_new_stations"]].fillna(0)

    df["points_per_100k"] = df["n_points"] * 100000 / df["population"].replace(0, pd.NA)
    df["evs_per_point"] = df["registered_evs"] / df["n_points"].replace(0, pd.NA)
    df["growth_vs_ev_growth"] = df["recent_new_stations"] / df["registered_evs"].replace(0, pd.NA)

    df["population_score"] = minmax_0_100(df["population"])
    df["availability_score"] = minmax_0_100(df["points_per_100k"], invert=True)  # fewer points/100k -> higher need
    df["capacity_score"] = minmax_0_100(df["avg_power_kw"], invert=True)          # lower avg power -> higher need
    # electricity_score: proxy — states with lower area-normalized station density have more grid headroom to add capacity
    df["electricity_score"] = minmax_0_100(df["area_km2"] / df["n_stations"].replace(0, pd.NA))
    df["growth_score"] = minmax_0_100(df["growth_vs_ev_growth"], invert=True)     # slower growth vs EV uptake -> higher need

    df["need_score"] = sum(df[col] * w for col, w in WEIGHTS.items())
    df["rank"] = df["need_score"].rank(ascending=False, method="min").astype(int)
    df["run_date"] = date.today().isoformat()

    out_cols = ["state_code", "run_date", "population_score", "availability_score",
                "capacity_score", "electricity_score", "growth_score", "need_score", "rank"]
    out = df[out_cols].sort_values("rank")
    out.to_sql("need_scores", engine, if_exists="append", index=False)
    print(f"Wrote {len(out)} need-score rows to `need_scores` table")
    print(out.round(1).to_string(index=False))
    return out


if __name__ == "__main__":
    engine = create_engine(DATABASE_URL)
    compute_need_scores(engine)
