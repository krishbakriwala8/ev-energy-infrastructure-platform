"""
End-to-end monthly refresh job — the automation loop from the spec:

    Bundesnetzagentur publishes new data
              -> pipeline runs
              -> database updated
              -> KPIs recalculated
              -> ML updated
              -> management report

No Docker, no cloud scheduler needed. Two ways to run it:

1. One-off:            python automation/monthly_pipeline.py
2. Recurring (no cron): python automation/scheduler.py   (uses the `schedule`
   package to fire this every 1st of the month, works as a long-running
   process or a login-item task)

Also fine to wire into plain cron:
    0 6 1 * * cd /path/to/ev-energy-platform && venv/bin/python automation/monthly_pipeline.py
"""
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORT_DIR = ROOT / "data" / "reports"
REPORT_DIR.mkdir(parents=True, exist_ok=True)

STEPS = [
    ("Fetch real data (falls back to sample generator on failure)",
     [sys.executable, str(ROOT / "etl" / "fetch_real_data.py")]),
    ("Load into PostgreSQL", [sys.executable, str(ROOT / "etl" / "load_to_postgres.py")]),
    ("Recompute KPIs", [sys.executable, str(ROOT / "analytics" / "kpis.py")]),
    ("Retrain / re-run load forecast", [sys.executable, str(ROOT / "ml" / "load_forecast.py")]),
    ("Re-run coverage-gap clustering", [sys.executable, str(ROOT / "ml" / "clustering.py")]),
    ("Recompute EV Infrastructure Need Score", [sys.executable, str(ROOT / "ml" / "scoring.py")]),
]


def run_pipeline():
    report_lines = [f"# Monthly pipeline run — {date.today().isoformat()}\n"]
    for description, cmd in STEPS:
        print(f"\n>>> {description}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        status = "OK" if result.returncode == 0 else "FAILED"
        print(result.stdout[-2000:])
        if result.returncode != 0:
            print(result.stderr[-2000:], file=sys.stderr)
        report_lines.append(f"## {description}: {status}\n```\n{result.stdout[-1000:]}\n```\n")

    report_path = REPORT_DIR / f"management_report_{date.today().isoformat()}.md"
    report_path.write_text("\n".join(report_lines))
    print(f"\nManagement report written to {report_path}")


if __name__ == "__main__":
    run_pipeline()
