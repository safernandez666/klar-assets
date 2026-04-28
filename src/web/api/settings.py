"""Settings endpoints — sources status and sync interval update."""
from __future__ import annotations

import os
from typing import Any

import structlog
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from src.storage.repository import DeviceRepository
from src.web.cache import get_cache
from src.web.config import (
    APP_BUILD_DATE,
    APP_URL,
    APP_VERSION,
    CS_CONFIGURED,
    JC_CONFIGURED,
    OKTA_CONFIGURED,
    OPENAI_CONFIGURED,
    SLACK_CONFIGURED,
    SYNC_INTERVAL_HOURS,
    _OKTA_OIDC_ENABLED,
)
from src.web.dependencies import get_repo

router = APIRouter()
logger = structlog.get_logger(__name__)

_sync_interval_hours = SYNC_INTERVAL_HOURS


@router.get("/api/settings")
async def api_settings(repo: DeviceRepository = Depends(get_repo)) -> Any:
    """Surface sources, last runs, and current sync interval to the Settings page."""
    last_runs = []
    try:
        conn = repo._connect()
        rows = conn.execute("SELECT * FROM sync_runs ORDER BY id DESC LIMIT 10").fetchall()
        conn.close()
        last_runs = [repo._row_to_dict(r) for r in rows]
    except Exception as exc:
        logger.warning("settings_last_runs_failed", error=str(exc))

    sources_status = {
        "crowdstrike": {"configured": CS_CONFIGURED, "name": "CrowdStrike (EDR)"},
        "jumpcloud": {"configured": JC_CONFIGURED, "name": "JumpCloud (MDM)"},
        "okta": {"configured": OKTA_CONFIGURED, "name": "Okta (IDP)"},
        "openai": {"configured": OPENAI_CONFIGURED, "name": "OpenAI (AI insights)"},
        "slack": {"configured": SLACK_CONFIGURED, "name": "Slack (Alerts)"},
        "okta_oidc": {"configured": _OKTA_OIDC_ENABLED, "name": "Okta OIDC (SSO)"},
    }

    return JSONResponse(content={
        "sync_interval_hours": _sync_interval_hours,
        "syncing": get_cache().syncing,
        "version": APP_VERSION,
        "build_date": APP_BUILD_DATE,
        "app_url": APP_URL,
        "sources": sources_status,
        "last_runs": last_runs,
    })


class SyncIntervalRequest(BaseModel):
    hours: int


@router.post("/api/settings/sync-interval")
async def api_set_sync_interval(body: SyncIntervalRequest) -> Any:
    """Update the sync cadence (persisted to env for next restart)."""
    global _sync_interval_hours
    if body.hours < 1 or body.hours > 24:
        return JSONResponse({"error": "Interval must be between 1 and 24 hours"}, status_code=400)
    _sync_interval_hours = body.hours
    try:
        # The scheduler is running in the lifespan, we can't easily access it here
        # But we store the value for the next restart
        os.environ["SYNC_INTERVAL_HOURS"] = str(body.hours)
    except Exception as exc:
        logger.warning("sync_interval_persist_failed", error=str(exc))
    return JSONResponse(content={"ok": True, "sync_interval_hours": _sync_interval_hours})
