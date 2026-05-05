"""Tools the AI assistant can call to read live inventory data.

The model receives function declarations matching `TOOLS_SCHEMA` and
can request a call. We dispatch via `execute_tool` against the
local DB (DeviceRepository) — the deduped, normalized snapshot that
the dashboard already trusts. We do NOT hit CrowdStrike / JumpCloud
/ Okta directly from the chat path because:

- DB is the source of truth post-sync (cheap, fast, consistent).
- Live API calls would be slower (~500ms-15s per call) and cost
  external rate-limit budget.
- All data the dashboard shows is already in the DB.

Hard constraints:
- Read-only. No mutation tools.
- Per-call result size capped (max_results in each function) so the
  model can't accidentally request the whole inventory and blow the
  context window.
- Returns are plain dicts/lists (JSON-serializable), no internal IDs
  or raw_data leaks.
"""
from __future__ import annotations

from typing import Any

from src.storage.repository import DeviceRepository


_VALID_STATUSES = {
    "FULLY_MANAGED", "MANAGED", "NO_EDR", "NO_MDM",
    "IDP_ONLY", "SERVER", "STALE", "UNKNOWN",
}
_VALID_REGIONS = {"MEXICO", "AMERICAS", "EUROPE", "ROW", "UNKNOWN"}
_VALID_SOURCES = {"crowdstrike", "jumpcloud", "okta"}


# ── Tool implementations ──────────────────────────────────────────────

def list_devices(
    repo: DeviceRepository,
    *,
    status: str | None = None,
    region: str | None = None,
    source: str | None = None,
    owner_email: str | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """Filter the inventory and return up to `limit` devices.

    Each filter is optional. Returns a slim payload: hostname, owner,
    serial, status, sources, region, last_seen.
    """
    limit = max(1, min(int(limit or 10), 50))
    if status and status not in _VALID_STATUSES:
        return {"error": f"Invalid status. Must be one of: {sorted(_VALID_STATUSES)}"}
    if region and region not in _VALID_REGIONS:
        return {"error": f"Invalid region. Must be one of: {sorted(_VALID_REGIONS)}"}
    if source and source not in _VALID_SOURCES:
        return {"error": f"Invalid source. Must be one of: {sorted(_VALID_SOURCES)}"}

    devices = repo.get_all_devices(
        status=status,
        source=source,
        region=region,
    )

    if owner_email:
        owner_lower = owner_email.strip().lower()
        devices = [d for d in devices if (d.get("owner_email") or "").lower() == owner_lower]

    devices = devices[:limit]

    return {
        "count": len(devices),
        "limit": limit,
        "devices": [
            {
                "hostname": (d.get("hostnames") or ["?"])[0],
                "owner": d.get("owner_email") or None,
                "serial": d.get("serial_number"),
                "status": d.get("status"),
                "sources": d.get("sources", []),
                "region": d.get("region") or "UNKNOWN",
                "last_seen": d.get("last_seen"),
            }
            for d in devices
        ],
    }


def lookup_device_by_serial(
    repo: DeviceRepository,
    *,
    serial: str,
) -> dict[str, Any]:
    """Look up a single device by its hardware serial number."""
    if not serial or not serial.strip():
        return {"error": "Serial cannot be empty"}
    serial = serial.strip()
    devices = repo.get_all_devices(search=serial)
    matches = [d for d in devices if (d.get("serial_number") or "").lower() == serial.lower()]
    if not matches:
        return {"found": False, "serial": serial}
    d = matches[0]
    return {
        "found": True,
        "hostname": (d.get("hostnames") or ["?"])[0],
        "all_hostnames": d.get("hostnames", []),
        "owner": d.get("owner_email") or None,
        "owner_name": d.get("owner_name") or None,
        "serial": d.get("serial_number"),
        "os_type": d.get("os_type"),
        "status": d.get("status"),
        "sources": d.get("sources", []),
        "region": d.get("region") or "UNKNOWN",
        "timezone": d.get("timezone"),
        "first_seen": d.get("first_seen"),
        "last_seen": d.get("last_seen"),
        "days_since_seen": d.get("days_since_seen"),
        "confidence_score": d.get("confidence_score"),
    }


def get_user_devices(
    repo: DeviceRepository,
    *,
    email: str,
) -> dict[str, Any]:
    """List every device assigned to a user."""
    if not email or not email.strip():
        return {"error": "Email cannot be empty"}
    email_lower = email.strip().lower()
    devices = repo.get_all_devices()
    matches = [d for d in devices if (d.get("owner_email") or "").lower() == email_lower]
    if not matches:
        return {"found": False, "email": email}
    return {
        "found": True,
        "email": email,
        "count": len(matches),
        "devices": [
            {
                "hostname": (d.get("hostnames") or ["?"])[0],
                "serial": d.get("serial_number"),
                "status": d.get("status"),
                "sources": d.get("sources", []),
                "region": d.get("region") or "UNKNOWN",
                "last_seen": d.get("last_seen"),
            }
            for d in matches
        ],
    }


def get_summary(repo: DeviceRepository) -> dict[str, Any]:
    """Fleet-wide aggregate counts. Use for 'how many', 'distribution', 'percentages' questions."""
    s = repo.get_summary()
    return {
        "total": s.get("total"),
        "by_status": s.get("by_status", {}),
        "by_source": s.get("by_source", {}),
        "by_region": s.get("by_region", {}),
        "by_os": s.get("by_os", {}),
        "endpoint_total": s.get("endpoint_total"),
    }


# ── OpenAI function-calling schema ────────────────────────────────────

TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "list_devices",
            "description": (
                "List devices from the inventory matching optional filters. "
                "Use when the user asks for a listado / list / cuáles son / "
                "top N devices in a status, region, source, or owned by an email."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "enum": sorted(_VALID_STATUSES),
                        "description": "Filter by device status (e.g. NO_EDR, NO_MDM, IDP_ONLY).",
                    },
                    "region": {
                        "type": "string",
                        "enum": sorted(_VALID_REGIONS),
                        "description": "Filter by region.",
                    },
                    "source": {
                        "type": "string",
                        "enum": sorted(_VALID_SOURCES),
                        "description": "Filter by source: crowdstrike, jumpcloud, or okta.",
                    },
                    "owner_email": {
                        "type": "string",
                        "description": "Filter by owner email (exact match, case-insensitive).",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max number of devices to return. Default 10, max 50.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lookup_device_by_serial",
            "description": (
                "Look up a single device by its hardware serial number. "
                "Returns owner, hostname, status, sources, region, last seen, etc."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "serial": {
                        "type": "string",
                        "description": "The hardware serial (e.g. L3073WL9G6).",
                    },
                },
                "required": ["serial"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_user_devices",
            "description": (
                "Return every device assigned to a user, looked up by email. "
                "Useful for compliance questions or 'who has X'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "email": {
                        "type": "string",
                        "description": "The user's corporate email.",
                    },
                },
                "required": ["email"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_summary",
            "description": (
                "Fleet-wide aggregate counts: total devices, by_status, by_source, "
                "by_region, by_os. Use for 'how many', 'distribution', 'percentage' questions."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


_DISPATCH = {
    "list_devices": list_devices,
    "lookup_device_by_serial": lookup_device_by_serial,
    "get_user_devices": get_user_devices,
    "get_summary": get_summary,
}


def execute_tool(name: str, arguments: dict[str, Any], repo: DeviceRepository) -> dict[str, Any]:
    """Dispatch a tool call from the model. Unknown tool → error dict."""
    fn = _DISPATCH.get(name)
    if fn is None:
        return {"error": f"Unknown tool: {name}"}
    try:
        return fn(repo, **(arguments or {}))
    except TypeError as exc:
        return {"error": f"Bad arguments for {name}: {exc}"}
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}
