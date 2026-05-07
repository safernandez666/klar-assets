"""Tests for the on-demand JumpCloud refresh endpoint.

The endpoint:
- Returns 503 if ``JC_API_KEY`` is unset.
- Returns 502 if the JumpCloud collector fails.
- Otherwise:
  1. Re-collects from JC only.
  2. Patches each existing DB row whose serial matches a fresh JC RawDevice
     (prepends the new hostname, refreshes ``source_ids[jumpcloud]`` and
     ``last_seen``).
  3. Hands the updated device list + fresh JC raw_data displaynames to
     ``reconcile_displaynames``.
  4. Refreshes the in-memory cache.
- Returns a summary that surfaces both phases (jc_collected,
  devices_refreshed, new_hostnames) on top of the reconciler counts.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.collectors.base import CollectResult
from src.models import NormalizedDevice, RawDevice
from src.storage.repository import DeviceRepository
from src.web.api.jumpcloud import router as jumpcloud_router


NOW = datetime(2026, 5, 7, 12, 0, 0, tzinfo=timezone.utc)


def _device(
    canonical_id: str,
    hostnames: list[str],
    sources: list[str],
    jc_id: str | None = None,
    serial: str | None = None,
) -> NormalizedDevice:
    source_ids: dict[str, str] = {}
    if jc_id is not None:
        source_ids["jumpcloud"] = jc_id
    return NormalizedDevice(
        canonical_id=canonical_id,
        hostnames=hostnames,
        sources=sources,
        source_ids=source_ids,
        serial_number=serial,
        first_seen=NOW,
        last_seen=NOW,
    )


def _raw_jc(
    serial: str,
    hostname: str,
    sid: str,
    *,
    display_name: str | None = None,
) -> RawDevice:
    return RawDevice(
        device_id=sid,
        hostname=hostname,
        serial_number=serial,
        source="jumpcloud",
        source_device_id=sid,
        last_seen=NOW,
        raw_data={"displayName": display_name or hostname},
    )


@pytest.fixture
def app_with_repo(tmp_path):
    """FastAPI app + a fresh DeviceRepository with seeded fixture rows."""
    repo = DeviceRepository(str(tmp_path / "test.db"))
    repo.upsert_devices([
        _device("a", ["old-jc-name.local"], ["jumpcloud"], jc_id="jc1", serial="DG27"),
        _device("b", ["KLR-ARM-X4FV"],     ["jumpcloud"], jc_id="jc2", serial="X4FV"),
        _device("c", ["legacy.local"],     ["crowdstrike"], serial="ONLY-CS"),
    ])

    app = FastAPI()
    app.include_router(jumpcloud_router)

    from src.web.dependencies import get_repo
    app.dependency_overrides[get_repo] = lambda: repo
    return app, repo


# ── 503 when no API key ───────────────────────────────────────────────

class TestNoApiKey:
    def test_returns_503_when_jc_api_key_missing(self, app_with_repo, monkeypatch) -> None:
        app, _ = app_with_repo
        monkeypatch.delenv("JC_API_KEY", raising=False)
        with TestClient(app) as client:
            r = client.post("/api/jumpcloud/reconcile-displaynames")
        assert r.status_code == 503
        body = r.json()
        assert "JC_API_KEY not configured" in body["error"]
        assert body["scanned"] == 0
        assert body["jc_collected"] == 0


# ── 502 when JC collector fails ───────────────────────────────────────

class TestCollectorFailure:
    def test_returns_502_when_jc_collect_fails(self, app_with_repo, monkeypatch) -> None:
        app, _ = app_with_repo
        monkeypatch.setenv("JC_API_KEY", "fake-key")

        # Build a CollectResult tolerant of both shapes (with/without `error`).
        try:
            bad_result = CollectResult(devices=[], success=False, error="rate_limited")
            expect_detail = "rate_limited"
        except TypeError:
            bad_result = CollectResult(devices=[], success=False)
            expect_detail = "unknown"

        with patch("src.web.api.jumpcloud.JumpCloudCollector") as MockCollector:
            instance = MockCollector.return_value
            instance.safe_collect.return_value = bad_result
            with TestClient(app) as client:
                r = client.post("/api/jumpcloud/reconcile-displaynames")

        assert r.status_code == 502
        body = r.json()
        assert "JumpCloud collection failed" in body["error"]
        assert expect_detail in body["error"]


# ── happy path ────────────────────────────────────────────────────────

class TestRefreshEndpoint:
    def test_merges_fresh_hostnames_into_existing_rows(self, app_with_repo, monkeypatch) -> None:
        app, repo = app_with_repo
        monkeypatch.setenv("JC_API_KEY", "fake-key")

        fresh = [
            _raw_jc("DG27", "KLR-MXM-DG27", "jc1", display_name="KLR-MXM-DG27"),
            _raw_jc("X4FV", "KLR-ARM-X4FV", "jc2", display_name="KLR-ARM-X4FV"),
        ]
        good_result = CollectResult(devices=fresh, success=True)

        # Mock cache.refresh to a no-op (cache is fragile in tests).
        with patch("src.web.api.jumpcloud.JumpCloudCollector") as MockCollector, \
             patch("src.web.api.jumpcloud.get_cache") as MockCache:
            MockCollector.return_value.safe_collect.return_value = good_result
            MockCache.return_value.refresh = MagicMock()

            with TestClient(app) as client:
                r = client.post("/api/jumpcloud/reconcile-displaynames")

        assert r.status_code == 200
        body = r.json()
        assert body["jc_collected"] == 2
        assert body["devices_refreshed"] == 2

        # DG27's row had old-jc-name.local; the fresh KLR-MXM-DG27 should now be
        # at hostnames[0] with the old name still present as secondary.
        rows = repo.get_all_devices()
        dg27 = [r for r in rows if r.get("serial_number") == "DG27"][0]
        assert dg27["hostnames"][0] == "KLR-MXM-DG27"
        assert "old-jc-name.local" in dg27["hostnames"]

        # X4FV already had KLR-ARM-X4FV — no new hostname added, just dedupe.
        x4fv = [r for r in rows if r.get("serial_number") == "X4FV"][0]
        assert x4fv["hostnames"] == ["KLR-ARM-X4FV"]

    def test_skips_devices_not_in_fresh_collection(self, app_with_repo, monkeypatch) -> None:
        """If JC's collect doesn't return a serial we have in DB, that row
        is left alone (no spurious updates, no errors)."""
        app, repo = app_with_repo
        monkeypatch.setenv("JC_API_KEY", "fake-key")

        # Only return DG27 — X4FV and ONLY-CS are not in fresh collection
        fresh = [_raw_jc("DG27", "KLR-MXM-DG27", "jc1")]
        good_result = CollectResult(devices=fresh, success=True)

        with patch("src.web.api.jumpcloud.JumpCloudCollector") as MockCollector, \
             patch("src.web.api.jumpcloud.get_cache") as MockCache:
            MockCollector.return_value.safe_collect.return_value = good_result
            MockCache.return_value.refresh = MagicMock()
            with TestClient(app) as client:
                r = client.post("/api/jumpcloud/reconcile-displaynames")

        body = r.json()
        assert body["devices_refreshed"] == 1  # only DG27

        rows = repo.get_all_devices()
        x4fv = [r for r in rows if r.get("serial_number") == "X4FV"][0]
        # Untouched
        assert x4fv["hostnames"] == ["KLR-ARM-X4FV"]
        cs_only = [r for r in rows if r.get("serial_number") == "ONLY-CS"][0]
        assert cs_only["hostnames"] == ["legacy.local"]

    def test_summary_includes_phase_counters_and_reconcile_summary(
        self, app_with_repo, monkeypatch
    ) -> None:
        """Response is a single dict that combines the JC-collect phase and
        the reconciler phase, so the UI can compose one toast."""
        app, _ = app_with_repo
        monkeypatch.setenv("JC_API_KEY", "fake-key")

        fresh = [_raw_jc("DG27", "KLR-MXM-DG27", "jc1")]

        with patch("src.web.api.jumpcloud.JumpCloudCollector") as MockCollector, \
             patch("src.web.api.jumpcloud.reconcile_displaynames",
                   return_value={"scanned": 3, "drifted": 1, "updated": 1,
                                 "failed": 0, "capped": 0, "dry_run": False}), \
             patch("src.web.api.jumpcloud.get_cache") as MockCache:
            MockCollector.return_value.safe_collect.return_value = CollectResult(
                devices=fresh, success=True)
            MockCache.return_value.refresh = MagicMock()
            with TestClient(app) as client:
                r = client.post("/api/jumpcloud/reconcile-displaynames")

        body = r.json()
        assert body["jc_collected"] == 1
        assert body["devices_refreshed"] == 1
        assert body["new_hostnames"] == 1   # DG27 had old-jc-name.local
        assert body["scanned"] == 3
        assert body["drifted"] == 1
        assert body["updated"] == 1
        assert "candidates" in body

    def test_cache_refresh_failure_does_not_break_response(
        self, app_with_repo, monkeypatch
    ) -> None:
        """If cache.refresh() raises, the response still succeeds — the
        actual reconciliation already happened."""
        app, _ = app_with_repo
        monkeypatch.setenv("JC_API_KEY", "fake-key")

        with patch("src.web.api.jumpcloud.JumpCloudCollector") as MockCollector, \
             patch("src.web.api.jumpcloud.get_cache") as MockCache:
            MockCollector.return_value.safe_collect.return_value = CollectResult(
                devices=[], success=True)
            MockCache.return_value.refresh.side_effect = RuntimeError("cache boom")
            with TestClient(app) as client:
                r = client.post("/api/jumpcloud/reconcile-displaynames")

        assert r.status_code == 200


# ── repo.update_device_jc_view ────────────────────────────────────────

class TestRepoUpdate:
    def test_update_device_jc_view_persists_new_hostnames(self, tmp_path) -> None:
        repo = DeviceRepository(str(tmp_path / "test.db"))
        repo.upsert_devices([
            _device("d1", ["old.local"], ["jumpcloud"], jc_id="jc-old", serial="S1"),
        ])
        ok = repo.update_device_jc_view(
            "d1",
            hostnames=["KLR-XXX-NEW", "old.local"],
            source_ids={"jumpcloud": "jc-new"},
            last_seen=NOW,
        )
        assert ok is True
        rows = repo.get_all_devices()
        assert isinstance(rows, list)
        assert rows[0]["hostnames"] == ["KLR-XXX-NEW", "old.local"]
        assert rows[0]["source_ids"]["jumpcloud"] == "jc-new"

    def test_update_device_jc_view_returns_false_for_unknown_id(self, tmp_path) -> None:
        repo = DeviceRepository(str(tmp_path / "test.db"))
        ok = repo.update_device_jc_view(
            "does-not-exist",
            hostnames=["x"],
            source_ids={},
        )
        assert ok is False
