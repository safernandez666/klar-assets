"""On-demand JumpCloud displayName reconciliation endpoint.

Faster alternative to a full ``Sync Now`` for the case where the only
thing you need is to push the current canonical ``KLR-*`` hostname into
JC's console ``displayName`` field. Instead of re-collecting from every
source (33s), this re-uses the already-persisted device list and only
talks to JumpCloud's API.

Typical use: right after renaming an endpoint, click "Reconcile JC
displayNames" in the Settings page → 2-5s → done, the console search
finds the device by its new name without waiting for the next 6h sync.
"""
from __future__ import annotations

import os
from typing import Any

import structlog
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from src.jumpcloud_reconciler import (
    KLR_PREFIX,
    fetch_jc_displaynames_live,
    reconcile_displaynames,
)
from src.models import NormalizedDevice
from src.storage.repository import DeviceRepository
from src.web.dependencies import get_repo

router = APIRouter()
logger = structlog.get_logger(__name__)


def _row_to_normalized(row: dict[str, Any]) -> NormalizedDevice | None:
    """Build a minimal ``NormalizedDevice`` from a repo row.

    Only the fields the reconciler actually reads need to be populated;
    everything else falls back to model defaults. Returns ``None`` if the
    row is too malformed to even attempt construction.
    """
    try:
        return NormalizedDevice(
            canonical_id=row.get("canonical_id") or "",
            hostnames=row.get("hostnames") or [],
            sources=row.get("sources") or [],
            source_ids=row.get("source_ids") or {},
        )
    except Exception:
        return None


@router.post("/api/jumpcloud/reconcile-displaynames")
async def api_jc_reconcile_displaynames(
    repo: DeviceRepository = Depends(get_repo),
) -> Any:
    """Push canonical ``KLR-*`` hostnames into JC's ``displayName`` field.

    Read flow:
      1. Pull the current device list from SQLite (no source re-collect).
      2. Pick the JC-sourced devices with a ``KLR-*`` hostname.
      3. GET ``/api/systems/{id}`` for each to learn their current displayName.
      4. PUT corrected displayNames where they drifted.

    Returns the same summary dict used by the in-sync reconciler, so the
    UI can display it consistently:
        {scanned, drifted, updated, failed, capped, dry_run}
    """
    api_key = os.getenv("JC_API_KEY", "")
    if not api_key:
        return JSONResponse(
            status_code=503,
            content={"error": "JC_API_KEY not configured", "scanned": 0,
                     "drifted": 0, "updated": 0, "failed": 0, "capped": 0,
                     "dry_run": False},
        )

    rows = repo.get_all_devices()
    if not isinstance(rows, list):
        # Defensive — get_all_devices returns a dict only when paginated,
        # which we don't ask for here.
        rows = []

    devices: list[NormalizedDevice] = []
    for row in rows:
        d = _row_to_normalized(row)
        if d is not None:
            devices.append(d)

    klr_jc_ids: list[str] = []
    for d in devices:
        if "jumpcloud" not in d.sources:
            continue
        sid = d.source_ids.get("jumpcloud")
        if not sid:
            continue
        if not any(isinstance(h, str) and h.startswith(KLR_PREFIX) for h in d.hostnames):
            continue
        klr_jc_ids.append(sid)

    logger.info("jc_reconcile_on_demand_start",
                total_devices=len(devices), klr_jc_candidates=len(klr_jc_ids))

    jc_displaynames = fetch_jc_displaynames_live(klr_jc_ids, api_key=api_key)
    summary = reconcile_displaynames(devices, jc_displaynames, api_key=api_key)
    summary["candidates"] = len(klr_jc_ids)

    logger.info("jc_reconcile_on_demand_done", **summary)
    return summary
