from __future__ import annotations

import json
import os
from typing import Any

import requests
import structlog

from src.models import NormalizedDevice

logger = structlog.get_logger(__name__)

SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")


def send_slack(text: str, blocks: list[dict[str, Any]] | None = None) -> bool:
    if not SLACK_WEBHOOK_URL:
        return False
    payload: dict[str, Any] = {"text": text}
    if blocks:
        payload["blocks"] = blocks
    try:
        resp = requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=10)
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
) -> None:
    """Send a Slack alert summarizing the sync and highlighting coverage gaps."""
    if not SLACK_WEBHOOK_URL:
        return

    no_edr = [d for d in devices if "crowdstrike" not in d.sources]
    no_mdm = [d for d in devices if "jumpcloud" not in d.sources]
    idp_only = [d for d in devices if d.status == "IDP_ONLY"]

    status_counts: dict[str, int] = {}
    for d in devices:
        status_counts[d.status] = status_counts.get(d.status, 0) + 1

    # Build message
    total = len(devices)
    sources_ok = sync_result.get("sources_ok", [])
    sources_failed = sync_result.get("sources_failed", [])

    status_line = sync_result.get("status", "unknown")
    header = f":{'white_check_mark' if status_line == 'success' else 'warning'}: *Device Inventory Sync — {status_line.upper()}*"

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

    # Highlight critical gaps
    if no_edr:
        lines.append("")
        lines.append(f":rotating_light: *{len(no_edr)} devices without EDR (CrowdStrike)*")
        for d in no_edr[:5]:
            host = d.hostnames[0] if d.hostnames else "unknown"
            owner = d.owner_email or "no owner"
            lines.append(f"  • `{host}` — {owner} ({', '.join(d.sources)})")
        if len(no_edr) > 5:
            lines.append(f"  _... and {len(no_edr) - 5} more_")

    if no_mdm:
        lines.append("")
        lines.append(f":warning: *{len(no_mdm)} devices without MDM (JumpCloud)*")
        for d in no_mdm[:5]:
            host = d.hostnames[0] if d.hostnames else "unknown"
            owner = d.owner_email or "no owner"
            lines.append(f"  • `{host}` — {owner} ({', '.join(d.sources)})")
        if len(no_mdm) > 5:
            lines.append(f"  _... and {len(no_mdm) - 5} more_")

    text = "\n".join(lines)
    send_slack(text)
    logger.info("slack_alert_sent", no_edr=len(no_edr), no_mdm=len(no_mdm))
