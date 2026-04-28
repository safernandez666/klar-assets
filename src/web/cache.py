"""In-memory cache for expensive dashboard payloads, refreshed after each sync.

Replaces the legacy module-level `_cache` dict and `_syncing` bool with a
single `CacheManager` instance owned by the web layer. Module-level singleton
is exposed via `get_cache()` so routers can read state without coupling to
FastAPI app state.
"""
from __future__ import annotations

from typing import Any

import structlog

from src.insights import generate_insights
from src.storage.repository import DeviceRepository
from src.web.config import DB_PATH, RISK_WEIGHTS

logger = structlog.get_logger(__name__)


class CacheManager:
    """Holds pre-computed dashboard data and the live sync flag."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._data: dict[str, Any] = {}
        self.syncing = False

    def get(self, key: str) -> Any:
        return self._data.get(key)

    def has(self, key: str) -> bool:
        return key in self._data

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value

    def refresh(self) -> None:
        """Pre-compute expensive data so API responses are instant."""
        try:
            repo = DeviceRepository(self._db_path)
            devices = repo.get_all_devices()
            summary = repo.get_summary()
            by_status = summary.get("by_status", {})
            total_devices = summary.get("total", 0)
            if total_devices > 0:
                weighted = sum(by_status.get(s, 0) * w for s, w in RISK_WEIGHTS.items())
                summary["risk_score"] = round(weighted / total_devices, 1)
            else:
                summary["risk_score"] = 0
            history = repo.get_status_history(limit=30)
            prev = repo.get_previous_snapshot()
            trends: dict[str, int] = {}
            if prev:
                for status_key, col_name in [
                    ("FULLY_MANAGED", "fully_managed"), ("MANAGED", "managed"),
                    ("NO_EDR", "no_edr"), ("NO_MDM", "no_mdm"), ("IDP_ONLY", "idp_only"),
                    ("STALE", "stale"), ("SERVER", "server"),
                ]:
                    trends[status_key] = by_status.get(status_key, 0) - prev.get(col_name, 0)

            self._data["summary"] = summary
            self._data["trends"] = {"trends": trends, "has_previous": prev is not None}
            self._data["history"] = {"history": history}
            self._data["insights"] = {"actions": generate_insights(devices, summary, history)}
            logger.info("cache_refreshed")
        except Exception as exc:
            logger.warning("cache_refresh_failed", error=str(exc))


_instance: CacheManager | None = None


def get_cache() -> CacheManager:
    """Return the process-wide CacheManager singleton."""
    global _instance
    if _instance is None:
        _instance = CacheManager(DB_PATH)
    return _instance
