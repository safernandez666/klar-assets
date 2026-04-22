from __future__ import annotations

import csv
import io
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncGenerator

from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.insights import generate_insights, generate_report_text
from src.storage.repository import DeviceRepository
from src.sync_engine import SyncEngine

DB_PATH = os.getenv("DB_PATH", "data/devices.db")
DIST_DIR = Path(__file__).resolve().parents[2] / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.interval import IntervalTrigger

    sync_interval = int(os.getenv("SYNC_INTERVAL_HOURS", "6"))
    sync_on_startup = os.getenv("SYNC_ON_STARTUP", "true").lower() == "true"

    scheduler = BackgroundScheduler()
    engine = SyncEngine(DB_PATH)

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
    scheduler.start()
    if sync_on_startup:
        if SyncEngine.should_skip_startup_sync(DB_PATH):
            from structlog import get_logger
            get_logger(__name__).info("startup_sync_skipped", reason="last_sync_within_2h")
        else:
            _job()
    yield
    scheduler.shutdown()


app = FastAPI(title="Klar Device Normalizer", lifespan=lifespan)

# Serve static assets (JS/CSS bundles)
if (DIST_DIR / "assets").exists():
    app.mount("/assets", StaticFiles(directory=DIST_DIR / "assets"), name="assets")


def _get_repo() -> DeviceRepository:
    return DeviceRepository(DB_PATH)


# ── API Routes ───────────────────────────────────────────────────────────────

@app.get("/api/devices")
async def api_devices(status: str | None = None, source: str | None = None) -> Any:
    repo = _get_repo()
    devices = repo.get_all_devices(status=status, source=source)
    return JSONResponse(content={"devices": devices})


@app.get("/api/summary")
async def api_summary() -> Any:
    repo = _get_repo()
    summary = repo.get_summary()
    return JSONResponse(content=summary)


@app.get("/api/history")
async def api_history(limit: int = 30) -> Any:
    repo = _get_repo()
    history = repo.get_status_history(limit=limit)
    return JSONResponse(content={"history": history})


@app.get("/api/trends")
async def api_trends() -> Any:
    repo = _get_repo()
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


@app.get("/api/sync/last")
async def api_sync_last() -> Any:
    repo = _get_repo()
    last = repo.get_last_sync_run()
    return JSONResponse(content={"last_sync": last})


EXPORT_COLUMNS = [
    "canonical_id", "hostnames", "serial_number", "owner_email", "owner_name",
    "os_type", "status", "sources", "coverage_gaps", "confidence_score",
    "match_reason", "days_since_seen", "first_seen", "last_seen",
]


def _flatten_device(dev: dict[str, Any]) -> dict[str, str]:
    """Flatten a device dict for export — lists become semicolon-separated strings."""
    row: dict[str, str] = {}
    for col in EXPORT_COLUMNS:
        val = dev.get(col, "")
        if isinstance(val, list):
            row[col] = "; ".join(str(v) for v in val)
        elif val is None:
            row[col] = ""
        else:
            row[col] = str(val)
    return row


@app.get("/api/export/csv")
async def export_csv(status: str | None = None, source: str | None = None) -> StreamingResponse:
    repo = _get_repo()
    devices = repo.get_all_devices(status=status, source=source)
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=EXPORT_COLUMNS)
    writer.writeheader()
    for dev in devices:
        writer.writerow(_flatten_device(dev))
    buf.seek(0)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    filename = f"device_inventory_{ts}.csv"
    return StreamingResponse(
        buf,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/export/xlsx")
async def export_xlsx(status: str | None = None, source: str | None = None) -> StreamingResponse:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    repo = _get_repo()
    devices = repo.get_all_devices(status=status, source=source)

    wb = Workbook()
    ws = wb.active
    ws.title = "Device Inventory"

    # Header row
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="2B579A", end_color="2B579A", fill_type="solid")
    for col_idx, col_name in enumerate(EXPORT_COLUMNS, 1):
        cell = ws.cell(row=1, column=col_idx, value=col_name)
        cell.font = header_font
        cell.fill = header_fill

    # Data rows
    status_colors = {
        "FULLY_MANAGED": "C6EFCE",
        "MANAGED": "DFF0D8",
        "NO_EDR": "FFC7CE",
        "NO_MDM": "FFEB9C",
        "IDP_ONLY": "FFD699",
        "STALE": "D9D9D9",
        "UNKNOWN": "F2F2F2",
    }
    for row_idx, dev in enumerate(devices, 2):
        flat = _flatten_device(dev)
        for col_idx, col_name in enumerate(EXPORT_COLUMNS, 1):
            cell = ws.cell(row=row_idx, column=col_idx, value=flat[col_name])
            if col_name == "status" and flat[col_name] in status_colors:
                cell.fill = PatternFill(
                    start_color=status_colors[flat[col_name]],
                    end_color=status_colors[flat[col_name]],
                    fill_type="solid",
                )

    # Auto-width columns
    for col_idx, col_name in enumerate(EXPORT_COLUMNS, 1):
        max_len = len(col_name)
        for row_idx in range(2, min(len(devices) + 2, 52)):
            val = ws.cell(row=row_idx, column=col_idx).value or ""
            max_len = max(max_len, len(str(val)))
        ws.column_dimensions[ws.cell(row=1, column=col_idx).column_letter].width = min(max_len + 2, 50)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    filename = f"device_inventory_{ts}.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── Coverage Gaps ───────────────────────────────────────────────────────────

@app.get("/api/gaps")
async def api_gaps() -> Any:
    repo = _get_repo()
    devices = repo.get_all_devices()
    gaps: dict[str, list[dict[str, Any]]] = {
        "missing_edr": [],
        "missing_mdm": [],
        "missing_idp": [],
    }
    for dev in devices:
        dev_gaps = dev.get("coverage_gaps", [])
        summary = {
            "canonical_id": dev.get("canonical_id"),
            "hostnames": dev.get("hostnames", []),
            "owner_email": dev.get("owner_email"),
            "status": dev.get("status"),
            "sources": dev.get("sources", []),
            "days_since_seen": dev.get("days_since_seen"),
        }
        for gap in dev_gaps:
            if gap in gaps:
                gaps[gap].append(summary)
    return JSONResponse(content={
        "gaps": {k: v for k, v in gaps.items()},
        "counts": {k: len(v) for k, v in gaps.items()},
    })


@app.get("/api/insights")
async def api_insights() -> Any:
    repo = _get_repo()
    devices = repo.get_all_devices()
    summary = repo.get_summary()
    history = repo.get_status_history(limit=10)
    actions = generate_insights(devices, summary, history)
    return JSONResponse(content={"actions": actions})


@app.get("/api/report")
async def api_report() -> Any:
    repo = _get_repo()
    devices = repo.get_all_devices()
    summary = repo.get_summary()
    history = repo.get_status_history(limit=10)
    text = generate_report_text(devices, summary, history)
    return JSONResponse(content={"report": text})


@app.get("/api/report/full")
async def api_report_full() -> Any:
    """Full structured report data for PDF generation."""
    repo = _get_repo()
    devices = repo.get_all_devices()
    summary = repo.get_summary()
    history = repo.get_status_history(limit=10)
    last_sync = repo.get_last_sync_run()

    # AI executive summary
    report_text = generate_report_text(devices, summary, history)

    # Quick actions
    actions = generate_insights(devices, summary, history)

    # Helper to pick fields for PDF lists
    def device_summary(d: dict[str, Any]) -> dict[str, Any]:
        return {
            "hostname": (d.get("hostnames") or ["N/A"])[0],
            "serial": d.get("serial_number") or "N/A",
            "owner": d.get("owner_email") or "N/A",
            "os": d.get("os_type") or "N/A",
            "sources": d.get("sources", []),
            "status": d.get("status", "UNKNOWN"),
            "confidence": d.get("confidence_score", 0),
            "match_reason": d.get("match_reason", ""),
            "days_since_seen": d.get("days_since_seen"),
        }

    # Top devices per category
    no_edr = [device_summary(d) for d in devices if d.get("status") == "NO_EDR"][:15]
    no_mdm = [device_summary(d) for d in devices if d.get("status") == "NO_MDM"][:15]
    idp_only = [device_summary(d) for d in devices if d.get("status") == "IDP_ONLY"][:15]
    stale = sorted(
        [device_summary(d) for d in devices if d.get("status") == "STALE"],
        key=lambda x: x.get("days_since_seen") or 0, reverse=True,
    )[:10]

    # Unique devices with match explanation (high confidence multi-source)
    unique_matches = []
    for d in devices:
        sources = d.get("sources", [])
        if len(sources) >= 2 and (d.get("confidence_score") or 0) >= 0.6:
            unique_matches.append(device_summary(d))
    unique_matches.sort(key=lambda x: x["confidence"], reverse=True)

    # Low confidence (potential duplicates or bad matches)
    low_confidence = sorted(
        [device_summary(d) for d in devices if (d.get("confidence_score") or 0) < 0.5],
        key=lambda x: x["confidence"],
    )[:15]

    return JSONResponse(content={
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "executive_summary": report_text,
        "summary": summary,
        "last_sync": last_sync,
        "actions": actions,
        "categories": {
            "no_edr": {"title": "Devices without EDR (CrowdStrike)", "count": len([d for d in devices if d.get("status") == "NO_EDR"]), "devices": no_edr},
            "no_mdm": {"title": "Devices without MDM (JumpCloud)", "count": len([d for d in devices if d.get("status") == "NO_MDM"]), "devices": no_mdm},
            "idp_only": {"title": "IDP-Only Devices (potential shadow IT)", "count": len([d for d in devices if d.get("status") == "IDP_ONLY"]), "devices": idp_only},
            "stale": {"title": "Stale Devices (90+ days inactive)", "count": len([d for d in devices if d.get("status") == "STALE"]), "devices": stale},
        },
        "unique_matches": {"title": "Cross-source Matched Devices", "count": len(unique_matches), "devices": unique_matches[:20]},
        "low_confidence": {"title": "Low Confidence Matches (review needed)", "count": len(low_confidence), "devices": low_confidence},
    })


class TriggerResponse(BaseModel):
    message: str
    started: bool


@app.post("/api/sync/trigger")
async def api_sync_trigger(background_tasks: BackgroundTasks) -> Any:
    def _run() -> None:
        try:
            SyncEngine(DB_PATH).run()
        except Exception:
            pass

    background_tasks.add_task(_run)
    return JSONResponse(content={"message": "Sync triggered", "started": True})


# ── SPA Catch-all ────────────────────────────────────────────────────────────

@app.get("/")
async def serve_index(request: Request) -> Any:
    index_path = DIST_DIR / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return JSONResponse(
        {"detail": "Frontend not built. Run: cd frontend && npm run build"},
        status_code=404,
    )


@app.get("/{path:path}")
async def serve_spa(path: str, request: Request) -> Any:
    # API 404s should stay JSON
    if path.startswith("api/"):
        return JSONResponse({"detail": "Not found"}, status_code=404)

    # Try to serve static file directly
    file_path = DIST_DIR / path
    if file_path.exists() and file_path.is_file():
        return FileResponse(file_path)

    # Fallback to SPA index.html
    index_path = DIST_DIR / "index.html"
    if index_path.exists():
        return FileResponse(index_path)

    return JSONResponse(
        {"detail": "Frontend not built. Run: cd frontend && npm run build"},
        status_code=404,
    )
