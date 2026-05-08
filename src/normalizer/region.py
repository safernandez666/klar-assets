"""Resolve a device's country bucket (MX / AR / DE / OT).

Priority ladder when classifying a device:
1. **Hostname** — if any hostname matches ``KLR-{XX}{Y}-...`` we trust ``XX``
   (set explicitly by the rename script with IANA timezone detection).
2. **Timezone** — JumpCloud `systemTimezone` (int or "HHMM" string) or
   CrowdStrike `timezone` (IANA string). Maps deterministically.
3. **CrowdStrike `agent_local_time`** — ISO 8601 with embedded UTC offset,
   used as a last resort for CS-only Windows devices that don't have a
   parseable timezone field.
4. **OT** (Other) when nothing matches.

Old bucket names (MEXICO/AMERICAS/EUROPE/ROW) are kept exported as
constants for any caller that still references them, but the value
written to ``device.region`` is now the 2-letter country code so the
chart aligns with the ``KLR-{XX}-...`` hostname taxonomy.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable


# ── 2-letter country codes (the new taxonomy) ──────────────────────────
MX = "MX"
AR = "AR"
DE = "DE"
OT = "OT"        # "Other" — Asia, Africa, US, Brazil, etc.
UNKNOWN = "UNKNOWN"

# ── Legacy aliases (kept so older imports don't break; values point to
# the new codes so old call sites still produce the right bucket). ──────
MEXICO = MX
AMERICAS = OT       # AMERICAS used to bundle BR/AR/CL/etc; now they fall under OT
EUROPE = OT
ROW = OT


_KLR_HOSTNAME_RE = re.compile(r"^KLR-(MX|AR|DE|OT)[MW]-", re.IGNORECASE)

_MEXICO_IANA = {
    "America/Cancun", "America/Merida", "America/Monterrey",
    "America/Tijuana", "America/Hermosillo", "America/Mazatlan",
    "America/Chihuahua", "America/Bahia_Banderas",
    "America/Matamoros", "America/Ojinaga",
}

_AR_IANA = {
    "America/Argentina/Buenos_Aires",
    "America/Argentina/Cordoba",
    "America/Argentina/Mendoza",
    "America/Argentina/Salta",
    "America/Argentina/Tucuman",
    "America/Argentina/Ushuaia",
    "America/Buenos_Aires",
}


# ── Public API ─────────────────────────────────────────────────────────

def country_from_hostname(hostnames: str | Iterable[str] | None) -> str | None:
    """Return the country code from a `KLR-XX...` hostname, else None.

    Accepts a single string OR any iterable (the dedup keeps a list of
    hostnames for cross-source merged devices).
    """
    if not hostnames:
        return None
    if isinstance(hostnames, str):
        candidates = [hostnames]
    else:
        candidates = list(hostnames)
    for h in candidates:
        if not h:
            continue
        m = _KLR_HOSTNAME_RE.match(h.strip())
        if m:
            return m.group(1).upper()
    return None


def country_from_timezone(tz: str | int | float | None) -> str | None:
    """Map a timezone (IANA string or numeric offset) to country code.

    Returns None when the timezone is empty / unparseable so the caller
    can fall back to the next signal in the ladder.
    """
    if tz is None:
        return None

    if isinstance(tz, str):
        s = tz.strip()
        if not s:
            return None
        try:
            return _country_from_offset(int(s))
        except ValueError:
            pass
        return _country_from_iana(s)

    if isinstance(tz, (int, float)):
        return _country_from_offset(int(tz))

    return None


def country_from_agent_local_time(iso: str | None) -> str | None:
    """Pull a country bucket from CrowdStrike's ``agent_local_time`` ISO.

    The string looks like ``2026-05-08T15:30:00-06:00`` — we only care
    about the trailing offset. Maps the offset to a country bucket the
    same way numeric tz does.
    """
    if not iso or not isinstance(iso, str):
        return None
    s = iso.strip()
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None
    if dt.tzinfo is None:
        return None
    offset = dt.utcoffset()
    if offset is None:
        return None
    hours = int(offset.total_seconds() // 3600)
    return _country_from_offset(hours)


def compute_country(
    hostnames: str | Iterable[str] | None,
    tz: str | int | float | None,
    agent_local_time: str | None = None,
) -> str:
    """Run the full priority ladder. Always returns a code (UNKNOWN if
    every signal failed)."""
    by_host = country_from_hostname(hostnames)
    if by_host:
        return by_host
    by_tz = country_from_timezone(tz)
    if by_tz:
        return by_tz
    by_alt = country_from_agent_local_time(agent_local_time)
    if by_alt:
        return by_alt
    return UNKNOWN


# ── Backward-compat alias used by dedup before the country migration. ──
def region_from_timezone(tz: str | int | float | None) -> str:
    """Deprecated wrapper — equivalent to ``country_from_timezone`` but
    returns ``UNKNOWN`` instead of ``None`` for backwards compatibility.
    """
    return country_from_timezone(tz) or UNKNOWN


# ── Internals ──────────────────────────────────────────────────────────

def _country_from_iana(s: str) -> str | None:
    if s.startswith("America/Mexico") or s in _MEXICO_IANA:
        return MX
    if s.startswith("America/Argentina") or s in _AR_IANA:
        return AR
    if (
        s.startswith("Europe/Berlin")
        or s.startswith("Europe/Frankfurt")
        or s == "CET"
        or s == "CEST"
    ):
        return DE
    if "/" in s or s.upper() == "UTC":
        return OT
    return None


def _country_from_offset(value: int) -> str | None:
    """Convert hour or HHMM offset to a country bucket.

    HHMM detection (matches old behaviour):
    - |value| <= 14         → plain hours
    - |value| <= 1459       → HHMM (e.g. -600 = UTC-6:00, 530 = UTC+5:30)
    - anything else         → None
    """
    abs_v = abs(value)
    if abs_v <= 14:
        hours = value
    elif abs_v <= 1459 and abs_v % 100 < 60:
        hours = int(value / 100)   # truncate toward zero, sign preserved
    else:
        return None

    # México (no DST): CST = UTC-6, MST = UTC-7
    if hours in (-6, -7):
        return MX
    # Argentina: UTC-3 year-round
    if hours == -3:
        return AR
    # Germany: CET (UTC+1) winter / CEST (UTC+2) summer
    if hours in (1, 2):
        return DE
    return OT
