"""Device inventory endpoints — listing and acknowledgement."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from src.storage.repository import DeviceRepository
from src.web.dependencies import get_current_user, get_repo

router = APIRouter()


@router.get("/api/devices")
async def api_devices(
    status: str | None = None,
    source: str | None = None,
    search: str | None = None,
    page: int | None = None,
    page_size: int = 25,
    repo: DeviceRepository = Depends(get_repo),
) -> Any:
    """List devices with optional filters and pagination, annotated with ack info."""
    result = repo.get_all_devices(status=status, source=source, search=search, page=page, page_size=page_size)
    acked = repo.get_acknowledged_details()

    # Paginated response
    if isinstance(result, dict):
        for d in result["devices"]:
            cid = d.get("canonical_id", "")
            if cid in acked:
                d["acknowledged"] = True
                d["ack_reason"] = acked[cid]["reason"]
                d["ack_by"] = acked[cid]["by"]
                d["ack_at"] = acked[cid]["at"]
            else:
                d["acknowledged"] = False
        return JSONResponse(content=result)

    # Legacy: no pagination (used by other internal callers)
    for d in result:
        cid = d.get("canonical_id", "")
        if cid in acked:
            d["acknowledged"] = True
            d["ack_reason"] = acked[cid]["reason"]
            d["ack_by"] = acked[cid]["by"]
            d["ack_at"] = acked[cid]["at"]
        else:
            d["acknowledged"] = False
    return JSONResponse(content={"devices": result})


class AckRequest(BaseModel):
    reason: str = ""
    by: str = ""


@router.post("/api/devices/{canonical_id}/ack")
async def ack_device(
    canonical_id: str,
    body: AckRequest,
    repo: DeviceRepository = Depends(get_repo),
    current_user: str | None = Depends(get_current_user),
) -> Any:
    """Mark a device as acknowledged. Falls back to the current session user."""
    ack_by = body.by or current_user or "unknown"
    repo.acknowledge_device(canonical_id, reason=body.reason, by=ack_by)
    return JSONResponse(content={"ok": True, "canonical_id": canonical_id, "by": ack_by})


@router.delete("/api/devices/{canonical_id}/ack")
async def unack_device(
    canonical_id: str,
    repo: DeviceRepository = Depends(get_repo),
) -> Any:
    """Remove acknowledgement from a device."""
    repo.unacknowledge_device(canonical_id)
    return JSONResponse(content={"ok": True, "canonical_id": canonical_id})
