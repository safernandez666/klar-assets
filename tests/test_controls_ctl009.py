"""Tests for CTL-009 — per-source agent dormancy.

CTL-009 catches the scenario where a device looks healthy at the merged
level (one source recently reporting it) but at least one source's agent
hasn't been seen in 10+ days. Concrete example: Mac with JumpCloud agent
alive but CrowdStrike agent dead.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.models import NormalizedDevice
from src.storage.repository import DeviceRepository
from src.web.api.controls import router as controls_router


NOW = datetime(2026, 5, 7, 12, 0, 0, tzinfo=timezone.utc)


def _device(
    canonical_id: str,
    *,
    sources: list[str],
    source_last_seen: dict[str, str] | None = None,
    status: str = "FULLY_MANAGED",
    serial: str = "SN1",
    hostname: str = "host",
) -> NormalizedDevice:
    return NormalizedDevice(
        canonical_id=canonical_id,
        hostnames=[hostname],
        serial_number=serial,
        sources=sources,
        source_last_seen=source_last_seen or {},
        status=status,
        first_seen=NOW,
        last_seen=NOW,
    )


@pytest.fixture
def app_with_repo(tmp_path):
    repo = DeviceRepository(str(tmp_path / "test.db"))
    app = FastAPI()
    app.include_router(controls_router)
    from src.web.dependencies import get_repo
    app.dependency_overrides[get_repo] = lambda: repo
    return app, repo


def _ctl(body: dict, ctl_id: str) -> dict:
    return next(c for c in body["controls"] if c["id"] == ctl_id)


# ── CTL-009 detection ─────────────────────────────────────────────────

class TestCTL009Detection:
    def test_passes_when_all_sources_fresh(self, app_with_repo) -> None:
        app, repo = app_with_repo
        repo.upsert_devices([
            _device("a", sources=["crowdstrike", "jumpcloud", "okta"],
                    source_last_seen={
                        "crowdstrike": NOW.isoformat(),
                        "jumpcloud":   NOW.isoformat(),
                        "okta":        NOW.isoformat(),
                    }),
        ])
        with TestClient(app) as client:
            r = client.get("/api/controls").json()
        ctl = _ctl(r, "CTL-009")
        assert ctl["status"] == "pass"
        assert ctl["affected"] == 0
        assert ctl["devices"] == []

    def test_detects_dormant_cs_agent_with_jc_alive(self, app_with_repo) -> None:
        """The Elias case: JC agent alive, CS dead 30 days. CTL-007/008
        miss it (merged last_seen recent); CTL-009 catches it."""
        app, repo = app_with_repo
        old = (NOW - timedelta(days=30)).isoformat()
        fresh = NOW.isoformat()
        repo.upsert_devices([
            _device("elias",
                    sources=["crowdstrike", "jumpcloud", "okta"],
                    source_last_seen={
                        "crowdstrike": old,    # ← dormant
                        "jumpcloud":   fresh,
                        "okta":        fresh,
                    }),
        ])
        with TestClient(app) as client:
            r = client.get("/api/controls").json()
        ctl = _ctl(r, "CTL-009")
        assert ctl["status"] == "fail"
        assert ctl["affected"] == 1
        assert ctl["devices"][0]["stale_sources"] == ["crowdstrike"]
        assert ctl["devices"][0]["stale_detail"]["crowdstrike"] == old

    def test_threshold_is_configurable_via_env(self, app_with_repo, monkeypatch) -> None:
        """Lowering the threshold catches devices the default would let pass."""
        # Reload module-level constant by reimporting the route module.
        import importlib

        import src.web.config as cfg_mod
        import src.web.api.controls as ctrl_mod

        monkeypatch.setenv("STALE_SOURCE_THRESHOLD_DAYS", "3")
        importlib.reload(cfg_mod)
        importlib.reload(ctrl_mod)

        # Re-mount with the reloaded router (the original fixture used the
        # old router object).
        from src.web.dependencies import get_repo
        app2 = FastAPI()
        app2.include_router(ctrl_mod.router)
        app2.dependency_overrides[get_repo] = lambda: app_with_repo[1]

        app_with_repo[1].upsert_devices([
            _device("d",
                    sources=["crowdstrike", "jumpcloud"],
                    source_last_seen={
                        "crowdstrike": (NOW - timedelta(days=5)).isoformat(),
                        "jumpcloud":   NOW.isoformat(),
                    }),
        ])
        with TestClient(app2) as client:
            r = client.get("/api/controls").json()
        ctl = _ctl(r, "CTL-009")
        # 5 days > 3-day threshold → flagged
        assert ctl["status"] == "fail"
        assert "crowdstrike" in ctl["devices"][0]["stale_sources"]

        # Restore env for other tests
        monkeypatch.delenv("STALE_SOURCE_THRESHOLD_DAYS", raising=False)
        importlib.reload(cfg_mod)
        importlib.reload(ctrl_mod)

    def test_skips_devices_with_no_source_last_seen(self, app_with_repo) -> None:
        """Older rows pre-migration have empty dict — CTL-009 should not
        crash, just skip them. CTL-007/008 cover those cases generally."""
        app, repo = app_with_repo
        repo.upsert_devices([
            _device("legacy", sources=["jumpcloud"], source_last_seen={}),
        ])
        with TestClient(app) as client:
            r = client.get("/api/controls").json()
        ctl = _ctl(r, "CTL-009")
        assert ctl["status"] == "pass"
        assert ctl["affected"] == 0

    def test_lists_multiple_stale_sources(self, app_with_repo) -> None:
        """If a device has two dormant sources, both must show up in
        ``stale_sources``."""
        app, repo = app_with_repo
        old = (NOW - timedelta(days=60)).isoformat()
        repo.upsert_devices([
            _device("zombie",
                    sources=["crowdstrike", "jumpcloud", "okta"],
                    source_last_seen={
                        "crowdstrike": old,
                        "jumpcloud":   old,
                        "okta":        NOW.isoformat(),
                    }),
        ])
        with TestClient(app) as client:
            r = client.get("/api/controls").json()
        ctl = _ctl(r, "CTL-009")
        assert ctl["affected"] == 1
        assert sorted(ctl["devices"][0]["stale_sources"]) == ["crowdstrike", "jumpcloud"]

    def test_excludes_servers(self, app_with_repo) -> None:
        """CTL-009 follows the same active-device filter as the other CTLs:
        SERVER status is excluded (often expected to drift)."""
        app, repo = app_with_repo
        repo.upsert_devices([
            _device("svr",
                    sources=["crowdstrike", "jumpcloud"],
                    status="SERVER",
                    source_last_seen={
                        "crowdstrike": (NOW - timedelta(days=60)).isoformat(),
                        "jumpcloud":   NOW.isoformat(),
                    }),
        ])
        with TestClient(app) as client:
            r = client.get("/api/controls").json()
        ctl = _ctl(r, "CTL-009")
        assert ctl["status"] == "pass"
        assert ctl["affected"] == 0

    def test_response_includes_threshold_days(self, app_with_repo) -> None:
        """The UI needs to know what threshold was used so it can label
        the control accurately (e.g., '10 días' vs '3 días')."""
        app, _ = app_with_repo
        with TestClient(app) as client:
            r = client.get("/api/controls").json()
        ctl = _ctl(r, "CTL-009")
        assert "threshold_days" in ctl
        assert isinstance(ctl["threshold_days"], int)
