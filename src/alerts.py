from __future__ import annotations

import os
from typing import Any

import requests
import structlog

from src.models import NormalizedDevice

logger = structlog.get_logger(__name__)

def _get_webhook_url() -> str:
    return os.getenv("SLACK_WEBHOOK_URL", "")


def send_slack(text: str, blocks: list[dict[str, Any]] | None = None) -> bool:
    if not _get_webhook_url():
        return False
    payload: dict[str, Any] = {"text": text}
    if blocks:
        payload["blocks"] = blocks
    try:
        resp = requests.post(_get_webhook_url(), json=payload, timeout=10)
        if resp.status_code != 200:
            logger.warning("slack_send_failed", status=resp.status_code, body=resp.text)
            return False
        return True
    except Exception as exc:
        logger.error("slack_send_error", error=str(exc))
        return False


def alert_after_sync(
    devices: list[NormalizedDevice],
    sync_result: dict[str, Any],
    disappeared: list[dict[str, Any]] | None = None,
    newly_stale: list[dict[str, Any]] | None = None,
) -> None:
    """Send a Slack alert summarizing the sync, gaps, and disappearances."""
    if not _get_webhook_url():
        return

    no_edr = [d for d in devices if "crowdstrike" not in d.sources]
    no_mdm = [d for d in devices if "jumpcloud" not in d.sources]

    status_counts: dict[str, int] = {}
    for d in devices:
        status_counts[d.status] = status_counts.get(d.status, 0) + 1

    total = len(devices)
    sources_ok = sync_result.get("sources_ok", [])
    sources_failed = sync_result.get("sources_failed", [])

    status_line = sync_result.get("status", "unknown")
    header = f":{'white_check_mark' if status_line == 'success' else 'warning'}: *Klar Device Normalizer — Sync {status_line.upper()}*"

    lines = [
        header,
        f"Total devices: *{total}*",
        f"Sources OK: {', '.join(sources_ok) or 'none'}",
    ]
    if sources_failed:
        lines.append(f":x: Sources failed: {', '.join(sources_failed)}")

    lines.append("")
    lines.append("*Status breakdown:*")
    for status, count in sorted(status_counts.items()):
        lines.append(f"  • {status}: {count}")

    # ── Disappeared devices (were managed, now gone) ────────────────
    if disappeared:
        lines.append("")
        lines.append(f":rotating_light: *{len(disappeared)} managed devices DISAPPEARED*")
        lines.append("_These devices were MANAGED/FULLY_MANAGED in the previous sync but are no longer reporting:_")
        for d in disappeared[:8]:
            host = (d.get("hostnames") or ["unknown"])[0]
            owner = d.get("owner_email") or "no owner"
            sources = ", ".join(d.get("sources") or [])
            lines.append(f"  • `{host}` — {owner} (was: {sources})")
        if len(disappeared) > 8:
            lines.append(f"  _... and {len(disappeared) - 8} more_")

    # ── Newly stale devices ─────────────────────────────────────────
    if newly_stale:
        lines.append("")
        lines.append(f":hourglass: *{len(newly_stale)} devices just went STALE (>90 days)*")
        for d in newly_stale[:5]:
            host = (d.get("hostnames") or ["unknown"])[0]
            days = d.get("days_since_seen") or "?"
            lines.append(f"  • `{host}` — inactive for {days} days")
        if len(newly_stale) > 5:
            lines.append(f"  _... and {len(newly_stale) - 5} more_")

    # ── Coverage gaps ───────────────────────────────────────────────
    if no_edr:
        lines.append("")
        lines.append(f":warning: *{len(no_edr)} devices without EDR (CrowdStrike)*")
        for d in no_edr[:5]:
            host = d.hostnames[0] if d.hostnames else "unknown"
            owner = d.owner_email or "no owner"
            lines.append(f"  • `{host}` — {owner}")
        if len(no_edr) > 5:
            lines.append(f"  _... and {len(no_edr) - 5} more_")

    text = "\n".join(lines)
    send_slack(text)
    logger.info("slack_alert_sent", no_edr=len(no_edr), disappeared=len(disappeared or []), newly_stale=len(newly_stale or []))
