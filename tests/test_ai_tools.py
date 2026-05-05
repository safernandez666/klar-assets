"""Tests for the AI tool dispatcher.

The chat endpoint exposes 4 tools (`list_devices`, `lookup_device_by_serial`,
`get_user_devices`, `get_summary`) that the model can call to query the live
DB. These tests pin:

- Each tool returns sensible data shape against a fixture DB.
- Bad arguments return a structured `error` rather than raising.
- Unknown tools return an error.
- Filters compose correctly (status + region + limit).
- Hardcoded enum validators reject unknown statuses / regions / sources.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.models import NormalizedDevice
from src.storage.repository import DeviceRepository
from src.web.api.ai_tools import (
    execute_tool,
    get_summary,
    get_user_devices,
    list_devices,
    lookup_device_by_serial,
)


NOW = datetime(2026, 5, 5, 12, 0, 0, tzinfo=timezone.utc)


def _device(
    canonical_id: str,
    serial: str | None = None,
    hostname: str = "h",
    owner_email: str | None = None,
    status: str = "MANAGED",
    sources: list[str] | None = None,
    region: str | None = "MEXICO",
    timezone_str: str | None = "-600",
) -> NormalizedDevice:
    return NormalizedDevice(
        canonical_id=canonical_id,
        hostnames=[hostname],
        serial_number=serial,
        sources=sources or ["jumpcloud"],
        owner_email=owner_email,
        status=status,
        region=region,
        timezone=timezone_str,
        first_seen=NOW,
        last_seen=NOW,
    )


@pytest.fixture
def repo(tmp_path):
    r = DeviceRepository(str(tmp_path / "test.db"))
    r.upsert_devices([
        _device("a", serial="SN001", hostname="alice-mac",
                owner_email="alice@klar.mx", status="FULLY_MANAGED",
                sources=["crowdstrike", "jumpcloud", "okta"], region="MEXICO"),
        _device("b", serial="SN002", hostname="bob-mac",
                owner_email="bob@klar.mx", status="NO_EDR",
                sources=["jumpcloud", "okta"], region="MEXICO"),
        _device("c", serial="SN003", hostname="charlie-mac",
                owner_email="charlie@klar.mx", status="NO_MDM",
                sources=["crowdstrike", "okta"], region="EUROPE",
                timezone_str="200"),
        _device("d", serial="SN004", hostname="server-1",
                owner_email=None, status="SERVER",
                sources=["crowdstrike"], region="UNKNOWN",
                timezone_str=None),
        _device("e", serial="SN005", hostname="alice-laptop",
                owner_email="alice@klar.mx", status="NO_EDR",
                sources=["jumpcloud", "okta"], region="MEXICO"),
    ])
    return r


# ── list_devices ──────────────────────────────────────────────────────

class TestListDevices:
    def test_no_filters_returns_all_up_to_limit(self, repo: DeviceRepository) -> None:
        out = list_devices(repo)
        assert out["count"] == 5
        # Default limit is 10, we only have 5 fixtures.
        assert len(out["devices"]) == 5

    def test_filter_by_status(self, repo: DeviceRepository) -> None:
        out = list_devices(repo, status="NO_EDR")
        assert out["count"] == 2
        assert all(d["status"] == "NO_EDR" for d in out["devices"])

    def test_filter_by_region(self, repo: DeviceRepository) -> None:
        out = list_devices(repo, region="EUROPE")
        assert out["count"] == 1
        assert out["devices"][0]["serial"] == "SN003"

    def test_filter_by_owner(self, repo: DeviceRepository) -> None:
        out = list_devices(repo, owner_email="alice@klar.mx")
        assert out["count"] == 2
        assert {d["serial"] for d in out["devices"]} == {"SN001", "SN005"}

    def test_filter_owner_is_case_insensitive(self, repo: DeviceRepository) -> None:
        out = list_devices(repo, owner_email="ALICE@KLAR.MX")
        assert out["count"] == 2

    def test_limit_is_capped_at_50(self, repo: DeviceRepository) -> None:
        out = list_devices(repo, limit=10000)
        assert out["limit"] == 50

    def test_invalid_status_returns_error(self, repo: DeviceRepository) -> None:
        out = list_devices(repo, status="BANANA")
        assert "error" in out

    def test_invalid_region_returns_error(self, repo: DeviceRepository) -> None:
        out = list_devices(repo, region="MARS")
        assert "error" in out


# ── lookup_device_by_serial ───────────────────────────────────────────

class TestLookupBySerial:
    def test_found(self, repo: DeviceRepository) -> None:
        out = lookup_device_by_serial(repo, serial="SN001")
        assert out["found"] is True
        assert out["owner"] == "alice@klar.mx"
        assert out["region"] == "MEXICO"

    def test_case_insensitive(self, repo: DeviceRepository) -> None:
        out = lookup_device_by_serial(repo, serial="sn001")
        assert out["found"] is True

    def test_not_found(self, repo: DeviceRepository) -> None:
        out = lookup_device_by_serial(repo, serial="DOESNOTEXIST")
        assert out["found"] is False

    def test_empty_serial(self, repo: DeviceRepository) -> None:
        out = lookup_device_by_serial(repo, serial="")
        assert "error" in out


# ── get_user_devices ──────────────────────────────────────────────────

class TestGetUserDevices:
    def test_user_with_two_devices(self, repo: DeviceRepository) -> None:
        out = get_user_devices(repo, email="alice@klar.mx")
        assert out["found"] is True
        assert out["count"] == 2

    def test_unknown_user(self, repo: DeviceRepository) -> None:
        out = get_user_devices(repo, email="nobody@klar.mx")
        assert out["found"] is False

    def test_empty_email(self, repo: DeviceRepository) -> None:
        out = get_user_devices(repo, email="")
        assert "error" in out


# ── get_summary ───────────────────────────────────────────────────────

class TestGetSummary:
    def test_summary_shape(self, repo: DeviceRepository) -> None:
        out = get_summary(repo)
        assert "by_status" in out
        assert "by_region" in out
        assert out["total"] == 5


# ── execute_tool dispatcher ───────────────────────────────────────────

class TestDispatcher:
    def test_known_tool(self, repo: DeviceRepository) -> None:
        out = execute_tool("get_summary", {}, repo)
        assert out["total"] == 5

    def test_unknown_tool(self, repo: DeviceRepository) -> None:
        out = execute_tool("delete_everything", {}, repo)
        assert "error" in out
        assert "Unknown tool" in out["error"]

    def test_bad_arguments_caught(self, repo: DeviceRepository) -> None:
        out = execute_tool("lookup_device_by_serial", {"wrong_field": "x"}, repo)
        assert "error" in out

    def test_arguments_passed_through(self, repo: DeviceRepository) -> None:
        out = execute_tool("list_devices", {"status": "NO_EDR", "limit": 1}, repo)
        assert out["count"] == 1
