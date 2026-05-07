"""Tests for the JumpCloud `displayName` reconciler.

The reconciler runs at the tail of every sync. It:

- Skips devices not sourced from JumpCloud
- Skips devices whose canonical hostname doesn't match KLR-*
- Skips devices whose JC `displayName` already matches the canonical name
- Caps the number of PUTs per run (safety against runaway updates)
- Can be disabled via env (`JC_RECONCILE_DISPLAYNAMES=0`)
- Skips when `JC_API_KEY` is unset
- Treats every HTTP failure as best-effort (logged, not raised)
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

import pytest
import requests

from src.jumpcloud_reconciler import (
    find_drift,
    jc_displaynames_from_raw,
    reconcile_displaynames,
)
from src.models import NormalizedDevice, RawDevice


NOW = datetime(2026, 5, 7, 12, 0, 0, tzinfo=timezone.utc)


def _device(
    canonical_id: str,
    hostnames: list[str],
    sources: list[str],
    jc_id: str | None = None,
) -> NormalizedDevice:
    source_ids: dict[str, str] = {}
    if jc_id is not None:
        source_ids["jumpcloud"] = jc_id
    return NormalizedDevice(
        canonical_id=canonical_id,
        hostnames=hostnames,
        sources=sources,
        source_ids=source_ids,
        first_seen=NOW,
        last_seen=NOW,
    )


# ── find_drift ────────────────────────────────────────────────────────

class TestFindDrift:
    def test_klr_hostname_with_stale_displayname_drifts(self) -> None:
        d = _device("a", ["KLR-MXM-DG27"], ["jumpcloud"], jc_id="jc1")
        out = find_drift([d], {"jc1": "Gastons-MacBook-Pro.local"})
        assert out == [("jc1", "Gastons-MacBook-Pro.local", "KLR-MXM-DG27", "a")]

    def test_already_in_sync_does_not_drift(self) -> None:
        d = _device("a", ["KLR-MXM-DG27"], ["jumpcloud"], jc_id="jc1")
        out = find_drift([d], {"jc1": "KLR-MXM-DG27"})
        assert out == []

    def test_no_klr_hostname_is_skipped(self) -> None:
        d = _device("a", ["legacy-hostname.local"], ["jumpcloud"], jc_id="jc1")
        out = find_drift([d], {"jc1": "anything"})
        assert out == []

    def test_no_jc_source_is_skipped(self) -> None:
        d = _device("a", ["KLR-MXM-DG27"], ["crowdstrike"], jc_id=None)
        out = find_drift([d], {})
        assert out == []

    def test_jc_source_but_no_jc_id_is_skipped(self) -> None:
        d = _device("a", ["KLR-MXM-DG27"], ["jumpcloud"], jc_id=None)
        out = find_drift([d], {})
        assert out == []

    def test_first_klr_hostname_wins_when_multiple(self) -> None:
        d = _device("a", ["KLR-MXM-AAAA", "KLR-MXM-BBBB"], ["jumpcloud"], jc_id="jc1")
        out = find_drift([d], {"jc1": "old"})
        assert out[0][2] == "KLR-MXM-AAAA"

    def test_whitespace_in_displayname_is_normalized(self) -> None:
        d = _device("a", ["KLR-MXM-DG27"], ["jumpcloud"], jc_id="jc1")
        out = find_drift([d], {"jc1": "  KLR-MXM-DG27  "})
        assert out == []

    def test_missing_jc_id_in_displaynames_treated_as_drift(self) -> None:
        # JC was unreachable at collect time → unknown displayName → safe default to "" → drift
        d = _device("a", ["KLR-MXM-DG27"], ["jumpcloud"], jc_id="jc-missing")
        out = find_drift([d], {})
        assert out and out[0][1] == ""


# ── reconcile_displaynames ────────────────────────────────────────────

class TestReconcile:
    def test_skipped_when_no_api_key(self, monkeypatch) -> None:
        monkeypatch.delenv("JC_API_KEY", raising=False)
        d = _device("a", ["KLR-MXM-DG27"], ["jumpcloud"], jc_id="jc1")
        out = reconcile_displaynames([d], {"jc1": "old"}, api_key=None)
        assert out["reason"] == "no_api_key"
        assert out["updated"] == 0

    def test_skipped_when_disabled_env(self, monkeypatch) -> None:
        monkeypatch.setenv("JC_RECONCILE_DISPLAYNAMES", "0")
        d = _device("a", ["KLR-MXM-DG27"], ["jumpcloud"], jc_id="jc1")
        out = reconcile_displaynames([d], {"jc1": "old"}, api_key="fake")
        assert out["reason"] == "disabled"
        assert out["updated"] == 0

    def test_no_drift_returns_zero_updates_no_http(self) -> None:
        d = _device("a", ["KLR-MXM-DG27"], ["jumpcloud"], jc_id="jc1")
        with patch("src.jumpcloud_reconciler.requests.Session") as mock_session:
            out = reconcile_displaynames([d], {"jc1": "KLR-MXM-DG27"}, api_key="fake")
        mock_session.assert_not_called()
        assert out == {"scanned": 1, "drifted": 0, "updated": 0,
                       "failed": 0, "capped": 0, "dry_run": False}

    def test_drifted_device_is_patched(self) -> None:
        d = _device("a", ["KLR-MXM-DG27"], ["jumpcloud"], jc_id="jc1")
        mock_resp = MagicMock(status_code=200)
        mock_resp.raise_for_status.return_value = None
        mock_session = MagicMock()
        mock_session.put.return_value = mock_resp
        with patch("src.jumpcloud_reconciler.requests.Session", return_value=mock_session):
            out = reconcile_displaynames([d], {"jc1": "old"}, api_key="fake")
        assert out["updated"] == 1
        assert out["drifted"] == 1
        assert out["failed"] == 0
        mock_session.put.assert_called_once()
        args, kwargs = mock_session.put.call_args
        assert args[0].endswith("/systems/jc1")
        assert kwargs["json"] == {"displayName": "KLR-MXM-DG27"}

    def test_dry_run_skips_http(self) -> None:
        d = _device("a", ["KLR-MXM-DG27"], ["jumpcloud"], jc_id="jc1")
        with patch("src.jumpcloud_reconciler.requests.Session") as mock_session:
            out = reconcile_displaynames([d], {"jc1": "old"}, api_key="fake", dry_run=True)
        mock_session.assert_not_called()
        assert out == {"scanned": 1, "drifted": 1, "updated": 0,
                       "failed": 0, "capped": 0, "dry_run": True}

    def test_max_updates_caps_runaway(self) -> None:
        devs = [_device(f"d{i}", [f"KLR-MXM-{i:04d}"], ["jumpcloud"], jc_id=f"jc{i}")
                for i in range(10)]
        names = {f"jc{i}": "old" for i in range(10)}
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_session = MagicMock()
        mock_session.put.return_value = mock_resp
        with patch("src.jumpcloud_reconciler.requests.Session", return_value=mock_session):
            out = reconcile_displaynames(devs, names, api_key="fake", max_updates=3)
        assert out["drifted"] == 10
        assert out["updated"] == 3
        assert out["capped"] == 7
        assert mock_session.put.call_count == 3

    def test_http_failure_does_not_raise(self) -> None:
        d = _device("a", ["KLR-MXM-DG27"], ["jumpcloud"], jc_id="jc1")
        mock_session = MagicMock()
        mock_session.put.side_effect = requests.HTTPError("500 boom")
        with patch("src.jumpcloud_reconciler.requests.Session", return_value=mock_session):
            out = reconcile_displaynames([d], {"jc1": "old"}, api_key="fake")
        assert out["failed"] == 1
        assert out["updated"] == 0

    def test_api_key_explicit_overrides_env(self, monkeypatch) -> None:
        monkeypatch.delenv("JC_API_KEY", raising=False)
        d = _device("a", ["KLR-MXM-DG27"], ["jumpcloud"], jc_id="jc1")
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_session = MagicMock()
        mock_session.put.return_value = mock_resp
        with patch("src.jumpcloud_reconciler.requests.Session", return_value=mock_session):
            out = reconcile_displaynames([d], {"jc1": "old"}, api_key="explicit")
        assert out["updated"] == 1


# ── jc_displaynames_from_raw helper ───────────────────────────────────

class TestJCDisplaynamesFromRaw:
    def test_extracts_displayname_from_jc_raw_records(self) -> None:
        raws = [
            RawDevice(source="jumpcloud", source_device_id="jc1",
                      raw_data={"displayName": "MacBook-Pro-de-Klar.local"}),
            RawDevice(source="jumpcloud", source_device_id="jc2",
                      raw_data={"displayName": "KLR-MXM-AAAA"}),
        ]
        out = jc_displaynames_from_raw(raws)
        assert out == {"jc1": "MacBook-Pro-de-Klar.local", "jc2": "KLR-MXM-AAAA"}

    def test_skips_non_jc_sources(self) -> None:
        raws = [
            RawDevice(source="crowdstrike", source_device_id="aid1",
                      raw_data={"displayName": "x"}),
            RawDevice(source="okta", source_device_id="ok1",
                      raw_data={"displayName": "y"}),
        ]
        assert jc_displaynames_from_raw(raws) == {}

    def test_handles_missing_displayname_gracefully(self) -> None:
        raws = [
            RawDevice(source="jumpcloud", source_device_id="jc1", raw_data={}),
            RawDevice(source="jumpcloud", source_device_id="jc2", raw_data={"displayName": None}),
        ]
        out = jc_displaynames_from_raw(raws)
        assert out == {"jc1": "", "jc2": ""}
