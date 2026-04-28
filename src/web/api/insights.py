"""AI-generated insights, narrative report, and structured PDF data."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from src.insights import generate_insights, generate_report_text
from src.storage.repository import DeviceRepository
from src.web.cache import get_cache
from src.web.config import RISK_WEIGHTS
from src.web.dependencies import get_repo

router = APIRouter()


@router.get("/api/insights")
async def api_insights(repo: DeviceRepository = Depends(get_repo)) -> Any:
    """Quick-action recommendations based on the current inventory."""
    cache = get_cache()
    if cache.has("insights"):
        return JSONResponse(content=cache.get("insights"))
    devices = repo.get_all_devices()
    summary = repo.get_summary()
    history = repo.get_status_history(limit=10)
    actions = generate_insights(devices, summary, history)
    return JSONResponse(content={"actions": actions})


@router.get("/api/report")
async def api_report(repo: DeviceRepository = Depends(get_repo)) -> Any:
    """Narrative executive summary."""
    devices = repo.get_all_devices()
    summary = repo.get_summary()
    history = repo.get_status_history(limit=10)
    text = generate_report_text(devices, summary, history)
    return JSONResponse(content={"report": text})


@router.get("/api/report/full")
async def api_report_full(repo: DeviceRepository = Depends(get_repo)) -> Any:
    """Full structured report data for PDF generation."""
    devices = repo.get_all_devices()
    summary = repo.get_summary()
    by_status = summary.get("by_status", {})
    total_devices = summary.get("total", 0)
    if total_devices > 0:
        weighted = sum(by_status.get(s, 0) * w for s, w in RISK_WEIGHTS.items())
        summary["risk_score"] = round(weighted / total_devices, 1)
    else:
        summary["risk_score"] = 0
    history = repo.get_status_history(limit=10)
    last_sync = repo.get_last_sync_run()

    report_text = generate_report_text(devices, summary, history)
    actions = generate_insights(devices, summary, history)

    def device_summary(d: dict[str, Any]) -> dict[str, Any]:
        return {
            "hostname": (d.get("hostnames") or ["N/A"])[0],
            "serial": d.get("serial_number") or "N/A",
            "owner": d.get("owner_email") or "N/A",
            "os": d.get("os_type") or "N/A",
            "sources": d.get("sources", []),
            "status": d.get("status", "UNKNOWN"),
            "confidence": d.get("confidence_score", 0),
            "match_reason": d.get("match_reason", ""),
            "days_since_seen": d.get("days_since_seen"),
        }

    no_edr = [device_summary(d) for d in devices if d.get("status") == "NO_EDR"][:15]
    no_mdm = [device_summary(d) for d in devices if d.get("status") == "NO_MDM"][:15]
    idp_only = [device_summary(d) for d in devices if d.get("status") == "IDP_ONLY"][:15]
    stale = sorted(
        [device_summary(d) for d in devices if d.get("status") == "STALE"],
        key=lambda x: x.get("days_since_seen") or 0, reverse=True,
    )[:10]

    unique_matches = []
    for d in devices:
        sources = d.get("sources", [])
        if len(sources) >= 2 and (d.get("confidence_score") or 0) >= 0.6:
            unique_matches.append(device_summary(d))
    unique_matches.sort(key=lambda x: x["confidence"], reverse=True)

    low_confidence = sorted(
        [device_summary(d) for d in devices if (d.get("confidence_score") or 0) < 0.5],
        key=lambda x: x["confidence"],
    )[:15]

    return JSONResponse(content={
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "executive_summary": report_text,
        "summary": summary,
        "last_sync": last_sync,
        "actions": actions,
        "categories": {
            "no_edr": {"title": "Devices without EDR (CrowdStrike)", "count": len([d for d in devices if d.get("status") == "NO_EDR"]), "devices": no_edr},
            "no_mdm": {"title": "Devices without MDM (JumpCloud)", "count": len([d for d in devices if d.get("status") == "NO_MDM"]), "devices": no_mdm},
            "idp_only": {"title": "IDP-Only Devices (potential shadow IT)", "count": len([d for d in devices if d.get("status") == "IDP_ONLY"]), "devices": idp_only},
            "stale": {"title": "Stale Devices (90+ days inactive)", "count": len([d for d in devices if d.get("status") == "STALE"]), "devices": stale},
        },
        "unique_matches": {"title": "Cross-source Matched Devices", "count": len(unique_matches), "devices": unique_matches[:20]},
        "low_confidence": {"title": "Low Confidence Matches (review needed)", "count": len(low_confidence), "devices": low_confidence},
    })
