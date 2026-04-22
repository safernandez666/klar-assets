from __future__ import annotations

import csv
import hashlib
import io
import os
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, AsyncGenerator

import jwt
from fastapi import BackgroundTasks, Cookie, FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.insights import generate_insights, generate_report_text
from src.storage.repository import DeviceRepository
from src.sync_engine import SyncEngine

DB_PATH = os.getenv("DB_PATH", "data/devices.db")
AUTH_USERNAME = os.getenv("AUTH_USERNAME", "admin")
AUTH_PASSWORD = os.getenv("AUTH_PASSWORD", "")
JWT_SECRET = os.getenv("JWT_SECRET", secrets.token_hex(32))
JWT_EXPIRY_HOURS = 24
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


# ── Auth ─────────────────────────────────────────────────────────────────────

PUBLIC_PATHS = {"/auth/login", "/auth/logout", "/favicon.svg"}


def _create_token(username: str) -> str:
    return jwt.encode(
        {"sub": username, "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRY_HOURS)},
        JWT_SECRET, algorithm="HS256",
    )


def _verify_token(token: str | None) -> str | None:
    if not token:
        return None
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        return payload.get("sub")
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None


@app.middleware("http")
async def auth_middleware(request: Request, call_next: Any) -> Any:
    path = request.url.path

    # Skip auth for public paths, static assets, and if no password configured
    if not AUTH_PASSWORD:
        return await call_next(request)
    if path in PUBLIC_PATHS or path.startswith("/assets/"):
        return await call_next(request)

    token = request.cookies.get("klar_session")
    user = _verify_token(token)

    if not user:
        # API calls get 401, page requests get redirect to login
        if path.startswith("/api/"):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
        return HTMLResponse(content=_login_page(), status_code=200)

    return await call_next(request)


class LoginRequest(BaseModel):
    username: str
    password: str


@app.post("/auth/login")
async def auth_login(body: LoginRequest) -> Any:
    if not AUTH_PASSWORD:
        return JSONResponse({"error": "Auth not configured"}, status_code=400)

    # Constant-time comparison
    user_ok = secrets.compare_digest(body.username, AUTH_USERNAME)
    pass_ok = secrets.compare_digest(body.password, AUTH_PASSWORD)

    if not (user_ok and pass_ok):
        return JSONResponse({"error": "Invalid credentials"}, status_code=401)

    token = _create_token(body.username)
    response = JSONResponse({"ok": True, "user": body.username})
    response.set_cookie(
        key="klar_session",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=JWT_EXPIRY_HOURS * 3600,
        path="/",
    )
    return response


@app.post("/auth/logout")
async def auth_logout() -> Any:
    response = JSONResponse({"ok": True})
    response.delete_cookie("klar_session", path="/")
    return response


def _login_page() -> str:
    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Klar Device Normalizer — Login</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Inter',sans-serif;background:#f5f5f3;display:flex;align-items:center;justify-content:center;min-height:100vh}
.card{background:#fff;border-radius:16px;box-shadow:0 4px 24px rgba(0,0,0,0.08);padding:48px 40px;width:100%;max-width:380px}
.logo{font-size:28px;font-weight:700;letter-spacing:-0.5px;margin-bottom:4px}
.sub{font-size:13px;color:#888;margin-bottom:32px}
label{display:block;font-size:12px;font-weight:600;color:#555;margin-bottom:6px;text-transform:uppercase;letter-spacing:0.5px}
input{width:100%;padding:10px 14px;border:1.5px solid #e0e0e0;border-radius:8px;font-size:14px;font-family:inherit;outline:none;transition:border 0.2s}
input:focus{border-color:#0f0f0f}
.field{margin-bottom:20px}
button{width:100%;padding:12px;background:#0f0f0f;color:#fff;border:none;border-radius:8px;font-size:14px;font-weight:600;font-family:inherit;cursor:pointer;transition:background 0.2s}
button:hover{background:#333}
.error{color:#dc2626;font-size:12px;margin-bottom:16px;display:none}
</style>
</head>
<body>
<div class="card">
<div class="logo">Klar</div>
<div class="sub">Device Normalizer — Sign in</div>
<div class="error" id="err"></div>
<form id="form">
<div class="field"><label>Username</label><input type="text" id="user" autocomplete="username" required></div>
<div class="field"><label>Password</label><input type="password" id="pass" autocomplete="current-password" required></div>
<button type="submit">Sign in</button>
</form>
</div>
<script>
document.getElementById('form').addEventListener('submit', async(e)=>{
  e.preventDefault();
  const err=document.getElementById('err');
  err.style.display='none';
  try{
    const r=await fetch('/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({username:document.getElementById('user').value,password:document.getElementById('pass').value})});
    if(r.ok){location.reload()}
    else{const d=await r.json();err.textContent=d.error||'Login failed';err.style.display='block'}
  }catch(ex){err.textContent='Connection error';err.style.display='block'}
});
</script>
</body>
</html>"""


# ── API Routes ───────────────────────────────────────────────────────────────

@app.get("/api/devices")
async def api_devices(status: str | None = None, source: str | None = None) -> Any:
    repo = _get_repo()
    devices = repo.get_all_devices(status=status, source=source)
    return JSONResponse(content={"devices": devices})


RISK_WEIGHTS: dict[str, int] = {
    "FULLY_MANAGED": 100,
    "MANAGED": 80,
    "SERVER": 75,
    "NO_MDM": 40,
    "NO_EDR": 25,
    "IDP_ONLY": 15,
    "STALE": 5,
    "UNKNOWN": 10,
}


@app.get("/api/summary")
async def api_summary() -> Any:
    repo = _get_repo()
    summary = repo.get_summary()
    # Calculate risk score
    by_status = summary.get("by_status", {})
    total = summary.get("total", 0)
    if total > 0:
        weighted = sum(by_status.get(s, 0) * w for s, w in RISK_WEIGHTS.items())
        score = round(weighted / total, 1)
    else:
        score = 0
    summary["risk_score"] = score
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
    # Add risk score
    by_status = summary.get("by_status", {})
    total_devices = summary.get("total", 0)
    if total_devices > 0:
        weighted = sum(by_status.get(s, 0) * w for s, w in RISK_WEIGHTS.items())
        summary["risk_score"] = round(weighted / total_devices, 1)
    else:
        summary["risk_score"] = 0
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


@app.post("/api/slack/test")
async def api_slack_test() -> Any:
    """Send a test Slack alert with current data using Block Kit."""
    from src.alerts import send_slack, build_sync_blocks, _get_webhook_url
    if not _get_webhook_url():
        return JSONResponse(content={"error": "SLACK_WEBHOOK_URL not configured in .env"}, status_code=400)

    repo = _get_repo()
    devices = repo.get_all_devices()
    summary_data = repo.get_summary()
    by_status = summary_data.get("by_status", {})
    total = summary_data.get("total", 0)
    managed = (by_status.get("MANAGED", 0) + by_status.get("FULLY_MANAGED", 0))
    no_edr = sum(1 for d in devices if d.get("status") == "NO_EDR")
    no_mdm = sum(1 for d in devices if d.get("status") == "NO_MDM")

    disappeared = repo.get_recently_deleted()
    newly_stale = repo.get_newly_stale()

    blocks = build_sync_blocks(
        status_counts=by_status,
        total=total,
        managed=managed,
        sources_ok=["crowdstrike", "jumpcloud", "okta"],
        sources_failed=[],
        sync_status="test",
        disappeared=disappeared,
        newly_stale=newly_stale,
        no_edr_count=no_edr,
        no_mdm_count=no_mdm,
    )

    fallback = f"Klar Test: {total} devices, {managed} managed"
    ok = send_slack(fallback, blocks=blocks)
    return JSONResponse(content={"sent": ok, "blocks_count": len(blocks)})


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

    # Fallback to SPA index.html
    index_path = DIST_DIR / "index.html"
    if index_path.exists():
        return FileResponse(index_path)

    return JSONResponse(
        {"detail": "Frontend not built. Run: cd frontend && npm run build"},
        status_code=404,
    )
