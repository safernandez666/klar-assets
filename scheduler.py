from __future__ import annotations

import os
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from src.sync_engine import SyncEngine


def create_scheduler(db_path: str | None = None) -> BackgroundScheduler:
    sync_interval = int(os.getenv("SYNC_INTERVAL_HOURS", "6"))
    scheduler = BackgroundScheduler()
    engine = SyncEngine(db_path)

    def _job() -> None:
        try:
            engine.run()
        except Exception:
            pass

    scheduler.add_job(
        _job,
        trigger=IntervalTrigger(hours=sync_interval),
        id="device_sync",
        replace_existing=True,
    )
    return scheduler
