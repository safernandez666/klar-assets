"""Unit tests for the region bucketing.

Coverage:
- IANA strings (CrowdStrike-style, in theory).
- Numeric offsets in plain hours (older JumpCloud agents: -6, 2, …).
- Numeric offsets in HHMM (newer JumpCloud agents: -600, 530, 200, …).
- Numeric strings (JumpCloud value persisted by collector as str).
- Edge cases: None, empty, garbage, very out-of-range values.
"""
from __future__ import annotations

import pytest

from src.normalizer.region import (
    AMERICAS,
    EUROPE,
    MEXICO,
    ROW,
    UNKNOWN,
    region_from_timezone,
)


class TestIanaStrings:
    @pytest.mark.parametrize("tz", [
        "America/Mexico_City",
        "America/Cancun",
        "America/Monterrey",
        "America/Tijuana",
        "America/Hermosillo",
        "America/Mazatlan",
    ])
    def test_mexico_iana(self, tz: str) -> None:
        assert region_from_timezone(tz) == MEXICO

    @pytest.mark.parametrize("tz,expected", [
        ("America/Argentina/Buenos_Aires", AMERICAS),
        ("America/Sao_Paulo", AMERICAS),
        ("America/New_York", AMERICAS),
        ("America/Los_Angeles", AMERICAS),
        ("Europe/Madrid", EUROPE),
        ("Europe/London", EUROPE),
        ("Asia/Tokyo", ROW),
        ("Africa/Cairo", ROW),
        ("Pacific/Auckland", ROW),
    ])
    def test_other_iana(self, tz: str, expected: str) -> None:
        assert region_from_timezone(tz) == expected


class TestNumericOffsetPlainHours:
    """Older JumpCloud agents return systemTimezone as plain hours."""

    @pytest.mark.parametrize("tz,expected", [
        (-6, MEXICO),     # CDMX (CST, no DST since 2022)
        (-7, MEXICO),     # MST (Tijuana / Hermosillo edge)
        (-3, AMERICAS),   # Argentina / Brazil
        (-5, AMERICAS),   # US Eastern / Bogotá
        (-8, AMERICAS),   # US Pacific
        (-10, AMERICAS),  # Hawaii / Alaska edge
        (0, EUROPE),      # UTC / Western Europe winter
        (1, EUROPE),      # CET
        (2, EUROPE),      # CEST / Eastern Europe winter
        (3, EUROPE),      # Moscow / Eastern Europe summer
        (5, ROW),         # Pakistan
        (8, ROW),         # China / Singapore
        (-12, ROW),       # International date line
    ])
    def test_hours(self, tz: int, expected: str) -> None:
        assert region_from_timezone(tz) == expected


class TestNumericOffsetHHMM:
    """Newer JumpCloud agents return HHMM (hours*100 + minutes)."""

    @pytest.mark.parametrize("tz,expected", [
        (-600, MEXICO),    # UTC-6:00 CDMX
        (-700, MEXICO),    # UTC-7:00 Tijuana
        (-300, AMERICAS),  # UTC-3:00 Argentina
        (-500, AMERICAS),  # UTC-5:00 US Eastern
        (-800, AMERICAS),  # UTC-8:00 US Pacific
        (100, EUROPE),     # UTC+1:00
        (200, EUROPE),     # UTC+2:00
        (300, EUROPE),     # UTC+3:00 Moscow
        (530, ROW),        # UTC+5:30 India
        (800, ROW),        # UTC+8:00 China
    ])
    def test_hhmm(self, tz: int, expected: str) -> None:
        assert region_from_timezone(tz) == expected


class TestNumericString:
    """Collector persists numeric offsets as strings; lookup must round-trip."""

    @pytest.mark.parametrize("tz,expected", [
        ("-600", MEXICO),
        ("-6", MEXICO),
        ("0", EUROPE),
        ("530", ROW),
        ("-300", AMERICAS),
    ])
    def test_numeric_strings(self, tz: str, expected: str) -> None:
        assert region_from_timezone(tz) == expected


class TestEdgeCases:
    @pytest.mark.parametrize("tz", [None, "", "   "])
    def test_empty_or_none_is_unknown(self, tz: str | None) -> None:
        assert region_from_timezone(tz) == UNKNOWN

    @pytest.mark.parametrize("tz", [
        "Foo/Bar",          # garbage IANA → ROW (any non-Americas/Europe IANA)
    ])
    def test_garbage_iana_is_row(self, tz: str) -> None:
        assert region_from_timezone(tz) == ROW

    @pytest.mark.parametrize("tz", [
        2000,    # |abs|=2000, ends in 00 but >1459 → unknown
        -9999,   # huge → unknown
    ])
    def test_out_of_range_is_unknown(self, tz: int) -> None:
        assert region_from_timezone(tz) == UNKNOWN

    def test_unknown_type_is_unknown(self) -> None:
        # Pydantic might pass a Pydantic-bound list or dict accidentally; we
        # don't crash and return UNKNOWN.
        assert region_from_timezone([1, 2]) == UNKNOWN  # type: ignore[arg-type]
