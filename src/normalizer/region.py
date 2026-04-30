"""Map an IANA timezone string to a coarse business region.

Source data comes from the device agents (CrowdStrike `timezone`, JumpCloud
`systemTimezone`). Used by the inventory filter and any per-region reports.
"""
from __future__ import annotations

# Region constants — kept short and uppercase so they're cheap to filter on
# and stable to display in the UI.
MEXICO = "MEXICO"
AMERICAS = "AMERICAS"
EUROPE = "EUROPE"
ROW = "ROW"  # Asia / Africa / Oceania / unknown
UNKNOWN = "UNKNOWN"


def region_from_timezone(tz: str | None) -> str:
    """Return a region bucket for an IANA timezone string.

    `America/Mexico_City` and `America/Cancun` → MEXICO
    `America/*` (others)                         → AMERICAS
    `Europe/*`                                   → EUROPE
    Everything else (including UTC, missing)     → ROW / UNKNOWN
    """
    if not tz:
        return UNKNOWN
    t = tz.strip()
    if not t:
        return UNKNOWN
    if t.startswith("America/Mexico") or t in {"America/Cancun", "America/Merida", "America/Monterrey", "America/Tijuana", "America/Hermosillo", "America/Mazatlan", "America/Chihuahua", "America/Bahia_Banderas", "America/Matamoros", "America/Ojinaga"}:
        return MEXICO
    if t.startswith("America/"):
        return AMERICAS
    if t.startswith("Europe/"):
        return EUROPE
    return ROW
