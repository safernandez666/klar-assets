from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from src.collectors.base import BaseCollector
from src.models import RawDevice
from src.normalizer.deduplicator import Deduplicator
from src.normalizer.enricher import Enricher
from src.sync_engine import SyncEngine


NOW = datetime(2026, 4, 22, 10, 0, 0, tzinfo=timezone.utc)


def _cs_device(
    aid: str = "aid-001",
    hostname: str = "LAPTOP-001",
    serial: str = "SN123",
    mac: str = "aa:bb:cc:dd:ee:01",
    last_user: str = "user@company.com",
) -> RawDevice:
    return RawDevice(
        device_id=aid,
        hostname=hostname,
        serial_number=serial,
        mac_addresses=[mac],
        os_type="Windows",
        os_version="10",
        last_user=last_user,
        last_seen=NOW,
        source="crowdstrike",
        source_device_id=aid,
        raw_data={},
    )


def _okta_device(
    okta_id: str = "okta-001",
    hostname: str = "LAPTOP-001",
    serial: str = "SN123",
    owner_email: str = "user@company.com",
    owner_name: str = "User",
) -> RawDevice:
    return RawDevice(
        device_id=okta_id,
        hostname=hostname,
        serial_number=serial,
        mac_addresses=[],
        os_type="Windows",
        os_version="",
        last_user=owner_email,
        last_seen=NOW,
        source="okta",
        source_device_id=okta_id,
        raw_data={
            "owner_email": owner_email,
            "owner_name": owner_name,
            "registered": True,
        },
    )


def _jc_device(
    jc_id: str = "jc-001",
    hostname: str = "laptop-001",
    serial: str = "SN123",
    mac: str = "aa:bb:cc:dd:ee:01",
    last_user: str = "user@company.com",
) -> RawDevice:
    return RawDevice(
        device_id=jc_id,
        hostname=hostname,
        serial_number=serial,
        mac_addresses=[mac],
        os_type="Windows",
        os_version="10",
        last_user=last_user,
        last_seen=NOW,
        source="jumpcloud",
        source_device_id=jc_id,
        raw_data={},
    )


class TestDeduplicator:
    def test_dedup_by_serial(self) -> None:
        """CS + Okta matched by serial → NO_MDM (has EDR+IDP but no MDM)."""
        devices = [
            _cs_device(serial="SN-SAME", mac="aa:bb:cc:dd:ee:01"),
            _okta_device(serial="SN-SAME", owner_email="user@company.com"),
        ]
        dedup = Deduplicator()
        enriched = Enricher().enrich(dedup.deduplicate(devices))
        assert len(enriched) == 1
        d = enriched[0]
        assert d.status == "NO_MDM"
        assert d.confidence_score == 0.85
        assert "crowdstrike" in d.sources
        assert "okta" in d.sources
        assert d.owner_email == "user@company.com"

    def test_dedup_by_mac(self) -> None:
        """CS + JC matched by MAC → MANAGED (has EDR + MDM)."""
        devices = [
            _cs_device(mac="aa:bb:cc:dd:ee:fa", serial="SN-CS"),
            _jc_device(mac="AA:BB:CC:DD:EE:FA", serial="SN-JC"),
        ]
        dedup = Deduplicator()
        enriched = Enricher().enrich(dedup.deduplicate(devices))
        assert len(enriched) == 1
        d = enriched[0]
        assert "crowdstrike" in d.sources
        assert "jumpcloud" in d.sources
        assert d.status == "MANAGED"
        assert "LAPTOP-001" in d.hostnames
        assert d.confidence_score == 0.8

    def test_fuzzy_hostname(self) -> None:
        """Hostname fuzzy match with suffix stripping, same OS."""
        devices = [
            RawDevice(
                device_id="cs-001",
                hostname="laptop-ARG",
                serial_number=None,
                mac_addresses=[],
                os_type="Windows",
                os_version="10",
                last_user="carlos@company.com",
                last_seen=NOW,
                source="crowdstrike",
                source_device_id="cs-001",
                raw_data={},
            ),
            RawDevice(
                device_id="okta-001",
                hostname="laptop",
                serial_number=None,
                mac_addresses=[],
                os_type="Windows",
                os_version="",
                last_user="carlos@company.com",
                last_seen=NOW,
                source="okta",
                source_device_id="okta-001",
                raw_data={"owner_email": "carlos@company.com", "registered": True},
            ),
        ]
        dedup = Deduplicator()
        result = dedup.deduplicate(devices)
        # These should match via owner_os:exact (same user + same OS)
        # or hostname fuzzy after suffix strip
        assert len(result) == 1
        d = Enricher().enrich(result)[0]
        assert d.confidence_score >= 0.4

    def test_no_mdm_status(self) -> None:
        """CS only → NO_MDM."""
        devices = [
            _cs_device(serial="SN-NOMDM", last_user=""),
        ]
        dedup = Deduplicator()
        enriched = Enricher().enrich(dedup.deduplicate(devices))
        assert len(enriched) == 1
        d = enriched[0]
        assert d.status == "NO_MDM"
        assert d.confidence_score == 0.2
        assert d.sources == ["crowdstrike"]

    def test_idp_only(self) -> None:
        """Okta only → IDP_ONLY (potential shadow IT)."""
        devices = [
            _okta_device(serial="SN-NOEDR", owner_email="mobile@company.com"),
        ]
        dedup = Deduplicator()
        enriched = Enricher().enrich(dedup.deduplicate(devices))
        assert len(enriched) == 1
        d = enriched[0]
        assert d.status == "IDP_ONLY"
        assert d.confidence_score == 0.2
        assert d.sources == ["okta"]

    def test_no_edr(self) -> None:
        """JumpCloud only → NO_EDR (MDM without EDR)."""
        devices = [
            _jc_device(jc_id="jc-solo", serial="SN-JC-ONLY", mac=""),
        ]
        dedup = Deduplicator()
        enriched = Enricher().enrich(dedup.deduplicate(devices))
        assert len(enriched) == 1
        d = enriched[0]
        assert d.status == "NO_EDR"
        assert d.sources == ["jumpcloud"]

    def test_low_confidence_different_os(self) -> None:
        """Two devices with different OS should NOT fuzzy-match."""
        devices = [
            RawDevice(
                device_id="cs-001",
                hostname="server-alpha",
                serial_number=None,
                mac_addresses=[],
                os_type="Linux",
                os_version="",
                last_user="",
                last_seen=NOW,
                source="crowdstrike",
                source_device_id="cs-001",
                raw_data={},
            ),
            RawDevice(
                device_id="jc-001",
                hostname="server-alpha",
                serial_number=None,
                mac_addresses=[],
                os_type="Windows",
                os_version="",
                last_user="",
                last_seen=NOW,
                source="jumpcloud",
                source_device_id="jc-001",
                raw_data={},
            ),
        ]
        dedup = Deduplicator()
        result = dedup.deduplicate(devices)
        # Same hostname but different OS → should NOT merge
        assert len(result) == 2

    def test_owner_os_cross_match(self) -> None:
        """Devices from different sources with same owner+OS merge when no serial conflict."""
        devices = [
            _cs_device(aid="cs-x", serial="", mac="", hostname="WS-CS-001",
                       last_user="shared@company.com"),
            _okta_device(okta_id="okta-x", serial="", hostname="User's Laptop",
                         owner_email="shared@company.com"),
        ]
        dedup = Deduplicator()
        result = dedup.deduplicate(devices)
        assert len(result) == 1
        d = result[0]
        assert "crowdstrike" in d.sources
        assert "okta" in d.sources
        assert d.match_reason == "owner_os:exact"

    def test_owner_os_no_merge_different_serials(self) -> None:
        """Devices with same owner+OS but different serials should NOT merge."""
        devices = [
            _cs_device(aid="cs-x", serial="SN-AAA", mac="", hostname="WS-CS-001",
                       last_user="shared@company.com"),
            _okta_device(okta_id="okta-x", serial="SN-BBB", hostname="User's Laptop",
                         owner_email="shared@company.com"),
        ]
        dedup = Deduplicator()
        result = dedup.deduplicate(devices)
        assert len(result) == 2

    def test_source_failure(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        engine = SyncEngine(db_path)
        for collector in engine.collectors:
            collector.collect = lambda: []  # type: ignore[method-assign]
        engine.collectors[0].collect = lambda: [  # type: ignore[method-assign]
            _cs_device(serial="SN-TEST", last_user="test@company.com")
        ]
        result = engine.run()
        assert result["final_count"] >= 0
        assert result["status"] in ("success", "partial")

    def test_fully_managed_three_sources(self) -> None:
        """CS + Okta + JC matched by serial → FULLY_MANAGED with confidence 1.0."""
        devices = [
            _cs_device(serial="SN-3SRC", mac="aa:bb:cc:dd:ee:99"),
            _okta_device(serial="SN-3SRC", owner_email="user@company.com"),
            _jc_device(serial="SN-3SRC", mac="AA:BB:CC:DD:EE:99"),
        ]
        dedup = Deduplicator()
        enriched = Enricher().enrich(dedup.deduplicate(devices))
        assert len(enriched) == 1
        d = enriched[0]
        assert d.confidence_score == 1.0
        assert "crowdstrike" in d.sources
        assert "okta" in d.sources
        assert "jumpcloud" in d.sources
        assert d.status == "FULLY_MANAGED"

    def test_managed_jc_cs(self) -> None:
        """JC + CS matched by serial → MANAGED (MDM + EDR, no IDP)."""
        devices = [
            _cs_device(serial="SN-JCCS", mac="aa:bb:cc:dd:ee:77"),
            _jc_device(serial="SN-JCCS", mac="AA:BB:CC:DD:EE:77"),
        ]
        dedup = Deduplicator()
        enriched = Enricher().enrich(dedup.deduplicate(devices))
        assert len(enriched) == 1
        d = enriched[0]
        assert d.status == "MANAGED"
        assert "crowdstrike" in d.sources
        assert "jumpcloud" in d.sources

    def test_similar_hostnames_dont_merge(self) -> None:
        """KLAR-AR-001 and KLAR-AR-002 should NOT merge despite similarity."""
        devices = [
            RawDevice(
                device_id="cs-001",
                hostname="KLAR-AR-001",
                serial_number=None,
                mac_addresses=[],
                os_type="Windows",
                os_version="10",
                last_user="user1@company.com",
                last_seen=NOW,
                source="crowdstrike",
                source_device_id="cs-001",
                raw_data={},
            ),
            RawDevice(
                device_id="cs-002",
                hostname="KLAR-AR-002",
                serial_number=None,
                mac_addresses=[],
                os_type="Windows",
                os_version="10",
                last_user="user2@company.com",
                last_seen=NOW,
                source="crowdstrike",
                source_device_id="cs-002",
                raw_data={},
            ),
        ]
        dedup = Deduplicator()
        result = dedup.deduplicate(devices)
        assert len(result) == 2

    def test_owner_priority_jc_over_okta(self) -> None:
        """JumpCloud user takes priority over Okta binding for owner."""
        devices = [
            _cs_device(serial="SN-PRIO", last_user="cs-user@company.com"),
            _okta_device(serial="SN-PRIO", owner_email="okta-user@company.com"),
            _jc_device(serial="SN-PRIO", last_user="jc-user@company.com"),
        ]
        dedup = Deduplicator()
        result = dedup.deduplicate(devices)
        assert len(result) == 1
        d = result[0]
        assert d.owner_email == "jc-user@company.com"

    def test_mobile_devices_filtered(self) -> None:
        """Mobile devices (iOS/Android) should be excluded from analysis."""
        devices = [
            _cs_device(serial="SN-DESKTOP"),
            RawDevice(
                device_id="okta-mobile",
                hostname="iPhone de Juan",
                serial_number=None,
                mac_addresses=[],
                os_type="iOS",
                os_version="17",
                last_user="juan@company.com",
                last_seen=NOW,
                source="okta",
                source_device_id="okta-mobile",
                raw_data={},
            ),
            RawDevice(
                device_id="okta-android",
                hostname="OPPO A58",
                serial_number=None,
                mac_addresses=[],
                os_type="ANDROID",
                os_version="14",
                last_user="maria@company.com",
                last_seen=NOW,
                source="okta",
                source_device_id="okta-android",
                raw_data={},
            ),
        ]
        dedup = Deduplicator()
        result = dedup.deduplicate(devices)
        # Only the desktop device should remain
        assert len(result) == 1
        assert "crowdstrike" in result[0].sources
