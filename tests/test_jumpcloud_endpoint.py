"""Tests for the on-demand JumpCloud reconcile-displaynames endpoint.

The endpoint:
- Returns 503 if ``JC_API_KEY`` is unset (no fallback behavior).
- Walks the persisted device list (no source re-collect).
- Picks JC-sourced devices whose hostname starts with ``KLR-``.
- Calls live JC ``GET /systems/{id}`` for each candidate.
- Hands the result + devices to ``reconcile_displaynames``.
- Returns the same summary the in-sync reconciler returns.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.models import NormalizedDevice
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


@pytest.fixture
def app_with_repo(tmp_path):
    """FastAPI app with the jumpcloud router and a fresh repo dependency."""
    repo = DeviceRepository(str(tmp_path / "test.db"))
    repo.upsert_devices([
        _device("a", ["KLR-MXM-DG27"], ["jumpcloud"], jc_id="jc1", serial="DG27"),
        _device("b", ["KLR-ARM-X4FV"], ["jumpcloud"], jc_id="jc2", serial="X4FV"),
        _device("c", ["legacy.local"], ["jumpcloud"], jc_id="jc3", serial="OLD1"),  # not KLR-*
        _device("d", ["KLR-MXM-NOID"], ["jumpcloud"], jc_id=None),                  # no jc_id
        _device("e", ["KLR-MXM-NOSRC"], ["crowdstrike"]),                           # not jumpcloud
    ])

    app = FastAPI()
    app.include_router(jumpcloud_router)
    app.dependency_overrides = {}

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


# ── happy path ────────────────────────────────────────────────────────

class TestReconcileEndpoint:
    def test_only_klr_jc_devices_are_candidates(self, app_with_repo, monkeypatch) -> None:
        app, _ = app_with_repo
        monkeypatch.setenv("JC_API_KEY", "fake-key")

        captured_ids: list[str] = []

        def fake_fetch(system_ids, *, api_key):
            captured_ids.extend(system_ids)
            return {sid: "stale-name" for sid in system_ids}

        with patch("src.web.api.jumpcloud.fetch_jc_displaynames_live", side_effect=fake_fetch), \
             patch("src.web.api.jumpcloud.reconcile_displaynames",
                   return_value={"scanned": 5, "drifted": 2, "updated": 2,
                                 "failed": 0, "capped": 0, "dry_run": False}):
            with TestClient(app) as client:
                r = client.post("/api/jumpcloud/reconcile-displaynames")

        assert r.status_code == 200
        # Only jc1 and jc2 qualify: KLR-* hostname AND jumpcloud source AND jc_id present.
        # jc3 has non-KLR hostname; "d" has no jc_id; "e" has no jumpcloud source.
        assert sorted(captured_ids) == ["jc1", "jc2"]

    def test_returns_reconciler_summary_with_candidates(self, app_with_repo, monkeypatch) -> None:
        app, _ = app_with_repo
        monkeypatch.setenv("JC_API_KEY", "fake-key")

        with patch("src.web.api.jumpcloud.fetch_jc_displaynames_live",
                   return_value={"jc1": "old", "jc2": "KLR-ARM-X4FV"}), \
             patch("src.web.api.jumpcloud.reconcile_displaynames",
                   return_value={"scanned": 5, "drifted": 1, "updated": 1,
                                 "failed": 0, "capped": 0, "dry_run": False}):
            with TestClient(app) as client:
                r = client.post("/api/jumpcloud/reconcile-displaynames")

        body = r.json()
        assert body["scanned"] == 5
        assert body["drifted"] == 1
        assert body["updated"] == 1
        assert body["candidates"] == 2  # endpoint adds this field

    def test_no_klr_devices_short_circuits_cleanly(self, tmp_path, monkeypatch) -> None:
        """An empty fleet (or no KLR-* devices) returns a no-op summary
        without error."""
        repo = DeviceRepository(str(tmp_path / "empty.db"))
        repo.upsert_devices([
            _device("z", ["legacy.local"], ["jumpcloud"], jc_id="jc-only"),
        ])

        app = FastAPI()
        app.include_router(jumpcloud_router)
        from src.web.dependencies import get_repo
        app.dependency_overrides[get_repo] = lambda: repo

        monkeypatch.setenv("JC_API_KEY", "fake-key")

        with patch("src.web.api.jumpcloud.fetch_jc_displaynames_live",
                   return_value={}) as fetch_mock, \
             patch("src.web.api.jumpcloud.reconcile_displaynames",
                   return_value={"scanned": 1, "drifted": 0, "updated": 0,
                                 "failed": 0, "capped": 0, "dry_run": False}):
            with TestClient(app) as client:
                r = client.post("/api/jumpcloud/reconcile-displaynames")

        assert r.status_code == 200
        # No KLR-* candidates → fetch should be called with empty list
        fetch_mock.assert_called_once()
        called_with = list(fetch_mock.call_args[0][0])
        assert called_with == []
        body = r.json()
        assert body["candidates"] == 0
