from __future__ import annotations

import os
from datetime import datetime, timezone
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


def _blocks_header(text: str) -> dict[str, Any]:
    return {"type": "header", "text": {"type": "plain_text", "text": text, "emoji": True}}


def _blocks_section(text: str) -> dict[str, Any]:
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def _blocks_fields(fields: list[str]) -> dict[str, Any]:
    return {"type": "section", "fields": [{"type": "mrkdwn", "text": f} for f in fields]}


def _blocks_divider() -> dict[str, Any]:
    return {"type": "divider"}


def _blocks_context(texts: list[str]) -> dict[str, Any]:
    return {"type": "context", "elements": [{"type": "mrkdwn", "text": t} for t in texts]}


RISK_WEIGHTS: dict[str, int] = {
    "FULLY_MANAGED": 100, "MANAGED": 80, "SERVER": 75,
    "NO_MDM": 40, "NO_EDR": 25, "IDP_ONLY": 15, "STALE": 5, "UNKNOWN": 10,
}


def build_sync_blocks(
    status_counts: dict[str, int],
    total: int,
    managed: int,
    sources_ok: list[str],
    sources_failed: list[str],
    sync_status: str,
    disappeared: list[dict[str, Any]] | None = None,
    newly_stale: list[dict[str, Any]] | None = None,
    new_devices: list[dict[str, Any]] | None = None,
    dual_use: list[dict[str, Any]] | None = None,
    no_edr_count: int = 0,
    no_mdm_count: int = 0,
) -> list[dict[str, Any]]:
    """Build Slack Block Kit blocks for a sync report."""
    pct = round(managed / total * 100) if total else 0
    icon = ":white_check_mark:" if sync_status == "success" else ":warning:"

    # Risk score
    risk_score = 0
    if total > 0:
        weighted = sum(status_counts.get(s, 0) * w for s, w in RISK_WEIGHTS.items())
        risk_score = round(weighted / total, 1)
    rs_emoji = ":large_green_circle:" if risk_score >= 80 else ":large_yellow_circle:" if risk_score >= 60 else ":large_orange_circle:" if risk_score >= 40 else ":red_circle:"
    rs_label = "Excellent" if risk_score >= 85 else "Good" if risk_score >= 70 else "Fair" if risk_score >= 55 else "At Risk" if risk_score >= 40 else "Critical"

    blocks: list[dict[str, Any]] = [
        _blocks_header(f"{icon} Klar Device Normalizer"),
        _blocks_section(f"Sync completed — *{sync_status.upper()}* — <!date^{int(datetime.now(timezone.utc).timestamp())}^{{date_short_pretty}} {{time}}|{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}>"),
        _blocks_divider(),
        _blocks_section(
            f"{rs_emoji}  *Risk Score:*  `{risk_score}`  —  *{rs_label}*\n\n"
            f":computer:  *Fleet:*  `{total}` devices\n\n"
            f":shield:  *Managed (MDM+EDR):*  `{managed}` of `{total}`  —  *{pct}%* coverage\n\n"
            f":red_circle:  *Without EDR:*  `{no_edr_count}` devices need CrowdStrike\n\n"
            f":large_orange_circle:  *Without MDM:*  `{no_mdm_count}` devices need JumpCloud"
        ),
        _blocks_divider(),
    ]

    # Status breakdown as compact text
    status_line = "  ".join(f"`{s}` {c}" for s, c in sorted(status_counts.items()))
    blocks.append(_blocks_section(f"*Status breakdown*\n{status_line}"))

    # Sources
    src_ok = "  ".join(f":large_green_circle: {s}" for s in sources_ok)
    src_fail = "  ".join(f":red_circle: {s}" for s in sources_failed) if sources_failed else ""
    src_text = src_ok
    if src_fail:
        src_text += f"\n{src_fail}"
    blocks.append(_blocks_section(f"*Sources*\n{src_text}"))

    # Disappeared
    if disappeared:
        blocks.append(_blocks_divider())
        device_list = "\n".join(
            f":rotating_light: `{(d.get('hostnames') or ['?'])[0]}` — {d.get('owner_email') or 'no owner'}"
            for d in disappeared[:5]
        )
        more = f"\n_+ {len(disappeared) - 5} more_" if len(disappeared) > 5 else ""
        blocks.append(_blocks_section(f"*:rotating_light: {len(disappeared)} Managed Devices Disappeared*\n{device_list}{more}"))

    # Newly stale
    if newly_stale:
        blocks.append(_blocks_divider())
        stale_list = "\n".join(
            f":hourglass: `{(d.get('hostnames') or ['?'])[0]}` — {d.get('days_since_seen', '?')} days"
            for d in newly_stale[:5]
        )
        blocks.append(_blocks_section(f"*:hourglass: {len(newly_stale)} Devices Went Stale*\n{stale_list}"))

    # New devices
    if new_devices:
        blocks.append(_blocks_divider())
        # Separate risky (no EDR/MDM) from normal
        risky_new = [d for d in new_devices if d.get("status") in ("NO_EDR", "NO_MDM", "IDP_ONLY")]
        safe_new = [d for d in new_devices if d.get("status") not in ("NO_EDR", "NO_MDM", "IDP_ONLY")]
        if risky_new:
            risky_list = "\n".join(
                f":warning: `{(d.get('hostnames') or ['?'])[0]}` — {d.get('owner_email') or 'no owner'} — *{d.get('status')}*"
                for d in risky_new[:5]
            )
            more = f"\n_+ {len(risky_new) - 5} more_" if len(risky_new) > 5 else ""
            blocks.append(_blocks_section(f"*:new: {len(risky_new)} New Devices Without Full Coverage*\n{risky_list}{more}"))
        if safe_new:
            blocks.append(_blocks_section(f":new: {len(safe_new)} new devices detected (managed)"))

    # Dual-use users
    if dual_use:
        blocks.append(_blocks_divider())
        du_list = "\n".join(
            f":iphone: `{u['email']}` — personal: {u['personal_devices'][0]['hostname']}"
            for u in dual_use[:5]
        )
        more = f"\n_+ {len(dual_use) - 5} more_" if len(dual_use) > 5 else ""
        blocks.append(_blocks_section(f"*:iphone: {len(dual_use)} Users With Personal Devices*\n{du_list}{more}"))

    # All clear
    if not disappeared and not newly_stale and not new_devices and not dual_use:
        blocks.append(_blocks_section(":white_check_mark: No changes since last sync"))

    blocks.append(_blocks_divider())
    blocks.append(_blocks_context(["Klar Device Normalizer — IT Security Team"]))

    return blocks


def alert_after_sync(
    devices: list[NormalizedDevice],
    sync_result: dict[str, Any],
    disappeared: list[dict[str, Any]] | None = None,
    newly_stale: list[dict[str, Any]] | None = None,
    new_devices: list[dict[str, Any]] | None = None,
) -> None:
    """Send a Slack alert summarizing the sync."""
    if not _get_webhook_url():
        return

    no_edr = [d for d in devices if "crowdstrike" not in d.sources]
    no_mdm = [d for d in devices if "jumpcloud" not in d.sources]

    status_counts: dict[str, int] = {}
    for d in devices:
        status_counts[d.status] = status_counts.get(d.status, 0) + 1

    total = len(devices)
    managed = status_counts.get("MANAGED", 0) + status_counts.get("FULLY_MANAGED", 0)

    # Detect dual-use (personal + corporate)
    by_owner: dict[str, list[NormalizedDevice]] = {}
    for d in devices:
        if d.owner_email:
            by_owner.setdefault(d.owner_email.lower(), []).append(d)
    dual_use_users: list[dict[str, Any]] = []
    for email, devs in by_owner.items():
        corporate = [d for d in devs if "jumpcloud" in d.sources or "crowdstrike" in d.sources]
        personal = [d for d in devs if d.status == "IDP_ONLY"]
        if corporate and personal:
            dual_use_users.append({
                "email": email,
                "personal_devices": [{"hostname": (d.hostnames or ["?"])[0]} for d in personal],
            })

    blocks = build_sync_blocks(
        status_counts=status_counts,
        total=total,
        managed=managed,
        sources_ok=sync_result.get("sources_ok", []),
        sources_failed=sync_result.get("sources_failed", []),
        sync_status=sync_result.get("status", "unknown"),
        disappeared=disappeared,
        newly_stale=newly_stale,
        new_devices=new_devices,
        dual_use=dual_use_users if dual_use_users else None,
        no_edr_count=len(no_edr),
        no_mdm_count=len(no_mdm),
    )

    fallback = f"Klar Sync: {total} devices, {managed} managed"
    send_slack(fallback, blocks=blocks)
    logger.info("slack_alert_sent", no_edr=len(no_edr), disappeared=len(disappeared or []), newly_stale=len(newly_stale or []))
