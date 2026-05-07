"""On-demand JumpCloud refresh endpoint.

Re-collects from JumpCloud only (skipping CrowdStrike + Okta for speed),
patches the new hostnames into the existing device snapshot, runs the
displayName reconciler with the freshly-collected raw data, and refreshes
the cache so the UI shows the new state immediately.

Use case: right after renaming an endpoint, click "Refresh JumpCloud" in
Settings → ~15 seconds → both the JC console search AND the app's UI
reflect the new name. Cheaper than a full ``Sync Now`` (33s) because it
skips the two slowest collectors when only JC data has changed.
"""
from __future__ import annotations

import os
from typing import Any

import structlog
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from src.collectors.jumpcloud import JumpCloudCollector
from src.jumpcloud_reconciler import (
    KLR_PREFIX,
    jc_displaynames_from_raw,
    reconcile_displaynames,
)
from src.models import NormalizedDevice
from src.storage.repository import DeviceRepository
from src.web.cache import get_cache
from src.web.dependencies import get_repo

router = APIRouter()
logger = structlog.get_logger(__name__)


def _row_to_normalized(row: dict[str, Any]) -> NormalizedDevice | None:
    """Build a minimal NormalizedDevice from a repo row.

    Only populates the fields ``reconcile_displaynames`` actually reads;
    everything else falls back to model defaults. Used for in-memory drift
    detection only — the row in SQLite stays untouched.
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
async def api_jc_refresh(
    repo: DeviceRepository = Depends(get_repo),
) -> Any:
    """Quick JumpCloud refresh: re-collect, merge into DB, reconcile, refresh cache.

    Steps:
      1. ``JumpCloudCollector.safe_collect()`` — fresh pull from JC (~13s).
      2. For each existing device matched by serial: prepend JC's new
         hostname to the device's hostnames list, refresh
         ``source_ids[jumpcloud]`` and ``last_seen``. We don't drop stale
         entries — the next full ``Sync Now`` (cron or manual) handles
         cleanup. Old hostnames stay as secondary entries; the new one
         shows first because it's at index 0.
      3. ``reconcile_displaynames`` — uses ``raw_data.displayName`` from
         the fresh collection (no extra HTTP).
      4. Refresh in-memory cache so the UI redraws immediately.

    Returns a summary dict including both the reconciler counts and the
    refresh counts, so the UI can toast something meaningful regardless
    of whether anything actually changed.
    """
    api_key = os.getenv("JC_API_KEY", "")
    if not api_key:
        return JSONResponse(
            status_code=503,
            content={"error": "JC_API_KEY not configured", "scanned": 0,
                     "drifted": 0, "updated": 0, "failed": 0, "capped": 0,
                     "dry_run": False, "jc_collected": 0,
                     "devices_refreshed": 0},
        )

    # ── 1. Fresh JC collection ────────────────────────────────────────
    collector = JumpCloudCollector()
    result = collector.safe_collect()
    if not result.success:
        # Older CollectResult shapes don't include `error`; surface what we can.
        err_detail = getattr(result, "error", None) or "unknown"
        return JSONResponse(
            status_code=502,
            content={"error": f"JumpCloud collection failed: {err_detail}",
                     "jc_collected": 0, "devices_refreshed": 0,
                     "scanned": 0, "drifted": 0, "updated": 0,
                     "failed": 0, "capped": 0, "dry_run": False},
        )
    fresh_jc = result.devices

    fresh_by_serial: dict[str, Any] = {}
    for raw in fresh_jc:
        sn = (raw.serial_number or "").strip().upper()
        if sn:
            fresh_by_serial[sn] = raw

    # ── 2. Patch existing rows with the freshly observed JC hostname ──
    rows = repo.get_all_devices()
    if not isinstance(rows, list):
        rows = []

    devices_refreshed = 0
    new_hostnames_seen = 0
    for row in rows:
        sn = (row.get("serial_number") or "").strip().upper()
        if not sn or sn not in fresh_by_serial:
            continue

        fresh = fresh_by_serial[sn]
        new_hostname = (fresh.hostname or "").strip()
        if not new_hostname:
            continue

        existing_hostnames = list(row.get("hostnames") or [])
        # Prepend the fresh hostname; dedupe preserving the new-first order.
        merged: list[str] = [new_hostname]
        for h in existing_hostnames:
            if h and h not in merged:
                merged.append(h)

        # Refresh source_ids so JC's _id is current.
        sids = dict(row.get("source_ids") or {})
        sids["jumpcloud"] = fresh.source_device_id

        repo.update_device_jc_view(
            row["canonical_id"],
            hostnames=merged,
            source_ids=sids,
            last_seen=fresh.last_seen,
        )
        devices_refreshed += 1
        if new_hostname not in existing_hostnames:
            new_hostnames_seen += 1

    # ── 3. Reconcile displayNames using the freshly collected raw_data ─
    rows_after = repo.get_all_devices()
    if not isinstance(rows_after, list):
        rows_after = []

    devices: list[NormalizedDevice] = []
    for row in rows_after:
        d = _row_to_normalized(row)
        if d is not None:
            devices.append(d)

    candidates = sum(
        1 for d in devices
        if "jumpcloud" in d.sources
        and d.source_ids.get("jumpcloud")
        and any(isinstance(h, str) and h.startswith(KLR_PREFIX) for h in d.hostnames)
    )

    jc_displaynames = jc_displaynames_from_raw(fresh_jc)
    summary = reconcile_displaynames(devices, jc_displaynames, api_key=api_key)

    # ── 4. Refresh cache so the UI sees the new state immediately ─────
    try:
        get_cache().refresh()
    except Exception as exc:
        # Cache failures shouldn't poison the response — log and continue.
        logger.warning("jc_quick_refresh_cache_refresh_failed", error=str(exc))

    summary["jc_collected"] = len(fresh_jc)
    summary["devices_refreshed"] = devices_refreshed
    summary["new_hostnames"] = new_hostnames_seen
    summary["candidates"] = candidates

    logger.info("jc_quick_refresh_done", **summary)
    return summary
