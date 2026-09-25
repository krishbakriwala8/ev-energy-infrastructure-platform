# German Energy & EV Infrastructure Intelligence Platform

An end-to-end data platform that answers: **Where does Germany need more EV
charging infrastructure, how is electricity demand changing, and what will
future demand look like?**

Built entirely on **free** data and **free** tools — no paid API, no Docker,
no cloud bill. PostgreSQL is the only external service required, and you
said you already have it installed.

```
Bundesnetzagentur EV Data + OPSD Energy Data + Destatis Regional Data
        -> ETL -> PostgreSQL -> Analytics -> ML Forecast -> Clustering
        -> Need Score -> GenAI Agent (NL -> SQL -> stats -> chart -> explanation)
        -> Streamlit dashboard -> Monthly automation
```

## 1. Why every piece is free

| Layer | Tool | Cost |
|---|---|---|
| EV charger data | Bundesnetzagentur Ladesäulenregister (CSV/XLSX, CC BY 4.0) | Free, no key |
| Electricity data | Open Power System Data (OPSD) time series | Free, no key |
| Regional stats | Destatis GENESIS REST API | Free, requires a free account (genesis.destatis.de) |
| Database | PostgreSQL (your local instance) | Free, you already have it |
| ML | scikit-learn, XGBoost, LightGBM | Free, open source |
| LLM (GenAI agent) | Groq API (Llama 3.1/3.3, free tier — you already used this in your email-summarizer project) | Free tier, no credit card |
| Dashboard | Streamlit | Free, open source |
| Automation | Python `schedule` / cron | Free, no Docker needed |

No Docker anywhere. Everything runs as plain Python processes against your
local PostgreSQL.

## 2. Project layout

```
ev-energy-platform/
├── db/schema.sql                 # PostgreSQL schema
├── etl/
│   ├── fetch_real_data.py        # downloads real BNetzA/OPSD/Destatis data
│   ├── generate_sample_data.py   # generates realistic offline sample data
│   │                              #   (schema-identical) so the whole
│   │                              #   pipeline runs even without internet
│   │                              #   access during a demo
│   └── load_to_postgres.py       # loads CSVs into PostgreSQL
├── analytics/kpis.py             # the 8 KPI views requested
├── ml/
│   ├── load_forecast.py          # XGBoost + LightGBM next-day demand forecast
│   ├── clustering.py             # DBSCAN / K-Means coverage-gap detection
│   └── scoring.py                # EV Infrastructure Need Score
├── agents/llm_agent.py           # NL question -> SQL -> stats -> chart -> LLM explanation
├── app/dashboard.py              # Streamlit demo app (this is what you show at the competition)
├── automation/monthly_pipeline.py  # end-to-end monthly refresh job
├── tests/test_pipeline.py        # smoke tests — run before your demo
└── requirements.txt
```

## 3. Quick start (competition demo, ~10 minutes)

```bash
cd ev-energy-platform
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 1. Get data. Two options:
#    a) REAL data (needs internet on the day): 
python etl/fetch_real_data.py
#    b) OFFLINE fallback (works with zero internet, same schema, realistic
#       numbers derived from published BNetzA/OPSD aggregates — use this as
#       your safety net right before you're on stage):
python etl/generate_sample_data.py

# 2. Set your Postgres connection (edit .env or export directly)
export DATABASE_URL="postgresql://postgres:yourpassword@localhost:5432/ev_energy"
createdb ev_energy   # if it doesn't exist yet

# 3. Create schema + load data
psql $DATABASE_URL -f db/schema.sql
python etl/load_to_postgres.py

# 4. Run analytics + ML once to populate derived tables
python analytics/kpis.py
python ml/load_forecast.py
python ml/clustering.py
python ml/scoring.py

# 5. Set your free Groq key (https://console.groq.com -> free API key)
export GROQ_API_KEY="gsk_..."

# 6. Launch the dashboard
streamlit run app/dashboard.py
```

Run `python tests/test_pipeline.py` beforehand — it runs the whole chain
against SQLite in a temp file so you can sanity-check everything works
even without Postgres running, in under a minute.

## 4. What to say in the demo (the "why it matters" framing)

- **Data engineering**: three heterogeneous public German sources (CSV
  register, time-series energy data, statistical REST API) unified into one
  relational model on a monthly refresh cycle — the same pattern utilities
  and public agencies use for infrastructure planning.
- **Analytics**: chargers per 100k inhabitants and fast/slow ratios are the
  actual metrics German states (Länder) and the Bundesnetzagentur itself
  publish when justifying EV subsidy allocation.
- **Forecasting**: next-day load forecasting is exactly what TSOs (like
  50Hertz, TenneT) run daily to balance grid supply — pairing it with EV
  demand growth shows where new charging load will stress the grid.
- **Clustering + Need Score**: turns raw coverage data into a ranked,
  explainable investment-priority list — the kind of output a Landkreis or
  utility planning team would actually use to decide where to put the next
  50 chargers.
- **GenAI agent**: makes all of this queryable in plain language for a
  non-technical manager, with the SQL/stats fully auditable underneath (no
  hallucinated numbers — the LLM only narrates results that were actually
  computed).

## 5. Real-world extension (say this after the demo)

This is a compressed prototype of what a state energy agency or a charging
network operator (e.g. EnBW, Ionity) would run in production: swap the
monthly BNetzA CSV pull for their internal telemetry feed, swap Destatis for
their internal demand model, and the same ETL → analytics → ML → agent
pipeline becomes a live grid-and-infrastructure planning tool.
