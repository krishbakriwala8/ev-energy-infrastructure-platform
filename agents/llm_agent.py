"""
GenAI agent: turns a manager's plain-English question into
SQL -> statistics -> chart data -> LLM explanation.

The LLM (Groq, free tier — https://console.groq.com, no credit card) is
used for exactly two things: writing the SQL and narrating the already
-computed results. It never invents numbers — every figure quoted in the
final answer comes straight from the SQL execution, which keeps the agent
auditable for a competition demo (no hallucinated statistics).

Flow:
    question -> LLM writes SQL (schema-aware) -> execute SQL on Postgres
    -> pandas summary stats -> chart-ready data -> LLM writes explanation
    grounded in those exact numbers

Run standalone:
    export GROQ_API_KEY=gsk_...
    python agents/llm_agent.py "Which German regions appear underserved by public EV charging infrastructure?"
"""
import json
import os
import re
import sys

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./ev_energy_local.db")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

SCHEMA_SUMMARY = """
states(state_code, state_name)
charging_stations(station_id, operator, street, city, postal_code, state_code, latitude, longitude,
                   num_charging_points, power_kw, charge_type, is_fast_charger, commissioning_date, source_snapshot_date)
electricity_timeseries(ts_id, timestamp, state_code, load_mw, solar_mw, wind_onshore_mw, wind_offshore_mw)
regional_stats(state_code, year, population, gdp_per_capita_eur, registered_evs, area_km2)
clusters(cluster_run_id, run_date, algorithm, state_code, cluster_label, centroid_lat, centroid_lon, station_count, is_coverage_gap)
forecasts(forecast_id, run_date, target_timestamp, model, predicted_load_mw, actual_load_mw, mae, rmse)
need_scores(state_code, run_date, population_score, availability_score, capacity_score, electricity_score, growth_score, need_score, rank)
"""

SQL_SYSTEM_PROMPT = f"""You are a SQL analyst for a German EV-infrastructure and energy database.
Schema:
{SCHEMA_SUMMARY}
Rules:
- Write ONE read-only SQL SELECT query (SQLite/Postgres-compatible) that answers the user's question.
- Always JOIN to `states` for human-readable state_name when relevant.
- Only use tables/columns listed above.
- Keep it as simple as possible: prefer 1-2 JOINs over long chains, and avoid joining a table you don't need.
- Return ONLY the complete SQL query, no markdown fences, no explanation, no truncation.
"""

EXPLAIN_SYSTEM_PROMPT = """You are a data analyst explaining results to a non-technical manager.
You will be given: the original question, the SQL query that was run, and the resulting data
(as JSON records) plus summary statistics. Write a concise (3-6 sentence) explanation grounded
strictly in the numbers provided. Never invent a number that isn't in the data. If comparing two
things, state the difference plainly. End with one concrete recommendation if the question implies
a decision (e.g. where to invest)."""


def get_groq_client():
    from groq import Groq
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY not set. Get a free key at https://console.groq.com")
    return Groq(api_key=api_key)


def _extract_sql(text_out: str) -> str:
    text_out = text_out.strip()
    text_out = re.sub(r"^```sql\s*|```$", "", text_out, flags=re.IGNORECASE | re.MULTILINE).strip()
    return text_out


def question_to_sql(client, question: str) -> str:
    resp = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": SQL_SYSTEM_PROMPT},
            {"role": "user", "content": question},
        ],
        temperature=0,
        max_tokens=1000,
    )
    choice = resp.choices[0]
    if choice.finish_reason == "length":
        raise RuntimeError(
            "The LLM's SQL got cut off before finishing (hit the token limit). "
            "Try rephrasing the question more simply, or re-ask."
        )
    return _extract_sql(choice.message.content)


def is_safe_select(sql: str) -> bool:
    lowered = sql.strip().lower()
    if not lowered.startswith("select"):
        return False
    forbidden = ("insert", "update", "delete", "drop", "alter", "truncate", ";--", "attach")
    return not any(f in lowered for f in forbidden)


def run_sql(engine, sql: str) -> pd.DataFrame:
    return pd.read_sql(text(sql), engine)


def summarize(df: pd.DataFrame) -> dict:
    summary = {"n_rows": len(df)}
    numeric_cols = df.select_dtypes("number").columns
    for col in numeric_cols:
        summary[f"{col}_min"] = float(df[col].min())
        summary[f"{col}_max"] = float(df[col].max())
        summary[f"{col}_mean"] = round(float(df[col].mean()), 2)
    return summary


def explain_results(client, question: str, sql: str, df: pd.DataFrame) -> str:
    records = df.head(20).to_dict(orient="records")
    payload = {
        "question": question, "sql": sql,
        "data_sample": records, "summary_stats": summarize(df),
    }
    resp = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": EXPLAIN_SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(payload, default=str)},
        ],
        temperature=0.3,
        max_tokens=400,
    )
    return resp.choices[0].message.content


def ask(question: str):
    """Full pipeline: question -> SQL -> execute -> stats -> chart -> LLM explanation."""
    engine = create_engine(DATABASE_URL)
    client = get_groq_client()

    sql = question_to_sql(client, question)
    if not is_safe_select(sql):
        raise ValueError(f"Generated SQL failed safety check:\n{sql}")

    df = run_sql(engine, sql)
    explanation = explain_results(client, question, sql, df)

    return {"question": question, "sql": sql, "data": df, "explanation": explanation}


if __name__ == "__main__":
    q = " ".join(sys.argv[1:]) or "Which German regions appear underserved by public EV charging infrastructure?"
    result = ask(q)
    print("SQL:\n", result["sql"])
    print("\nData:\n", result["data"].head(10).to_string(index=False))
    print("\nExplanation:\n", result["explanation"])
