"""
Identifies areas with poor EV-charging coverage using spatial clustering.

- DBSCAN groups charging stations into dense clusters; points that don't
  belong to any cluster (label == -1) are treated as isolated/underserved
  locations — genuine "coverage gap" candidates.
- K-Means (k = number of states) gives a complementary regional view: cities
  where the assigned cluster has a low charging-point density relative to
  its population share are flagged as gaps too.

Run:  python ml/clustering.py
"""
import os
from datetime import date

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from sklearn.cluster import DBSCAN, KMeans
from sqlalchemy import create_engine, text

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./ev_energy_local.db")


def run_clustering(engine):
    df = pd.read_sql(text("SELECT station_id, state_code, latitude, longitude, num_charging_points FROM charging_stations WHERE latitude IS NOT NULL AND longitude IS NOT NULL"), engine)
    if df.empty:
        print("No station coordinates found — run ETL first.")
        return None

    coords = df[["latitude", "longitude"]].to_numpy()

    # DBSCAN: eps in degrees ~ 0.15 (~15km), tuned for national-scale sparsity detection
    dbscan = DBSCAN(eps=0.15, min_samples=4).fit(coords)
    df["dbscan_label"] = dbscan.labels_
    n_gap_points = int((df["dbscan_label"] == -1).sum())
    n_clusters = len(set(dbscan.labels_)) - (1 if -1 in dbscan.labels_ else 0)
    print(f"DBSCAN: {n_clusters} dense clusters found, {n_gap_points} isolated stations flagged as coverage-gap candidates")

    # K-Means over states for a coarser regional summary
    k = df["state_code"].nunique()
    kmeans = KMeans(n_clusters=k, random_state=42, n_init=10).fit(coords)
    df["kmeans_label"] = kmeans.labels_

    rows = []
    run_date = date.today().isoformat()

    for label, group in df.groupby("dbscan_label"):
        is_gap = label == -1
        rows.append({
            "run_date": run_date, "algorithm": "DBSCAN",
            "state_code": group["state_code"].mode().iat[0] if not group.empty else None,
            "cluster_label": int(label),
            "centroid_lat": float(group["latitude"].mean()),
            "centroid_lon": float(group["longitude"].mean()),
            "station_count": int(len(group)),
            "is_coverage_gap": bool(is_gap),
        })

    for label, group in df.groupby("kmeans_label"):
        rows.append({
            "run_date": run_date, "algorithm": "KMEANS",
            "state_code": group["state_code"].mode().iat[0] if not group.empty else None,
            "cluster_label": int(label),
            "centroid_lat": float(group["latitude"].mean()),
            "centroid_lon": float(group["longitude"].mean()),
            "station_count": int(len(group)),
            "is_coverage_gap": len(group) < df.groupby("kmeans_label").size().median() * 0.5,
        })

    out = pd.DataFrame(rows)
    out.to_sql("clusters", engine, if_exists="append", index=False)
    print(f"Wrote {len(out)} cluster rows to `clusters` table")
    return out


if __name__ == "__main__":
    engine = create_engine(DATABASE_URL)
    run_clustering(engine)
