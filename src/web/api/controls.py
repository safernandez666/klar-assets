"""Compliance-controls evaluation (CTL-001 .. CTL-011)."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from src.jumpcloud_reconciler import (
    fetch_jc_agent_health_live,
    fetch_jc_command_health_live,
)
from src.storage.repository import DeviceRepository
from src.web.config import (
    CONTROLS_META,
    STALE_SOURCE_THRESHOLD_DAYS,
    ZOMBIE_AGENT_LAST_CONTACT_HOURS,
)
from src.web.dependencies import get_repo

router = APIRouter()


@router.get("/api/controls")
async def api_controls(repo: DeviceRepository = Depends(get_repo)) -> Any:
    """Evaluate 8 compliance controls against current device inventory."""
    devices = repo.get_all_devices()
    acked = repo.get_acknowledged()

    active = [d for d in devices if d.get("canonical_id") not in acked
              and d.get("status") != "SERVER" and not d.get("deleted_at")]

    okta_devices = [d for d in active if "okta" in d.get("sources", [])]
    jc_devices = [d for d in active if "jumpcloud" in d.get("sources", [])]
    cs_devices = [d for d in active if "crowdstrike" in d.get("sources", [])]

    okta_users = {(d.get("owner_email") or "").lower() for d in okta_devices if d.get("owner_email")}
    jc_owners = {(d.get("owner_email") or "").lower() for d in jc_devices if d.get("owner_email")}

    def _dev_summary(d: dict) -> dict:
        return {
            "canonical_id": d.get("canonical_id"),
            "hostname": (d.get("hostnames") or ["—"])[0],
            "serial": d.get("serial_number"),
            "owner": d.get("owner_email") or "N/A",
            "status": d.get("status"),
            "sources": d.get("sources", []),
            "last_seen": d.get("last_seen"),
            "days_since_seen": d.get("days_since_seen"),
        }

    results = []

    # CTL-001: Okta devices not in JC (IDP_ONLY)
    ctl1 = [d for d in active if d.get("status") == "IDP_ONLY"]
    results.append({**CONTROLS_META[0], "status": "fail" if ctl1 else "pass",
                    "total": len(okta_devices), "affected": len(ctl1),
                    "devices": [_dev_summary(d) for d in ctl1[:50]]})

    # CTL-002: JC devices without CS (NO_EDR)
    ctl2 = [d for d in active if d.get("status") == "NO_EDR"]
    results.append({**CONTROLS_META[1], "status": "fail" if ctl2 else "pass",
                    "total": len(jc_devices), "affected": len(ctl2),
                    "devices": [_dev_summary(d) for d in ctl2[:50]]})

    # CTL-003: CS devices without JC (NO_MDM)
    ctl3 = [d for d in active if d.get("status") == "NO_MDM"]
    results.append({**CONTROLS_META[2], "status": "fail" if ctl3 else "pass",
                    "total": len(cs_devices), "affected": len(ctl3),
                    "devices": [_dev_summary(d) for d in ctl3[:50]]})

    # CTL-004: Access without any protection (IDP_ONLY + NO_MDM)
    ctl4 = [d for d in active if d.get("status") in ("IDP_ONLY", "NO_MDM")]
    results.append({**CONTROLS_META[3], "status": "fail" if ctl4 else "pass",
                    "total": len(okta_devices), "affected": len(ctl4),
                    "devices": [_dev_summary(d) for d in ctl4[:50]]})

    # CTL-005: Okta users with no JC device (uses real Okta user list)
    all_okta_users = repo.get_okta_users(exclude_types=["external_agent", "system"])
    if all_okta_users:
        # Real user list available — compare against JC device owners
        okta_user_emails = {u["email"].lower() for u in all_okta_users if u.get("email")}
        users_no_jc = okta_user_emails - jc_owners
        ctl5_users = [{"canonical_id": u["id"], "hostname": "—",
                       "serial": None, "owner": u["email"],
                       "status": u.get("user_type") or "employee", "sources": ["okta"],
                       "last_seen": u.get("last_login"), "days_since_seen": None}
                      for u in all_okta_users if u["email"].lower() in users_no_jc]
        results.append({**CONTROLS_META[4], "status": "fail" if users_no_jc else "pass",
                        "total": len(okta_user_emails), "affected": len(users_no_jc),
                        "devices": ctl5_users[:50]})
    else:
        # Fallback: infer from device owners
        users_no_jc = okta_users - jc_owners
        ctl5_devs = [d for d in okta_devices if (d.get("owner_email") or "").lower() in users_no_jc]
        results.append({**CONTROLS_META[4], "status": "fail" if users_no_jc else "pass",
                        "total": len(okta_users), "affected": len(users_no_jc),
                        "devices": [_dev_summary(d) for d in ctl5_devs[:50]]})

    # CTL-006: JC devices without owner
    ctl6 = [d for d in jc_devices if not d.get("owner_email")]
    results.append({**CONTROLS_META[5], "status": "fail" if ctl6 else "pass",
                    "total": len(jc_devices), "affected": len(ctl6),
                    "devices": [_dev_summary(d) for d in ctl6[:50]]})

    # CTL-007: JC devices not reporting (stale, 30+ days)
    ctl7 = [d for d in jc_devices if (d.get("days_since_seen") or 0) >= 30]
    results.append({**CONTROLS_META[6], "status": "fail" if ctl7 else "pass",
                    "total": len(jc_devices), "affected": len(ctl7),
                    "devices": [_dev_summary(d) for d in ctl7[:50]]})

    # CTL-008: CS devices not reporting (stale, 30+ days)
    ctl8 = [d for d in cs_devices if (d.get("days_since_seen") or 0) >= 30]
    results.append({**CONTROLS_META[7], "status": "fail" if ctl8 else "pass",
                    "total": len(cs_devices), "affected": len(ctl8),
                    "devices": [_dev_summary(d) for d in ctl8[:50]]})

    # CTL-009: per-source agent dormancy (10+ days by default).
    # Catches the case where the merged last_seen is recent (because other
    # sources are still reporting) but at least one source's individual
    # agent went silent. CTL-007/008 miss this because they compare the
    # merged last_seen, which takes the max across sources.
    cutoff = datetime.now(timezone.utc) - timedelta(days=STALE_SOURCE_THRESHOLD_DAYS)
    ctl9 = []
    for d in active:
        sls = d.get("source_last_seen") or {}
        if not sls:
            # Older rows pre-migration may have empty dicts; skip — those
            # surface naturally in CTL-007/008 if relevant.
            continue
        stale_sources: list[str] = []
        stale_detail: dict[str, str] = {}
        for src, ts in sls.items():
            if not ts:
                continue
            try:
                seen = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                if seen.tzinfo is None:
                    seen = seen.replace(tzinfo=timezone.utc)
                if seen < cutoff:
                    stale_sources.append(src)
                    stale_detail[src] = ts
            except (ValueError, TypeError):
                # Malformed timestamp — surface as stale conservatively
                # rather than swallow it silently.
                stale_sources.append(src)
                stale_detail[src] = ts
        if stale_sources:
            ctl9.append({**_dev_summary(d),
                         "stale_sources": stale_sources,
                         "stale_detail": stale_detail})
    results.append({**CONTROLS_META[8], "status": "fail" if ctl9 else "pass",
                    "total": len(active), "affected": len(ctl9),
                    "threshold_days": STALE_SOURCE_THRESHOLD_DAYS,
                    "devices": ctl9[:50]})

    # CTL-011: JC zombie agent — reports inventory but doesn't actually
    # execute work. JumpCloud has *two* execution channels and they fail
    # independently, so we check both:
    #
    #   policy_pending — `policyStats.success == 0` AND `pending > 0`. The
    #     declarative MDM channel never converged. Most common after a
    #     macOS Tahoe upgrade where the user account that runs the agent
    #     loses secureToken.
    #
    #   commands_dead — agent has been issued ≥3 commandresults in the
    #     last 7 days and *none* of them returned an exitCode. The
    #     imperative script channel is dead. This is the subtle case:
    #     policyStats can look perfect (e.g. KV2GY645QV with 11/11) yet
    #     CrowdStrike Install will silently fail forever. Typical cause:
    #     TCC/PPPC denied to jumpcloud-agent for Full Disk Access or
    #     Background Tasks.
    #
    # We deliberately ignore JC's `active` flag — it flips to false within
    # ~30 min of idleness so trusting it would hide most zombies. The
    # `last_contact` cutoff (env `ZOMBIE_AGENT_LAST_CONTACT_HOURS`,
    # default 24) keeps the bucket tight against CTL-007.
    #
    # Skipped if no JC_API_KEY.
    ctl11: list[dict[str, Any]] = []
    jc_health: dict[str, dict] = {}
    cmd_health: dict[str, dict] = {}
    jc_key = os.getenv("JC_API_KEY", "")
    if jc_key and jc_devices:
        try:
            jc_health = fetch_jc_agent_health_live(api_key=jc_key)
        except Exception:
            jc_health = {}
        try:
            cmd_health = fetch_jc_command_health_live(api_key=jc_key, days=7)
        except Exception:
            cmd_health = {}
    zombie_cutoff = datetime.now(timezone.utc) - timedelta(hours=ZOMBIE_AGENT_LAST_CONTACT_HOURS)
    MIN_COMMANDS_FOR_DEAD = 3   # we need *some* sample size before we conclude "commands are broken"

    for d in jc_devices:
        sid = (d.get("source_ids") or {}).get("jumpcloud")
        if not sid or sid not in jc_health:
            continue
        h = jc_health[sid]
        last = h.get("last_contact") or ""
        try:
            seen = datetime.fromisoformat(str(last).replace("Z", "+00:00"))
            if seen.tzinfo is None:
                seen = seen.replace(tzinfo=timezone.utc)
            if seen < zombie_cutoff:
                continue
        except (ValueError, TypeError):
            continue

        # Pattern A: policy pending
        ps = h.get("policy_stats") or {}
        try:
            success = int(ps.get("success", 0) or 0)
            pending = int(ps.get("pending", 0) or 0)
            failed = int(ps.get("failed", 0) or 0)
        except (ValueError, TypeError):
            success, pending, failed = 0, 0, 0
        is_policy_zombie = success == 0 and pending > 0

        # Pattern B: commands never complete
        cmd = cmd_health.get(sid) or {}
        cmd_total = cmd.get("total", 0)
        cmd_completed = cmd.get("completed", 0)
        is_command_zombie = cmd_total >= MIN_COMMANDS_FOR_DEAD and cmd_completed == 0

        if not (is_policy_zombie or is_command_zombie):
            continue

        reasons = []
        if is_policy_zombie:
            reasons.append("policy_pending")
        if is_command_zombie:
            reasons.append("commands_dead")

        ctl11.append({
            **_dev_summary(d),
            "zombie_reasons": reasons,
            "policy_stats": {"success": success, "pending": pending, "failed": failed},
            "command_stats": {"total_7d": cmd_total, "completed_7d": cmd_completed,
                              "latest_request": cmd.get("latest_request") or None,
                              "latest_completed": cmd.get("latest_completed") or None},
            "last_contact": last,
            "os_family": h.get("os_family"),
        })
    results.append({**CONTROLS_META[9], "status": "fail" if ctl11 else "pass",
                    "total": len(jc_devices), "affected": len(ctl11),
                    "cutoff_hours": ZOMBIE_AGENT_LAST_CONTACT_HOURS,
                    "min_commands_for_dead": MIN_COMMANDS_FOR_DEAD,
                    "devices": ctl11[:50]})

    passing = sum(1 for r in results if r["status"] == "pass")
    return JSONResponse(content={
        "controls": results,
        "summary": {"total": len(results), "passing": passing, "failing": len(results) - passing},
    })
