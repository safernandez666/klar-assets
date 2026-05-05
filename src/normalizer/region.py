"""Map a timezone (IANA string or numeric offset) to a coarse business region.

Source data comes from the device agents:
- CrowdStrike: does NOT expose IANA timezone (only `agent_local_time` ISO).
- JumpCloud: exposes `systemTimezone` as an int. Format varies by agent
  version: newer agents return HHMM (e.g. -600 for UTC-6:00, 530 for
  UTC+5:30); older agents return plain hours (e.g. -6, 2). Both are
  handled here.

Used by the inventory filter and the dashboard region pie chart.
"""
from __future__ import annotations


# Region constants — kept short and uppercase so they're cheap to filter on
# and stable to display in the UI.
MEXICO = "MEXICO"
AMERICAS = "AMERICAS"
EUROPE = "EUROPE"
ROW = "ROW"  # Asia / Africa / Oceania
UNKNOWN = "UNKNOWN"


_MEXICO_IANA = {
    "America/Cancun", "America/Merida", "America/Monterrey",
    "America/Tijuana", "America/Hermosillo", "America/Mazatlan",
    "America/Chihuahua", "America/Bahia_Banderas",
    "America/Matamoros", "America/Ojinaga",
}


def region_from_timezone(tz: str | int | float | None) -> str:
    """Return a region bucket for a timezone value.

    Accepts:
    - IANA strings (`America/Mexico_City`, `Europe/Madrid`, …)
    - Numeric offsets in plain hours (e.g. -6) or HHMM (e.g. -600, 530)
      — JumpCloud `systemTimezone` returns either depending on agent version.
    - Numeric strings (e.g. "-600") — passed through as ints.
    - None / empty → UNKNOWN.

    Buckets:
    - MEXICO   → IANA America/Mexico* / Cancun / Tijuana / etc, or
                 numeric offset of UTC-6 / UTC-7 (México CST/MST, no DST since 2022).
    - AMERICAS → other America/* IANA, or UTC-3 to UTC-10 (excluding the
                 Mexico range).
    - EUROPE   → Europe/* IANA, or UTC-1 to UTC+3.
    - ROW      → everything else (Asia / Africa / Oceania, including UTC=0
                 since UTC-only is more often a server than a Klar user).
    - UNKNOWN  → null / empty / unparseable.
    """
    if tz is None:
        return UNKNOWN

    # IANA / string path
    if isinstance(tz, str):
        s = tz.strip()
        if not s:
            return UNKNOWN
        # Numeric strings ("-600") fall through to the offset branch.
        try:
            return _region_from_offset(int(s))
        except ValueError:
            pass
        return _region_from_iana(s)

    # Numeric offset (JumpCloud)
    if isinstance(tz, (int, float)):
        return _region_from_offset(int(tz))

    return UNKNOWN


def _region_from_iana(s: str) -> str:
    if s.startswith("America/Mexico") or s in _MEXICO_IANA:
        return MEXICO
    if s.startswith("America/"):
        return AMERICAS
    if s.startswith("Europe/"):
        return EUROPE
    return ROW


def _region_from_offset(value: int) -> str:
    """Convert JumpCloud-style numeric offset to a region bucket.

    Detection heuristic for the unit:
    - |value| <= 14         → plain hours (e.g. -6 = UTC-6)
    - |value| <= 1459 and ends in :MM ≤ 59 → HHMM (e.g. -600 = UTC-6:00,
      530 = UTC+5:30)
    - anything else         → UNKNOWN

    Only the hour component matters for the coarse region bucket, so we
    discard minutes after parsing.
    """
    abs_v = abs(value)
    if abs_v <= 14:
        hours = value
    elif abs_v <= 1459 and abs_v % 100 < 60:
        hours = value // 100  # truncate toward zero is fine; sign preserved
        # Edge: -600 // 100 in Python is -6 (floor), which happens to match
        # truncation here because -600 % 100 == 0. For values like -630,
        # int(-630 / 100) == -6 but -630 // 100 == -7 (floor). Use int(/) for
        # consistent truncation toward zero across signs.
        hours = int(value / 100)
    else:
        return UNKNOWN

    # México (no DST): CST = UTC-6, MST = UTC-7
    if hours in (-6, -7):
        return MEXICO
    # Other Americas: from Argentina/Brazil (UTC-3) to Hawaii (UTC-10),
    # excluding Mexico which we caught above.
    if -10 <= hours <= -3:
        return AMERICAS
    # Western Europe (UTC+0 winter / +1 summer) through Moscow (UTC+3).
    # We start at -1 to capture Azores / Cape Verde edge cases sometimes
    # used by Iberian / North African contractors.
    if -1 <= hours <= 3:
        return EUROPE
    return ROW
