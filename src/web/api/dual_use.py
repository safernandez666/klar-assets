"""Dual-use detection — users with both corporate and personal devices."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from src.storage.repository import DeviceRepository
from src.web.dependencies import get_repo

router = APIRouter()


@router.get("/api/dual-use")
async def api_dual_use(repo: DeviceRepository = Depends(get_repo)) -> Any:
    """People using both corporate and personal devices."""
    devices = repo.get_all_devices()

    by_owner: dict[str, list[dict[str, Any]]] = {}
    for d in devices:
        email = d.get("owner_email")
        if email:
            by_owner.setdefault(email.lower(), []).append(d)

    dual_users = []
    for email, devs in by_owner.items():
        corporate = [d for d in devs if "jumpcloud" in d.get("sources", []) or "crowdstrike" in d.get("sources", [])]
        personal = [d for d in devs if d.get("status") == "IDP_ONLY"]
        if corporate and personal:
            dual_users.append({
                "email": email,
                "corporate_devices": [{
                    "hostname": (d.get("hostnames") or ["?"])[0],
                    "status": d.get("status"),
                    "sources": d.get("sources"),
                    "serial": d.get("serial_number"),
                } for d in corporate],
                "personal_devices": [{
                    "hostname": (d.get("hostnames") or ["?"])[0],
                    "status": d.get("status"),
                    "serial": d.get("serial_number"),
                    "os": d.get("os_type"),
                } for d in personal],
            })

    return JSONResponse(content={
        "dual_use_count": len(dual_users),
        "total_users_with_devices": len(by_owner),
        "users": dual_users,
    })
