"""Compliance-controls evaluation (CTL-001 .. CTL-008)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from src.storage.repository import DeviceRepository
from src.web.config import CONTROLS_META
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

    passing = sum(1 for r in results if r["status"] == "pass")
    return JSONResponse(content={
        "controls": results,
        "summary": {"total": len(results), "passing": passing, "failing": len(results) - passing},
    })
