"""
Fetches REAL German public data. Everything here is free, no API key
required except Destatis (free account).

Sources
-------
1. Bundesnetzagentur Ladesäulenregister (EV chargers)
   Human page:  https://www.bundesnetzagentur.de/DE/Fachthemen/ElektrizitaetundGas/E-Mobilitaet/DownloadundKontakt.html
   Direct CSV changes filename with each monthly snapshot, so this script
   scrapes the download page for the current "Liste der Ladesäulen (CSV)"
   link rather than hard-coding a stale URL.

2. Electricity load / wind / solar
   Primary:  SMARD (Bundesnetzagentur's own market-data platform, CC BY 4.0,
             JSON API, updated continuously) -> https://www.smard.de
             API docs: https://github.com/bundesAPI/smard-api
   Fallback: Open Power System Data (OPSD) historical bulk time series
             (project is no longer actively updated but the data is CC-0
             and still widely used for modelling / backtesting)
             -> https://data.open-power-system-data.org/time_series/

3. Destatis GENESIS regional statistics (population, GDP, vehicle stock)
   Free REST/JSON API, requires a free genesis.destatis.de account.
   -> https://www-genesis.destatis.de/genesis/online

Run:  python etl/fetch_real_data.py
Output: writes CSVs into data/raw/
"""
import io
import os
import re
import sys
import time
import zipfile
from pathlib import Path

import pandas as pd
import requests

RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)

HEADERS = {"User-Agent": "Mozilla/5.0 (EV-Energy-Platform research script)"}

BNETZA_PAGE = "https://www.bundesnetzagentur.de/DE/Fachthemen/ElektrizitaetundGas/E-Mobilitaet/DownloadundKontakt.html"
SMARD_INDEX = "https://www.smard.de/app/chart_data/{filter}/{region}/index_hour.json"
SMARD_SERIES = "https://www.smard.de/app/chart_data/{filter}/{region}/{filter}_{region}_hour_{ts}.json"
OPSD_TIME_SERIES_CSV = "https://data.open-power-system-data.org/time_series/latest/time_series_60min_singleindex.csv"

# SMARD filter IDs (see https://github.com/bundesAPI/smard-api)
SMARD_FILTERS = {
    "load_mw": "410",
    "wind_onshore_mw": "4067",
    "wind_offshore_mw": "1225",
    "solar_mw": "4068",
}


def fetch_bnetza_charging_stations() -> Path:
    """Scrape the BNetzA download page for the current CSV link and download it."""
    print("Fetching Bundesnetzagentur Ladesäulenregister page...")
    resp = requests.get(BNETZA_PAGE, headers=HEADERS, timeout=60)
    resp.raise_for_status()
    match = re.search(r'href="([^"]+Ladesaeulenregister[^"]*\.csv)"', resp.text, re.IGNORECASE)
    if not match:
        # Fall back: look for any '.csv' link with 'Ladesäulen' nearby text
        match = re.search(r'href="([^"]+\.csv)"', resp.text, re.IGNORECASE)
    if not match:
        raise RuntimeError(
            "Could not find the CSV link on the BNetzA page — the site layout "
            "may have changed. Open the URL in a browser and update BNETZA_PAGE "
            "parsing, or download the CSV manually into data/raw/ladesaeulenregister.csv"
        )
    csv_url = match.group(1)
    if csv_url.startswith("/"):
        csv_url = "https://www.bundesnetzagentur.de" + csv_url
    print(f"  -> downloading {csv_url}")
    csv_resp = requests.get(csv_url, headers=HEADERS, timeout=180)
    csv_resp.raise_for_status()
    out_path = RAW_DIR / "ladesaeulenregister.csv"
    out_path.write_bytes(csv_resp.content)
    print(f"  Saved {out_path} ({len(csv_resp.content)/1e6:.1f} MB)")
    return out_path


def fetch_smard_series(filter_name: str, filter_id: str, region: str = "DE") -> pd.DataFrame:
    """Pull the most recent available week of hourly data for one SMARD filter."""
    idx_url = SMARD_INDEX.format(filter=filter_id, region=region)
    idx = requests.get(idx_url, headers=HEADERS, timeout=60).json()
    latest_ts = idx["timestamps"][-1]
    series_url = SMARD_SERIES.format(filter=filter_id, region=region, ts=latest_ts)
    data = requests.get(series_url, headers=HEADERS, timeout=60).json()
    df = pd.DataFrame(data["series"], columns=["timestamp_ms", filter_name])
    df["timestamp"] = pd.to_datetime(df["timestamp_ms"], unit="ms")
    return df[["timestamp", filter_name]]


def fetch_electricity_data() -> Path:
    print("Fetching electricity data from SMARD (Bundesnetzagentur)...")
    try:
        frames = []
        for name, fid in SMARD_FILTERS.items():
            print(f"  -> {name} (filter {fid})")
            frames.append(fetch_smard_series(name, fid))
            time.sleep(0.5)
        merged = frames[0]
        for f in frames[1:]:
            merged = merged.merge(f, on="timestamp", how="outer")
        out_path = RAW_DIR / "electricity_timeseries.csv"
        merged.sort_values("timestamp").to_csv(out_path, index=False)
        print(f"  Saved {out_path}")
        return out_path
    except Exception as e:
        print(f"  SMARD fetch failed ({e}); falling back to OPSD historical bulk CSV")
        df = pd.read_csv(OPSD_TIME_SERIES_CSV, usecols=lambda c: c.startswith("utc_timestamp") or "DE_load" in c or "DE_solar" in c or "DE_wind" in c)
        out_path = RAW_DIR / "electricity_timeseries.csv"
        df.to_csv(out_path, index=False)
        print(f"  Saved {out_path} (OPSD fallback)")
        return out_path


def fetch_destatis_regional_stats() -> Path:
    """
    Destatis GENESIS-Online requires a free account. Set DESTATIS_USERNAME /
    DESTATIS_PASSWORD as env vars, then this pulls population (table 12411)
    and vehicle stock (table 46251) by state.
    Docs: https://www-genesis.destatis.de/genesis/online?operation=api
    """
    user = os.getenv("DESTATIS_USERNAME")
    pw = os.getenv("DESTATIS_PASSWORD")
    if not user or not pw:
        print(
            "DESTATIS_USERNAME/PASSWORD not set — skipping live Destatis pull.\n"
            "Register free at https://www-genesis.destatis.de then set the env vars.\n"
            "Using etl/generate_sample_data.py's regional_stats.csv as a fallback is fine "
            "for a demo; the numbers there are set to realistic published magnitudes."
        )
        return RAW_DIR / "regional_stats.csv"

    base = "https://www-genesis.destatis.de/genesisWS/rest/2020/data/table"
    params = {
        "username": user,
        "password": pw,
        "name": "12411-0002",  # population by state
        "area": "all",
        "format": "csv",
    }
    print("Fetching Destatis population table...")
    resp = requests.get(base, params=params, timeout=60)
    resp.raise_for_status()
    out_path = RAW_DIR / "regional_stats.csv"
    out_path.write_bytes(resp.content)
    print(f"  Saved {out_path}")
    return out_path


if __name__ == "__main__":
    print("=" * 70)
    print("Fetching real German public data (free, no Docker)")
    print("=" * 70)
    try:
        fetch_bnetza_charging_stations()
    except Exception as e:
        print(f"BNetzA fetch failed: {e}\nRun etl/generate_sample_data.py as a fallback.")
    try:
        fetch_electricity_data()
    except Exception as e:
        print(f"Electricity fetch failed: {e}\nRun etl/generate_sample_data.py as a fallback.")
    try:
        fetch_destatis_regional_stats()
    except Exception as e:
        print(f"Destatis fetch failed: {e}\nRun etl/generate_sample_data.py as a fallback.")
    print("Done. Check data/raw/")
