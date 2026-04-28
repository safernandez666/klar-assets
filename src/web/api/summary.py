"""Dashboard summary, diff, history, and trends endpoints."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from src.storage.repository import DeviceRepository
from src.web.cache import get_cache
from src.web.config import RISK_WEIGHTS, SYNC_INTERVAL_HOURS
from src.web.dependencies import get_repo

router = APIRouter()
logger = structlog.get_logger(__name__)


@router.get("/api/summary")
async def api_summary(repo: DeviceRepository = Depends(get_repo)) -> Any:
    """Aggregate counts + risk score + ETA for next sync."""
    cache = get_cache()
    summary = repo.get_summary()
    by_status = summary.get("by_status", {})
    total = summary.get("total", 0)
    if total > 0:
        weighted = sum(by_status.get(s, 0) * w for s, w in RISK_WEIGHTS.items())
        score = round(weighted / total, 1)
    else:
        score = 0
    summary["risk_score"] = score
    summary["syncing"] = cache.syncing
    last_sync = repo.get_last_sync_run()
    if last_sync and last_sync.get("finished_at"):
        try:
            finished = datetime.fromisoformat(str(last_sync["finished_at"]).replace("Z", "+00:00"))
            if finished.tzinfo is None:
                finished = finished.replace(tzinfo=timezone.utc)
            next_sync = finished + timedelta(hours=SYNC_INTERVAL_HOURS)
            summary["next_sync"] = next_sync.isoformat()
            summary["sync_interval_hours"] = SYNC_INTERVAL_HOURS
        except Exception as exc:
            logger.warning("next_sync_calc_failed", error=str(exc))
    return JSONResponse(content=summary)


@router.get("/api/diff")
async def api_diff(repo: DeviceRepository = Depends(get_repo)) -> Any:
    """Changes between the last two syncs."""
    devices = repo.get_all_devices()
    new_devices = repo.get_new_devices()
    disappeared = repo.get_recently_deleted()
    newly_stale = repo.get_newly_stale()

    history = repo.get_status_history(limit=2)
    status_changes: dict[str, dict[str, int]] = {}
    if len(history) >= 2:
        curr, prev = history[-1], history[-2]
        for col in ["fully_managed", "managed", "no_edr", "no_mdm", "idp_only", "stale", "server"]:
            status_key = col.upper()
            c_val = curr.get(col, 0)
            p_val = prev.get(col, 0)
            if c_val != p_val:
                status_changes[status_key] = {"previous": p_val, "current": c_val, "delta": c_val - p_val}

    def _dev_summary(d: dict) -> dict:
        return {
            "hostname": (d.get("hostnames") or ["?"])[0],
            "owner": d.get("owner_email"),
            "status": d.get("status"),
            "sources": d.get("sources", []),
        }

    return JSONResponse(content={
        "new_devices": {"count": len(new_devices), "devices": [_dev_summary(d) for d in new_devices[:20]]},
        "disappeared": {"count": len(disappeared), "devices": [_dev_summary(d) for d in disappeared[:20]]},
        "newly_stale": {"count": len(newly_stale), "devices": [_dev_summary(d) for d in newly_stale[:10]]},
        "status_changes": status_changes,
        "total_current": len(devices),
    })


@router.get("/api/history")
async def api_history(limit: int = 30, repo: DeviceRepository = Depends(get_repo)) -> Any:
    """Daily status snapshots used by the trend chart."""
    cache = get_cache()
    if cache.has("history"):
        return JSONResponse(content=cache.get("history"))
    history = repo.get_status_history(limit=limit)
    return JSONResponse(content={"history": history})


@router.get("/api/trends")
async def api_trends(repo: DeviceRepository = Depends(get_repo)) -> Any:
    """Per-status delta vs the previous snapshot."""
    cache = get_cache()
    if cache.has("trends"):
        return JSONResponse(content=cache.get("trends"))
    prev = repo.get_previous_snapshot()
    summary = repo.get_summary()
    current = summary.get("by_status", {})
    trends: dict[str, int] = {}
    if prev:
        for status_key, col_name in [
            ("FULLY_MANAGED", "fully_managed"),
            ("MANAGED", "managed"),
            ("NO_EDR", "no_edr"),
            ("NO_MDM", "no_mdm"),
            ("IDP_ONLY", "idp_only"),
            ("STALE", "stale"),
            ("SERVER", "server"),
        ]:
            old_val = prev.get(col_name, 0)
            new_val = current.get(status_key, 0)
            trends[status_key] = new_val - old_val
    return JSONResponse(content={"trends": trends, "has_previous": prev is not None})
