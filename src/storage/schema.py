from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_SQL = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS devices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_id TEXT NOT NULL,
    hostnames TEXT NOT NULL DEFAULT '[]',
    serial_number TEXT,
    mac_addresses TEXT NOT NULL DEFAULT '[]',
    owner_email TEXT,
    owner_name TEXT,
    os_type TEXT,
    sources TEXT NOT NULL DEFAULT '[]',
    source_ids TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'UNKNOWN',
    confidence_score REAL NOT NULL DEFAULT 0.0,
    match_reason TEXT NOT NULL DEFAULT '',
    is_active_vpn INTEGER NOT NULL DEFAULT 0,
    coverage_gaps TEXT NOT NULL DEFAULT '[]',
    days_since_seen INTEGER,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    deleted_at TEXT
);

CREATE TABLE IF NOT EXISTS sync_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    total_raw_devices INTEGER NOT NULL DEFAULT 0,
    duplicates_removed INTEGER NOT NULL DEFAULT 0,
    final_count INTEGER NOT NULL DEFAULT 0,
    sources_ok TEXT NOT NULL DEFAULT '[]',
    sources_failed TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS status_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sync_run_id INTEGER NOT NULL,
    recorded_at TEXT NOT NULL,
    total INTEGER NOT NULL DEFAULT 0,
    fully_managed INTEGER NOT NULL DEFAULT 0,
    managed INTEGER NOT NULL DEFAULT 0,
    no_edr INTEGER NOT NULL DEFAULT 0,
    no_mdm INTEGER NOT NULL DEFAULT 0,
    idp_only INTEGER NOT NULL DEFAULT 0,
    stale INTEGER NOT NULL DEFAULT 0,
    unknown INTEGER NOT NULL DEFAULT 0,
    server INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS acknowledged_devices (
    canonical_id TEXT PRIMARY KEY,
    reason TEXT NOT NULL DEFAULT '',
    acknowledged_by TEXT NOT NULL DEFAULT '',
    acknowledged_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_devices_owner_email ON devices(owner_email);
CREATE INDEX IF NOT EXISTS idx_devices_status ON devices(status);
CREATE INDEX IF NOT EXISTS idx_devices_last_seen ON devices(last_seen);
CREATE INDEX IF NOT EXISTS idx_devices_serial_number ON devices(serial_number);
CREATE INDEX IF NOT EXISTS idx_snapshots_recorded_at ON status_snapshots(recorded_at);
"""


def init_db(db_path: str) -> None:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    conn.close()
