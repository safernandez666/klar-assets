"""Reconcile the JumpCloud console `displayName` for renamed endpoints.

Background
----------
After an endpoint is renamed (via ``scutil --set ComputerName`` on macOS or
``Rename-Computer`` on Windows), the JumpCloud agent re-publishes the
OS-level ``hostname`` on its next inventory cycle. **But** the JumpCloud
console's ``displayName`` field — the one the search bar uses — is set
once at agent enrollment and is never refreshed by the agent. That stale
``displayName`` is why a search for ``KLR-MXM-DG27`` finds nothing even
though the device has already been renamed.

This module bridges the gap. After every successful sync, it:

1. Looks at every normalized device that is sourced from JumpCloud and
   whose canonical hostname starts with ``KLR-`` (our standardized
   naming convention).
2. Compares that hostname against the ``displayName`` we already pulled
   from JC during the sync (cached in ``RawDevice.raw_data``).
3. PUTs the corrected ``displayName`` for every device whose value drifted.

Safety
------
- Skipped entirely when ``JC_API_KEY`` is unset.
- Skipped entirely when ``JC_RECONCILE_DISPLAYNAMES`` is set to ``"0"``.
- Hard cap on the number of PUTs per run (``JC_RECONCILE_MAX_UPDATES``,
  default 50) to prevent a runaway after a bulk-rename mistake.
- Best-effort: any HTTP failure is logged but never raised — the sync
  result must not depend on JC reachability for an out-of-band step.
"""
from __future__ import annotations

import os
from typing import Iterable

import requests
import structlog

from src.models import NormalizedDevice

logger = structlog.get_logger(__name__)

JC_API = "https://console.jumpcloud.com/api"
KLR_PREFIX = "KLR-"
DEFAULT_MAX_UPDATES = 50


def _canonical_klr_hostname(device: NormalizedDevice) -> str | None:
    """Return the first hostname starting with ``KLR-``, or ``None``."""
    for h in device.hostnames:
        if isinstance(h, str) and h.startswith(KLR_PREFIX):
            return h
    return None


def find_drift(
    devices: Iterable[NormalizedDevice],
    jc_displaynames: dict[str, str],
) -> list[tuple[str, str, str, str]]:
    """Return ``[(jc_id, current_displayName, target_name, canonical_id)]``
    for every JC-sourced device whose ``displayName`` disagrees with the
    canonical KLR-* hostname."""
    drift: list[tuple[str, str, str, str]] = []
    for d in devices:
        if "jumpcloud" not in d.sources:
            continue
        jc_id = d.source_ids.get("jumpcloud")
        if not jc_id:
            continue
        target = _canonical_klr_hostname(d)
        if not target:
            continue
        current = (jc_displaynames.get(jc_id) or "").strip()
        if current == target:
            continue
        drift.append((jc_id, current, target, d.canonical_id))
    return drift


def reconcile_displaynames(
    devices: Iterable[NormalizedDevice],
    jc_displaynames: dict[str, str],
    *,
    api_key: str | None = None,
    dry_run: bool = False,
    max_updates: int | None = None,
) -> dict:
    """Run the full scan + PUT pass.

    Returns a summary dict with the keys ``scanned``, ``drifted``, ``updated``,
    ``failed``, ``capped``, ``dry_run``, and optionally ``reason`` when a guard
    short-circuited the run."""
    devs = list(devices)
    api_key = api_key if api_key is not None else os.getenv("JC_API_KEY", "")
    enabled = os.getenv("JC_RECONCILE_DISPLAYNAMES", "1") != "0"
    if max_updates is None:
        try:
            max_updates = int(os.getenv("JC_RECONCILE_MAX_UPDATES", str(DEFAULT_MAX_UPDATES)))
        except ValueError:
            max_updates = DEFAULT_MAX_UPDATES

    base = {"scanned": len(devs), "drifted": 0, "updated": 0,
            "failed": 0, "capped": 0, "dry_run": dry_run}

    if not enabled:
        logger.info("jc_reconcile_disabled")
        return {**base, "reason": "disabled"}
    if not api_key:
        logger.info("jc_reconcile_skipped_no_api_key")
        return {**base, "reason": "no_api_key"}

    drift = find_drift(devs, jc_displaynames)
    base["drifted"] = len(drift)

    if not drift:
        logger.info("jc_reconcile_no_drift", scanned=len(devs))
        return base

    capped = max(0, len(drift) - max_updates)
    work = drift[:max_updates]
    base["capped"] = capped
    if capped:
        logger.warning("jc_reconcile_capped",
                       drifted=len(drift), max_updates=max_updates, capped=capped)

    if dry_run:
        for jc_id, current, target, canonical_id in work:
            logger.info("jc_reconcile_drift",
                        jc_id=jc_id, current=current, target=target,
                        canonical_id=canonical_id, dry_run=True)
        return base

    session = requests.Session()
    session.headers.update({
        "x-api-key": api_key,
        "Accept": "application/json",
        "Content-Type": "application/json",
    })

    updated = failed = 0
    for jc_id, current, target, canonical_id in work:
        try:
            resp = session.put(f"{JC_API}/systems/{jc_id}",
                               json={"displayName": target}, timeout=30)
            resp.raise_for_status()
            updated += 1
            logger.info("jc_displayname_updated",
                        jc_id=jc_id, current=current, target=target,
                        canonical_id=canonical_id)
        except requests.RequestException as exc:
            failed += 1
            logger.warning("jc_displayname_update_failed",
                           jc_id=jc_id, target=target, error=str(exc))

    base["updated"] = updated
    base["failed"] = failed
    logger.info("jc_reconcile_summary", **base)
    return base


def jc_displaynames_from_raw(raw_devices: Iterable) -> dict[str, str]:
    """Helper: extract ``{jc_id: displayName}`` from ``RawDevice`` items.

    Pulled from ``raw_data`` (where the JC collector dumps the full system
    payload), so we avoid an extra round-trip per device just to learn what
    the current ``displayName`` is."""
    out: dict[str, str] = {}
    for r in raw_devices:
        if getattr(r, "source", None) != "jumpcloud":
            continue
        sid = getattr(r, "source_device_id", None)
        if not sid:
            continue
        raw = getattr(r, "raw_data", {}) or {}
        out[sid] = (raw.get("displayName") or "").strip()
    return out
