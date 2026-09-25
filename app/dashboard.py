"""
Streamlit demo app — this is what you present at the competition.

Run:  streamlit run app/dashboard.py
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import plotly.express as px
import streamlit as st
from dotenv import load_dotenv
from sqlalchemy import create_engine

from analytics.kpis import ALL_KPIS

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./ev_energy_local.db")

st.set_page_config(page_title="German Energy & EV Infrastructure Intelligence", layout="wide")

@st.cache_resource
def get_engine():
    return create_engine(DATABASE_URL)

engine = get_engine()

st.title("🔌 German Energy & EV Infrastructure Intelligence Platform")
st.caption(
    "Bundesnetzagentur charging-station register + electricity system data + Destatis regional "
    "statistics -> analytics -> ML forecasting/clustering -> GenAI agent. All free data, no Docker."
)

tab_overview, tab_energy, tab_ml, tab_agent = st.tabs(
    ["📊 Infrastructure Overview", "⚡ Electricity System", "🤖 ML: Forecast, Clusters & Need Score", "💬 Ask the Agent"]
)

# ---------------------------------------------------------------- Overview
with tab_overview:
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Charging stations per state")
        df = ALL_KPIS["stations_per_state"](engine)
        st.plotly_chart(px.bar(df, x="state_name", y="station_count", color="charging_points",
                                labels={"state_name": "State", "station_count": "Stations"}), use_container_width=True)

    with col2:
        st.subheader("Chargers per 100k inhabitants")
        df2 = ALL_KPIS["chargers_per_100k"](engine)
        st.plotly_chart(px.bar(df2.sort_values("points_per_100k"), x="points_per_100k", y="state_name", orientation="h",
                                labels={"points_per_100k": "Points / 100k pop.", "state_name": "State"}), use_container_width=True)

    col3, col4 = st.columns(2)
    with col3:
        st.subheader("Fast vs. slow charging")
        df3 = ALL_KPIS["fast_vs_slow"](engine)
        melted = df3.melt(id_vars=["state_name"], value_vars=["fast_points", "slow_points"], var_name="type", value_name="points")
        st.plotly_chart(px.bar(melted, x="state_name", y="points", color="type", barmode="stack"), use_container_width=True)

    with col4:
        st.subheader("Charging-power distribution")
        df4 = ALL_KPIS["power_distribution"](engine)
        st.plotly_chart(px.bar(df4, x="power_kw", y="n_stations", labels={"power_kw": "Power (kW)", "n_stations": "Stations"}), use_container_width=True)

    st.subheader("Regional gaps — most underserved states (lowest chargers per 100k)")
    st.dataframe(ALL_KPIS["regional_gaps"](engine), use_container_width=True)

    st.subheader("Infrastructure growth over time")
    dfg = ALL_KPIS["infrastructure_growth"](engine)
    if not dfg.empty:
        yearly = dfg.groupby("year")["new_stations"].sum().reset_index()
        st.plotly_chart(px.line(yearly, x="year", y="new_stations", markers=True), use_container_width=True)

# ---------------------------------------------------------------- Energy
with tab_energy:
    st.subheader("Electricity demand")
    d1 = ALL_KPIS["electricity_demand_summary"](engine)
    if not d1.empty:
        st.plotly_chart(px.line(d1, x="day", y=["avg_load_mw", "peak_load_mw", "min_load_mw"]), use_container_width=True)

    st.subheader("Wind & solar production")
    d2 = ALL_KPIS["renewable_production"](engine)
    if not d2.empty:
        st.plotly_chart(px.area(d2, x="day", y=["avg_solar_mw", "avg_wind_mw"]), use_container_width=True)

# ---------------------------------------------------------------- ML
with tab_ml:
    st.subheader("Next-day load forecast (XGBoost / LightGBM)")
    try:
        fdf = pd.read_sql("SELECT * FROM forecasts ORDER BY target_timestamp", engine)
        if fdf.empty:
            st.info("No forecasts yet — run `python ml/load_forecast.py` first.")
        else:
            st.plotly_chart(px.line(fdf, x="target_timestamp", y=["predicted_load_mw", "actual_load_mw"], color="model"), use_container_width=True)
            st.dataframe(fdf.groupby("model")[["mae", "rmse"]].first().reset_index())
    except Exception as e:
        st.warning(f"Forecast table not available yet: {e}")

    st.subheader("Infrastructure coverage-gap clusters")
    try:
        cdf = pd.read_sql("SELECT * FROM clusters WHERE algorithm='DBSCAN' ORDER BY run_date DESC LIMIT 500", engine)
        if cdf.empty:
            st.info("No cluster results yet — run `python ml/clustering.py` first.")
        else:
            st.plotly_chart(px.scatter_mapbox(cdf, lat="centroid_lat", lon="centroid_lon", color="is_coverage_gap",
                                               size="station_count", zoom=4.5, mapbox_style="carto-positron",
                                               center={"lat": 51.2, "lon": 10.4}), use_container_width=True)
    except Exception as e:
        st.warning(f"Cluster table not available yet: {e}")

    st.subheader("EV Infrastructure Need Score (investment priority ranking)")
    try:
        ndf = pd.read_sql("""
            SELECT ns.*, s.state_name FROM need_scores ns JOIN states s ON s.state_code = ns.state_code
            WHERE run_date = (SELECT MAX(run_date) FROM need_scores) ORDER BY rank
        """, engine)
        if ndf.empty:
            st.info("No need scores yet — run `python ml/scoring.py` first.")
        else:
            st.plotly_chart(px.bar(ndf.sort_values("need_score"), x="need_score", y="state_name", orientation="h",
                                    color="need_score", color_continuous_scale="Reds"), use_container_width=True)
            st.dataframe(ndf, use_container_width=True)
    except Exception as e:
        st.warning(f"Need-score table not available yet: {e}")

# ---------------------------------------------------------------- Agent
with tab_agent:
    st.subheader("Ask a question in plain English")
    st.caption("e.g. 'Which German regions appear underserved by public EV charging infrastructure?' or 'Compare Bavaria and Brandenburg.'")
    q = st.text_input("Your question", value="Which German regions appear underserved by public EV charging infrastructure?")
    if st.button("Ask"):
        if not os.getenv("GROQ_API_KEY"):
            st.error("Set GROQ_API_KEY (free at console.groq.com) to enable the agent.")
        else:
            from agents.llm_agent import ask
            with st.spinner("SQL -> statistics -> chart -> LLM explanation..."):
                result = ask(q)
            st.code(result["sql"], language="sql")
            st.dataframe(result["data"], use_container_width=True)
            if len(result["data"].columns) >= 2:
                numeric_cols = result["data"].select_dtypes("number").columns
                if len(numeric_cols) >= 1:
                    label_col = [c for c in result["data"].columns if c not in numeric_cols][0] if len(result["data"].columns) > len(numeric_cols) else result["data"].columns[0]
                    st.plotly_chart(px.bar(result["data"], x=label_col, y=numeric_cols[0]), use_container_width=True)
            st.markdown("### Explanation")
            st.write(result["explanation"])
