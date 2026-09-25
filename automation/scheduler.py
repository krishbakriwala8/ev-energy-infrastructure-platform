"""
Optional long-running scheduler (alternative to cron) — fires the monthly
pipeline automatically. Just `python automation/scheduler.py &` and leave it
running; no Docker, no external scheduler service.

    pip install schedule
"""
import time

import schedule

from monthly_pipeline import run_pipeline

# Bundesnetzagentur publishes its updated register on the 1st of each month
schedule.every().day.at("06:00").do(lambda: run_pipeline() if time.strftime("%d") == "01" else None)

if __name__ == "__main__":
    print("Scheduler running. Pipeline will fire on the 1st of each month at 06:00.")
    while True:
        schedule.run_pending()
        time.sleep(3600)
