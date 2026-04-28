"""Person-centric views (per-user device list and compliance check)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from src.storage.repository import DeviceRepository
from src.web.dependencies import get_repo

router = APIRouter()


@router.get("/api/people")
async def api_people(repo: DeviceRepository = Depends(get_repo)) -> Any:
    """Person-centric view: email → devices → compliance. Includes unassigned."""
    devices = repo.get_all_devices()
    acked = repo.get_acknowledged()

    by_owner: dict[str, list[dict[str, Any]]] = {}
    for d in devices:
        email = d.get("owner_email") or "unassigned"
        by_owner.setdefault(email.lower(), []).append(d)

    people = []
    for email, devs in sorted(by_owner.items()):
        non_acked = [d for d in devs if d.get("canonical_id") not in acked]
        managed_count = sum(1 for d in non_acked if d.get("status") in ("MANAGED", "FULLY_MANAGED"))
        total_count = len(non_acked)
        has_edr = any("crowdstrike" in d.get("sources", []) for d in non_acked)
        has_mdm = any("jumpcloud" in d.get("sources", []) for d in non_acked)
        statuses = list({d.get("status") for d in non_acked})

        people.append({
            "email": email,
            "device_count": total_count,
            "managed_count": managed_count,
            "has_edr": has_edr,
            "has_mdm": has_mdm,
            "compliant": managed_count > 0,
            "statuses": statuses,
            "devices": [{
                "hostname": (d.get("hostnames") or ["?"])[0],
                "status": d.get("status"),
                "sources": d.get("sources"),
                "serial": d.get("serial_number"),
                "os": d.get("os_type"),
                "confidence": d.get("confidence_score"),
            } for d in devs],
        })

    compliant = sum(1 for p in people if p["compliant"])
    return JSONResponse(content={
        "total_people": len(people),
        "compliant": compliant,
        "non_compliant": len(people) - compliant,
        "people": people,
    })


@router.get("/api/user/{email}/compliance")
async def api_user_compliance(email: str, repo: DeviceRepository = Depends(get_repo)) -> Any:
    """Check if a user has at least one managed device."""
    devices = repo.get_all_devices()
    acked = repo.get_acknowledged()

    user_devices = [d for d in devices
                    if (d.get("owner_email") or "").lower() == email.lower()
                    and d.get("canonical_id") not in acked]

    if not user_devices:
        return JSONResponse(content={"email": email, "found": False, "compliant": False, "devices": []})

    managed = [d for d in user_devices if d.get("status") in ("MANAGED", "FULLY_MANAGED")]
    has_edr = any("crowdstrike" in d.get("sources", []) for d in user_devices)
    has_mdm = any("jumpcloud" in d.get("sources", []) for d in user_devices)

    return JSONResponse(content={
        "email": email,
        "found": True,
        "compliant": len(managed) > 0,
        "has_edr": has_edr,
        "has_mdm": has_mdm,
        "device_count": len(user_devices),
        "managed_count": len(managed),
        "devices": [{
            "hostname": (d.get("hostnames") or ["?"])[0],
            "status": d.get("status"),
            "sources": d.get("sources"),
        } for d in user_devices],
    })
