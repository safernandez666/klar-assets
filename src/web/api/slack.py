"""Slack alert smoke test."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from src.storage.repository import DeviceRepository
from src.web.dependencies import get_repo

router = APIRouter()


@router.post("/api/slack/test")
async def api_slack_test(repo: DeviceRepository = Depends(get_repo)) -> Any:
    """Send a test Slack alert with current data using Block Kit."""
    from src.alerts import _get_webhook_url, build_sync_blocks, send_slack
    if not _get_webhook_url():
        return JSONResponse(content={"error": "SLACK_WEBHOOK_URL not configured in .env"}, status_code=400)

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

    fallback = f"Test: {total} devices, {managed} managed"
    ok = send_slack(fallback, blocks=blocks)
    return JSONResponse(content={"sent": ok, "blocks_count": len(blocks)})
