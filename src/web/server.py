"""FastAPI app factory: wires lifespan, middleware, routers, and the SPA shell.

All concerns (config, cache, auth, individual routers) live in their own
modules — this file only orchestrates them.
"""
from __future__ import annotations

import threading
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from src.sync_engine import SyncEngine
from src.web.api.controls import router as controls_router
from src.web.api.devices import router as devices_router
from src.web.api.dual_use import router as dual_use_router
from src.web.api.export import router as export_router
from src.web.api.gaps import router as gaps_router
from src.web.api.insights import router as insights_router
from src.web.api.people import router as people_router
from src.web.api.settings import router as settings_router
from src.web.api.slack import router as slack_router
from src.web.api.summary import router as summary_router
from src.web.api.sync import router as sync_router
from src.web.auth.middleware import auth_middleware
from src.web.auth.router import router as auth_router
from src.web.cache import get_cache
from src.web.config import DB_PATH, DIST_DIR, SYNC_INTERVAL_HOURS, SYNC_ON_STARTUP
from src.web.health import router as health_router

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Boot the background sync scheduler and prime the cache."""
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.interval import IntervalTrigger

    scheduler = BackgroundScheduler()
    engine = SyncEngine(DB_PATH)
    cache = get_cache()

    def _job() -> None:
        cache.syncing = True
        try:
            engine.run()
            cache.refresh()
        except Exception as exc:
            logger.warning("scheduled_sync_failed", error=str(exc))
        finally:
            cache.syncing = False

    scheduler.add_job(
        _job,
        trigger=IntervalTrigger(hours=SYNC_INTERVAL_HOURS),
        id="device_sync",
        replace_existing=True,
    )
    scheduler.start()
    if SYNC_ON_STARTUP:
        if SyncEngine.should_skip_startup_sync(DB_PATH):
            logger.info("startup_sync_skipped", reason="last_sync_within_2h")
            cache.refresh()
        else:
            # Run startup sync in background — don't block server startup
            logger.info("startup_sync_background")
            threading.Thread(target=_job, daemon=True).start()
    else:
        cache.refresh()
    yield
    scheduler.shutdown()


app = FastAPI(title="Device Normalizer", lifespan=lifespan)

# Serve static assets (JS/CSS bundles)
if (DIST_DIR / "assets").exists():
    app.mount("/assets", StaticFiles(directory=DIST_DIR / "assets"), name="assets")

# Auth runs on every request before routes resolve.
app.middleware("http")(auth_middleware)

# Register routers (order is irrelevant for non-overlapping paths).
app.include_router(health_router)
app.include_router(auth_router)
app.include_router(settings_router)
app.include_router(devices_router)
app.include_router(summary_router)
app.include_router(sync_router)
app.include_router(export_router)
app.include_router(gaps_router)
app.include_router(people_router)
app.include_router(dual_use_router)
app.include_router(insights_router)
app.include_router(slack_router)
app.include_router(controls_router)


# ── SPA Catch-all (must be last) ─────────────────────────────────────────────

# index.html references content-hashed JS/CSS bundles. Browsers cache it
# aggressively by default, but the next deploy generates new bundle names —
# so a cached index.html points users at chunks that no longer exist on the
# server and the page goes blank with a 404. Force revalidation on every
# load. The hashed assets under /assets/ are still safe to cache forever.
_INDEX_NO_CACHE = {
    "Cache-Control": "no-store, no-cache, must-revalidate",
    "Pragma": "no-cache",
    "Expires": "0",
}


@app.get("/")
async def serve_index(request: Request) -> Any:
    """Serve the React index page."""
    index_path = DIST_DIR / "index.html"
    if index_path.exists():
        return FileResponse(index_path, headers=_INDEX_NO_CACHE)
    return JSONResponse(
        {"detail": "Frontend not built. Run: cd frontend && npm run build"},
        status_code=404,
    )


@app.get("/{path:path}")
async def serve_spa(path: str, request: Request) -> Any:
    """Fall through to static files or the SPA shell for client-side routes."""
    # API 404s should stay JSON
    if path.startswith("api/"):
        return JSONResponse({"detail": "Not found"}, status_code=404)

    # Try to serve static file directly
    # Resolve to absolute path and verify it stays within DIST_DIR to prevent
    # path traversal (e.g. GET /../../etc/passwd).  resolve() follows .. and
    # symlinks; we check the canonical prefix before serving the file.
    file_path = (DIST_DIR / path).resolve()
    try:
        file_path.relative_to(DIST_DIR.resolve())
    except ValueError:
        return JSONResponse({"detail": "Not found"}, status_code=404)
    if file_path.exists() and file_path.is_file():
        return FileResponse(file_path)

    # Fallback to SPA index.html — also must skip cache for the same reason.
    index_path = DIST_DIR / "index.html"
    if index_path.exists():
        return FileResponse(index_path, headers=_INDEX_NO_CACHE)

    return JSONResponse(
        {"detail": "Frontend not built. Run: cd frontend && npm run build"},
        status_code=404,
    )
