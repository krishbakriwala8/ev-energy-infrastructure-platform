"""
Next-day electricity load forecast using XGBoost and LightGBM on lag/time
features built from electricity_timeseries. Writes predictions into the
`forecasts` table.

Run:  python ml/load_forecast.py
"""
import os
from datetime import date

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sqlalchemy import create_engine, text

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./ev_energy_local.db")


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values("timestamp").copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["hour"] = df["timestamp"].dt.hour
    df["dow"] = df["timestamp"].dt.dayofweek
    df["is_weekend"] = (df["dow"] >= 5).astype(int)
    df["month"] = df["timestamp"].dt.month
    for lag in (1, 24, 168):  # 1h, 1 day, 1 week
        df[f"load_lag_{lag}"] = df["load_mw"].shift(lag)
    df["solar_mw"] = df["solar_mw"].fillna(0)
    df["wind_mw"] = df["wind_onshore_mw"].fillna(0) + df["wind_offshore_mw"].fillna(0)
    df = df.dropna(subset=[c for c in df.columns if "lag" in c])
    return df


FEATURES = ["hour", "dow", "is_weekend", "month", "load_lag_1", "load_lag_24", "load_lag_168", "solar_mw", "wind_mw"]


def train_and_forecast(engine):
    raw = pd.read_sql(text("SELECT timestamp, load_mw, solar_mw, wind_onshore_mw, wind_offshore_mw FROM electricity_timeseries WHERE state_code IS NULL ORDER BY timestamp"), engine)
    if len(raw) < 24 * 10:
        print(f"Not enough data ({len(raw)} rows) for a meaningful forecast — need >= 10 days. Run ETL first.")
        return None

    feat = build_features(raw)
    split = int(len(feat) * 0.85)
    train, test = feat.iloc[:split], feat.iloc[split:]

    X_train, y_train = train[FEATURES], train["load_mw"]
    X_test, y_test = test[FEATURES], test["load_mw"]

    results = {}

    try:
        import xgboost as xgb
        xgb_model = xgb.XGBRegressor(n_estimators=300, max_depth=6, learning_rate=0.05, subsample=0.8, colsample_bytree=0.8, random_state=42)
        xgb_model.fit(X_train, y_train)
        preds = xgb_model.predict(X_test)
        mae, rmse = mean_absolute_error(y_test, preds), mean_squared_error(y_test, preds) ** 0.5
        results["xgboost"] = (preds, mae, rmse)
        print(f"XGBoost   -> MAE {mae:.1f} MW, RMSE {rmse:.1f} MW")
    except ImportError:
        print("xgboost not installed, skipping")

    try:
        import lightgbm as lgb
        lgb_model = lgb.LGBMRegressor(n_estimators=300, max_depth=6, learning_rate=0.05, subsample=0.8, colsample_bytree=0.8, random_state=42, verbosity=-1)
        lgb_model.fit(X_train, y_train)
        preds = lgb_model.predict(X_test)
        mae, rmse = mean_absolute_error(y_test, preds), mean_squared_error(y_test, preds) ** 0.5
        results["lightgbm"] = (preds, mae, rmse)
        print(f"LightGBM  -> MAE {mae:.1f} MW, RMSE {rmse:.1f} MW")
    except ImportError:
        print("lightgbm not installed, skipping")

    if not results:
        print("No models available — install xgboost/lightgbm.")
        return None

    # persist forecasts for the test window
    rows = []
    run_date = date.today().isoformat()
    for model_name, (preds, mae, rmse) in results.items():
        for ts, actual, pred in zip(test["timestamp"], y_test, preds):
            rows.append({
                "run_date": run_date, "target_timestamp": ts, "model": model_name,
                "predicted_load_mw": float(pred), "actual_load_mw": float(actual),
                "mae": float(mae), "rmse": float(rmse),
            })
    out = pd.DataFrame(rows)
    out.to_sql("forecasts", engine, if_exists="append", index=False)
    print(f"Wrote {len(out)} forecast rows to `forecasts` table")
    return results


if __name__ == "__main__":
    engine = create_engine(DATABASE_URL)
    train_and_forecast(engine)
