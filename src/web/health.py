"""Public health and version endpoints (no auth)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from src.web.cache import get_cache
from src.web.config import APP_BUILD_DATE, APP_VERSION

router = APIRouter()


@router.get("/healthz")
async def healthz() -> Any:
    """Liveness probe + current sync flag."""
    return JSONResponse(content={
        "status": "ok",
        "syncing": get_cache().syncing,
        "version": APP_VERSION,
    })


@router.get("/api/version")
async def api_version() -> Any:
    """Build version + date for the login page footer and About panel."""
    return JSONResponse(content={"version": APP_VERSION, "build_date": APP_BUILD_DATE})
