"""Tests for the by_region aggregation in DeviceRepository.get_summary().

Region is derived per-device by the deduplicator from the IANA timezone
string. The summary endpoint feeds the dashboard "By Region" pie chart, so
the aggregation needs to:
- bucket each non-server device into its region label
- exclude SERVER status (cloud servers in AWS regions would dominate)
- coalesce missing/null region values into "UNKNOWN"
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.models import NormalizedDevice
from src.storage.repository import DeviceRepository


NOW = datetime(2026, 5, 4, 0, 0, 0, tzinfo=timezone.utc)


def _device(canonical_id: str, region: str | None, status: str = "MANAGED") -> NormalizedDevice:
    return NormalizedDevice(
        canonical_id=canonical_id,
        hostnames=[f"host-{canonical_id}"],
        sources=["crowdstrike"],
        status=status,
        first_seen=NOW,
        last_seen=NOW,
        region=region,
    )


@pytest.fixture
def repo(tmp_path):
    return DeviceRepository(str(tmp_path / "test.db"))


def test_by_region_buckets_endpoints(repo) -> None:
    repo.upsert_devices([
        _device("a", "MEXICO"),
        _device("b", "MEXICO"),
        _device("c", "AMERICAS"),
        _device("d", "EUROPE"),
        _device("e", "ROW"),
    ])
    summary = repo.get_summary()
    assert summary["by_region"] == {"MEXICO": 2, "AMERICAS": 1, "EUROPE": 1, "ROW": 1}


def test_by_region_excludes_servers(repo) -> None:
    """Servers in AWS regions would otherwise drown out the user fleet."""
    repo.upsert_devices([
        _device("user-mx", "MEXICO", status="MANAGED"),
        _device("server-us", "AMERICAS", status="SERVER"),
        _device("server-eu", "EUROPE", status="SERVER"),
    ])
    summary = repo.get_summary()
    assert summary["by_region"] == {"MEXICO": 1}


def test_by_region_coalesces_null_to_unknown(repo) -> None:
    """Devices whose source agents never reported a timezone end up in
    UNKNOWN, not silently dropped from the chart."""
    repo.upsert_devices([
        _device("tz-known", "MEXICO"),
        _device("tz-missing", None),
    ])
    summary = repo.get_summary()
    assert summary["by_region"]["MEXICO"] == 1
    assert summary["by_region"]["UNKNOWN"] == 1


def test_by_region_present_when_no_devices(repo) -> None:
    summary = repo.get_summary()
    assert "by_region" in summary
    assert summary["by_region"] == {}
