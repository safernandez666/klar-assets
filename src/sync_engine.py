from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog

from src.collectors.base import CollectResult
from src.collectors.crowdstrike import CrowdStrikeCollector
from src.collectors.jumpcloud import JumpCloudCollector
from src.collectors.okta import OktaCollector
from src.models import NormalizedDevice, RawDevice
from src.normalizer.deduplicator import Deduplicator
from src.normalizer.enricher import Enricher
from src.alerts import alert_after_sync
from src.storage.repository import DeviceRepository

logger = structlog.get_logger(__name__)


class SyncEngine:
    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = db_path or os.getenv("DB_PATH", "data/devices.db")
        self.repo = DeviceRepository(self.db_path)
        self.deduplicator = Deduplicator()
        self.enricher = Enricher()
        self.collectors = [
            CrowdStrikeCollector(),
            OktaCollector(),
            JumpCloudCollector(),
        ]

    @staticmethod
    def should_skip_startup_sync(db_path: str | None = None) -> bool:
        """Skip startup sync if the last successful run finished < 2 hours ago."""
        path = db_path or os.getenv("DB_PATH", "data/devices.db")
        repo = DeviceRepository(path)
        last = repo.get_last_sync_run()
        if not last:
            return False
        if last.get("status") != "success":
            return False
        finished = last.get("finished_at")
        if not finished:
            return False
        try:
            finished_dt = datetime.fromisoformat(str(finished).replace("Z", "+00:00"))
            if finished_dt.tzinfo is None:
                finished_dt = finished_dt.replace(tzinfo=timezone.utc)
            return datetime.now(timezone.utc) - finished_dt < timedelta(hours=2)
        except Exception:
            return False

    def run(self) -> dict[str, Any]:
        started_at = datetime.now(timezone.utc).isoformat()
        all_raw: list[RawDevice] = []
        sources_ok: list[str] = []
        sources_failed: list[str] = []

        with ThreadPoolExecutor(max_workers=len(self.collectors)) as executor:
            futures = {
                executor.submit(collector.safe_collect): collector.source_name
                for collector in self.collectors
            }
            for future in as_completed(futures):
                source_name = futures[future]
                try:
                    result: CollectResult = future.result()
                    all_raw.extend(result.devices)
                    if result.success:
                        sources_ok.append(source_name)
                    else:
                        sources_failed.append(source_name)
                except Exception as exc:
                    logger.error("collector_failed", source=source_name, error=str(exc))
                    sources_failed.append(source_name)

        normalized = self.deduplicator.deduplicate(all_raw)
        enriched = self.enricher.enrich(normalized)

        # Assign canonical IDs if empty
        for dev in enriched:
            if not dev.canonical_id:
                import uuid
                dev.canonical_id = str(uuid.uuid4())

        self.repo.upsert_devices(enriched)

        final_count = len(enriched)
        duplicates_removed = len(all_raw) - final_count

        run = {
            "started_at": started_at,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "status": "success" if not sources_failed else "partial",
            "total_raw_devices": len(all_raw),
            "duplicates_removed": duplicates_removed if duplicates_removed > 0 else 0,
            "final_count": final_count,
            "sources_ok": sources_ok,
            "sources_failed": sources_failed,
        }
        sync_run_id = self.repo.save_sync_run(run)
        logger.info("sync_completed", **run)

        # Save status snapshot for historical tracking
        status_counts: dict[str, int] = {}
        for dev in enriched:
            status_counts[dev.status] = status_counts.get(dev.status, 0) + 1
        self.repo.save_status_snapshot(sync_run_id, status_counts)

        # Detect disappeared and newly stale devices
        disappeared = self.repo.get_recently_deleted()
        newly_stale = self.repo.get_newly_stale()
        if disappeared:
            logger.warning("devices_disappeared", count=len(disappeared),
                          devices=[((d.get("hostnames") or ["?"])[0]) for d in disappeared[:5]])
        if newly_stale:
            logger.warning("devices_newly_stale", count=len(newly_stale))

        # Send Slack alert if webhook is configured
        try:
            alert_after_sync(enriched, run, disappeared=disappeared, newly_stale=newly_stale)
        except Exception as exc:
            logger.warning("alert_failed", error=str(exc))

        return run
