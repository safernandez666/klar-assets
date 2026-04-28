"""Coverage-gap report (devices missing EDR/MDM/IDP)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from src.storage.repository import DeviceRepository
from src.web.dependencies import get_repo

router = APIRouter()


@router.get("/api/gaps")
async def api_gaps(repo: DeviceRepository = Depends(get_repo)) -> Any:
    """Group devices by which protective tool they're missing."""
    devices = repo.get_all_devices()
    gaps: dict[str, list[dict[str, Any]]] = {
        "missing_edr": [],
        "missing_mdm": [],
        "missing_idp": [],
    }
    for dev in devices:
        dev_gaps = dev.get("coverage_gaps", [])
        summary = {
            "canonical_id": dev.get("canonical_id"),
            "hostnames": dev.get("hostnames", []),
            "owner_email": dev.get("owner_email"),
            "status": dev.get("status"),
            "sources": dev.get("sources", []),
            "days_since_seen": dev.get("days_since_seen"),
        }
        for gap in dev_gaps:
            if gap in gaps:
                gaps[gap].append(summary)
    return JSONResponse(content={
        "gaps": {k: v for k, v in gaps.items()},
        "counts": {k: len(v) for k, v in gaps.items()},
    })
