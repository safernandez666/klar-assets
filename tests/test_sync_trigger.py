"""Tests for the /api/sync/trigger endpoint — verify the syncing flag
lifecycle and concurrent-trigger guard.
"""
from __future__ import annotations

import time
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.web.api.sync import router as sync_router
from src.web.cache import CacheManager
import src.web.api.sync as sync_module


@pytest.fixture
def app_with_cache(tmp_path):
    """Mount only the sync router with a fresh CacheManager singleton."""
    app = FastAPI()
    app.include_router(sync_router)

    db_path = str(tmp_path / "test.db")
    fresh_cache = CacheManager(db_path)

    with patch.object(sync_module, "get_cache", return_value=fresh_cache):
        yield app, fresh_cache


def test_trigger_sets_and_clears_syncing_flag(app_with_cache) -> None:
    """Flag is True while SyncEngine.run() executes, False after."""
    app, cache = app_with_cache
    assert cache.syncing is False

    # Capture the flag's value from inside the patched run() so we can
    # verify it was True during the work — TestClient blocks until the
    # background task finishes, so we can't observe the live state from
    # the main thread.
    flag_during_run: list[bool] = []

    def capture_flag(self):
        flag_during_run.append(cache.syncing)
        return {"status": "success"}

    with patch("src.web.api.sync.SyncEngine.run", new=capture_flag), \
         TestClient(app) as client:
        resp = client.post("/api/sync/trigger")

    assert resp.status_code == 200
    assert resp.json() == {"message": "Sync triggered", "started": True}
    assert flag_during_run == [True]
    assert cache.syncing is False


def test_trigger_returns_409_when_already_syncing(app_with_cache) -> None:
    app, cache = app_with_cache
    cache.syncing = True

    with TestClient(app) as client:
        resp = client.post("/api/sync/trigger")

    assert resp.status_code == 409
    body = resp.json()
    assert body["started"] is False
    assert "in progress" in body["message"].lower()
    # Flag must remain True — we did not clear someone else's sync.
    assert cache.syncing is True


def test_trigger_clears_flag_even_when_run_raises(app_with_cache) -> None:
    """If SyncEngine.run() raises, the syncing flag must still be cleared
    so the UI can recover instead of getting stuck."""
    app, cache = app_with_cache

    def boom(self):
        raise RuntimeError("collector blew up")

    with patch("src.web.api.sync.SyncEngine.run", new=boom), \
         TestClient(app) as client:
        resp = client.post("/api/sync/trigger")
        assert resp.status_code == 200

    deadline = time.time() + 2
    while time.time() < deadline and cache.syncing:
        time.sleep(0.05)
    assert cache.syncing is False
