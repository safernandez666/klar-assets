from __future__ import annotations

import json
import os
from typing import Any

import structlog
from openai import OpenAI

logger = structlog.get_logger(__name__)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

SYSTEM_PROMPT = """You are an IT security analyst reviewing a device inventory for a company.
The inventory normalizes data from three sources:
- JumpCloud (MDM - Mobile Device Management, source of truth for device management)
- CrowdStrike (EDR - Endpoint Detection and Response)
- Okta (IDP - Identity Provider)

Status definitions:
- FULLY_MANAGED: Device has JumpCloud + CrowdStrike + Okta + owner assigned (complete visibility)
- MANAGED: Device has JumpCloud + CrowdStrike (MDM + EDR, the baseline for managed)
- NO_EDR: Device in JumpCloud but missing CrowdStrike (needs EDR deployment)
- NO_MDM: Device in CrowdStrike but missing JumpCloud (needs MDM enrollment)
- IDP_ONLY: Device only in Okta, no EDR or MDM (potential shadow IT)
- STALE: Device not seen in 90+ days (candidate for cleanup)

Mobile devices are already filtered out. This is desktop/laptop only.

Analyze the data and provide 4-6 actionable recommendations. For each:
- Assign a priority: critical, high, medium, low, or success
- Give a short title (under 60 chars)
- Give a description (2-3 sentences max) with specific numbers and device/owner names when available

Respond ONLY with a JSON array of objects with keys: priority, title, description.
No markdown, no commentary, just the JSON array."""


def generate_insights(
    devices: list[dict[str, Any]],
    summary: dict[str, Any],
    history: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """Generate insights using OpenAI, with fallback to rule-based."""
    if OPENAI_API_KEY:
        try:
            return _generate_with_openai(devices, summary, history)
        except Exception as exc:
            logger.error("openai_insights_failed", error=str(exc))

    return _generate_rule_based(devices, summary, history)


def _build_context(
    devices: list[dict[str, Any]],
    summary: dict[str, Any],
    history: list[dict[str, Any]],
) -> str:
    """Build a concise context string for the AI."""
    by_status = summary.get("by_status", {})
    by_source = summary.get("by_source", {})
    total = summary.get("total", 0)

    # Top devices missing EDR
    no_edr = [d for d in devices if d.get("status") == "NO_EDR"]
    no_edr_sample = [
        {"hostname": (d.get("hostnames") or ["?"])[0], "owner": d.get("owner_email"), "sources": d.get("sources")}
        for d in no_edr[:10]
    ]

    # Top devices missing MDM
    no_mdm = [d for d in devices if d.get("status") == "NO_MDM"]
    no_mdm_sample = [
        {"hostname": (d.get("hostnames") or ["?"])[0], "owner": d.get("owner_email"), "sources": d.get("sources")}
        for d in no_mdm[:10]
    ]

    # IDP only (potential shadow IT)
    idp_only = [d for d in devices if d.get("status") == "IDP_ONLY"]
    idp_sample = [
        {"hostname": (d.get("hostnames") or ["?"])[0], "owner": d.get("owner_email"), "os": d.get("os_type")}
        for d in idp_only[:10]
    ]

    # Stale devices
    stale = [d for d in devices if d.get("status") == "STALE"]
    stale_sample = [
        {"hostname": (d.get("hostnames") or ["?"])[0], "days_inactive": d.get("days_since_seen")}
        for d in sorted(stale, key=lambda x: x.get("days_since_seen") or 0, reverse=True)[:5]
    ]

    # Low confidence
    low_conf = [d for d in devices if (d.get("confidence_score") or 0) < 0.5]

    # Trends
    trend_info = ""
    if len(history) >= 2:
        latest = history[-1]
        prev = history[-2]
        trend_info = f"""
Trends (vs previous sync):
- FULLY_MANAGED: {latest.get('fully_managed', 0) - prev.get('fully_managed', 0):+d}
- NO_EDR: {latest.get('no_edr', 0) - prev.get('no_edr', 0):+d}
- NO_MDM: {latest.get('no_mdm', 0) - prev.get('no_mdm', 0):+d}"""

    managed = by_status.get("MANAGED", 0) + by_status.get("FULLY_MANAGED", 0)
    managed_pct = round(managed / total * 100) if total else 0

    return f"""Fleet summary: {total} desktop/laptop devices
Status breakdown: {json.dumps(by_status)}
Source counts: {json.dumps(by_source)}
Managed rate: {managed_pct}% ({managed}/{total})
Low confidence matches: {len(low_conf)}
{trend_info}

Devices without EDR ({len(no_edr)}): {json.dumps(no_edr_sample)}
Devices without MDM ({len(no_mdm)}): {json.dumps(no_mdm_sample)}
IDP-only devices ({len(idp_only)}): {json.dumps(idp_sample)}
Stale devices ({len(stale)}): {json.dumps(stale_sample)}"""


def _generate_with_openai(
    devices: list[dict[str, Any]],
    summary: dict[str, Any],
    history: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """Call OpenAI API to generate insights."""
    client = OpenAI(api_key=OPENAI_API_KEY)
    context = _build_context(devices, summary, history)

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": context},
        ],
        temperature=0.3,
        max_tokens=1000,
    )

    content = response.choices[0].message.content or "[]"
    # Strip markdown fences if present
    content = content.strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[1] if "\n" in content else content[3:]
    if content.endswith("```"):
        content = content[:-3]
    content = content.strip()

    actions = json.loads(content)
    logger.info("openai_insights_generated", count=len(actions))
    return actions


def _generate_rule_based(
    devices: list[dict[str, Any]],
    summary: dict[str, Any],
    history: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """Fallback rule-based insights when OpenAI is not available."""
    actions: list[dict[str, str]] = []
    by_status = summary.get("by_status", {})
    total = summary.get("total", 0)
    if total == 0:
        return [{"priority": "info", "title": "No data yet", "description": "Run a sync to populate the inventory."}]

    no_edr = by_status.get("NO_EDR", 0)
    no_mdm = by_status.get("NO_MDM", 0)
    idp_only = by_status.get("IDP_ONLY", 0)
    stale = by_status.get("STALE", 0)
    managed = by_status.get("MANAGED", 0)
    fully_managed = by_status.get("FULLY_MANAGED", 0)
    managed_pct = round((managed + fully_managed) / total * 100) if total else 0

    if no_edr > 0:
        missing = [d for d in devices if d.get("status") == "NO_EDR"]
        sample = ", ".join(
            d.get("owner_email") or (d.get("hostnames") or ["unknown"])[0]
            for d in missing[:3]
        )
        actions.append({
            "priority": "critical",
            "title": f"Install CrowdStrike on {no_edr} devices",
            "description": f"Devices in JumpCloud without EDR. Top: {sample}. Deploy via JumpCloud policy.",
        })

    if no_mdm > 0:
        missing = [d for d in devices if d.get("status") == "NO_MDM"]
        sample = ", ".join(
            d.get("owner_email") or (d.get("hostnames") or ["unknown"])[0]
            for d in missing[:3]
        )
        actions.append({
            "priority": "high",
            "title": f"Enroll {no_mdm} devices in JumpCloud",
            "description": f"Devices with CrowdStrike but not managed by IT. Top: {sample}.",
        })

    if idp_only > 0:
        actions.append({
            "priority": "high",
            "title": f"Investigate {idp_only} IDP-only workstations",
            "description": "Desktops/laptops in Okta without EDR or MDM. Possible shadow IT.",
        })

    if stale > 0:
        actions.append({
            "priority": "medium",
            "title": f"Clean up {stale} stale devices",
            "description": "Not seen in 90+ days. Remove from JC/CS to reduce license costs.",
        })

    actions.append({
        "priority": "success" if managed_pct >= 80 else "info",
        "title": f"{managed_pct}% fleet managed — {total - managed - fully_managed} to go",
        "description": f"{managed + fully_managed}/{total} devices have MDM + EDR coverage.",
    })

    return actions


REPORT_PROMPT = """You are an IT security analyst writing an executive summary for a device inventory report.
Write in professional English. The report will be included in a PDF export.

Based on the data provided, write:
1. **Executive Summary** (3-4 sentences): Overall fleet health, managed percentage, key risks.
2. **Key Findings** (4-6 bullet points): Specific numbers and actionable observations.
3. **Recommendations** (3-4 bullet points): Prioritized next steps.

Use markdown formatting. Be concise and specific with numbers. No fluff."""


def generate_report_text(
    devices: list[dict[str, Any]],
    summary: dict[str, Any],
    history: list[dict[str, Any]],
) -> str:
    """Generate executive summary text for PDF export."""
    context = _build_context(devices, summary, history)

    if OPENAI_API_KEY:
        try:
            client = OpenAI(api_key=OPENAI_API_KEY)
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": REPORT_PROMPT},
                    {"role": "user", "content": context},
                ],
                temperature=0.3,
                max_tokens=800,
            )
            text = response.choices[0].message.content or ""
            logger.info("openai_report_generated")
            return text
        except Exception as exc:
            logger.error("openai_report_failed", error=str(exc))

    # Fallback
    by_status = summary.get("by_status", {})
    total = summary.get("total", 0)
    managed = by_status.get("MANAGED", 0) + by_status.get("FULLY_MANAGED", 0)
    pct = round(managed / total * 100) if total else 0
    return (
        f"## Executive Summary\n\n"
        f"The fleet consists of {total} desktop/laptop devices. {pct}% ({managed}/{total}) have both "
        f"MDM (JumpCloud) and EDR (CrowdStrike) coverage. {by_status.get('NO_EDR', 0)} devices lack "
        f"endpoint protection, and {by_status.get('NO_MDM', 0)} are not enrolled in device management.\n\n"
        f"## Key Findings\n\n"
        f"- **{by_status.get('FULLY_MANAGED', 0)}** devices fully managed (MDM + EDR + IDP)\n"
        f"- **{by_status.get('MANAGED', 0)}** devices managed (MDM + EDR)\n"
        f"- **{by_status.get('NO_EDR', 0)}** devices missing CrowdStrike (EDR)\n"
        f"- **{by_status.get('NO_MDM', 0)}** devices missing JumpCloud (MDM)\n"
        f"- **{by_status.get('IDP_ONLY', 0)}** devices only in Okta (potential shadow IT)\n"
        f"- **{by_status.get('STALE', 0)}** stale devices (90+ days inactive)\n\n"
        f"## Recommendations\n\n"
        f"- Deploy CrowdStrike on all {by_status.get('NO_EDR', 0)} unprotected devices\n"
        f"- Enroll {by_status.get('NO_MDM', 0)} unmanaged devices in JumpCloud\n"
        f"- Investigate {by_status.get('IDP_ONLY', 0)} IDP-only workstations for shadow IT\n"
        f"- Clean up {by_status.get('STALE', 0)} stale devices to reduce license costs"
    )
