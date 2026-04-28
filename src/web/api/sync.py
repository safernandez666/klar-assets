"""Sync status and on-demand sync trigger."""
from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends
from fastapi.responses import JSONResponse

from src.storage.repository import DeviceRepository
from src.sync_engine import SyncEngine
from src.web.cache import get_cache
from src.web.config import DB_PATH
from src.web.dependencies import get_repo

router = APIRouter()
logger = structlog.get_logger(__name__)


@router.get("/api/sync/last")
async def api_sync_last(repo: DeviceRepository = Depends(get_repo)) -> Any:
    """Return metadata about the most recent sync run."""
    last = repo.get_last_sync_run()
    return JSONResponse(content={"last_sync": last})


@router.post("/api/sync/trigger")
async def api_sync_trigger(background_tasks: BackgroundTasks) -> Any:
    """Kick off a fresh sync in a background task."""
    cache = get_cache()

    def _run() -> None:
        try:
            SyncEngine(DB_PATH).run()
            cache.refresh()
        except Exception as exc:
            logger.warning("manual_sync_failed", error=str(exc))

    background_tasks.add_task(_run)
    return JSONResponse(content={"message": "Sync triggered", "started": True})
