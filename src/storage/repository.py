from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from src.models import NormalizedDevice
from src.storage.schema import init_db


class DeviceRepository:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        init_db(db_path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _serialize(value: Any) -> str:
        return json.dumps(value, default=str)

    @staticmethod
    def _deserialize(value: str | None, default: Any) -> Any:
        if value is None:
            return default
        try:
            return json.loads(value)
        except Exception:
            return default

    def upsert_devices(self, devices: list[NormalizedDevice]) -> None:
        conn = self._connect()
        now = datetime.now(timezone.utc).isoformat()
        with conn:
            # Soft-delete all existing active devices so each sync is a clean snapshot.
            # This prevents duplicates when canonical_ids change or devices disappear.
            conn.execute(
                "UPDATE devices SET deleted_at = ? WHERE deleted_at IS NULL",
                (now,),
            )
            for dev in devices:
                conn.execute(
                    """
                    INSERT INTO devices (
                        canonical_id, hostnames, serial_number, mac_addresses,
                        owner_email, owner_name, os_type, sources, source_ids,
                        status, confidence_score, match_reason, is_active_vpn,
                        coverage_gaps, days_since_seen, first_seen, last_seen, deleted_at,
                        timezone, region
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        dev.canonical_id,
                        self._serialize(dev.hostnames),
                        dev.serial_number,
                        self._serialize(dev.mac_addresses),
                        dev.owner_email,
                        dev.owner_name,
                        dev.os_type,
                        self._serialize(dev.sources),
                        self._serialize(dev.source_ids),
                        dev.status,
                        dev.confidence_score,
                        dev.match_reason,
                        1 if dev.is_active_vpn else 0,
                        self._serialize(dev.coverage_gaps),
                        dev.days_since_seen,
                        dev.first_seen.isoformat() if dev.first_seen else now,
                        dev.last_seen.isoformat() if dev.last_seen else now,
                        None,
                        dev.timezone,
                        dev.region,
                    ),
                )
        conn.close()

    def get_all_devices(
        self,
        status: str | None = None,
        source: str | None = None,
        search: str | None = None,
        page: int | None = None,
        page_size: int = 25,
        region: str | None = None,
    ) -> list[dict[str, Any]] | dict[str, Any]:
        """Get devices. If page is set, returns paginated result with total count."""
        conn = self._connect()
        query = "SELECT * FROM devices WHERE deleted_at IS NULL"
        count_query = "SELECT COUNT(*) FROM devices WHERE deleted_at IS NULL"
        params: list[Any] = []
        if status:
            query += " AND status = ?"
            count_query += " AND status = ?"
            params.append(status)
        if source:
            query += " AND sources LIKE ?"
            count_query += " AND sources LIKE ?"
            params.append(f'%"{source}"%')
        if region:
            query += " AND region = ?"
            count_query += " AND region = ?"
            params.append(region)
        if search:
            query += " AND (owner_email LIKE ? OR hostnames LIKE ? OR serial_number LIKE ?)"
            count_query += " AND (owner_email LIKE ? OR hostnames LIKE ? OR serial_number LIKE ?)"
            s = f"%{search}%"
            params.extend([s, s, s])
        query += " ORDER BY last_seen DESC"

        if page is not None:
            total = conn.execute(count_query, params).fetchone()[0]
            offset = (page - 1) * page_size
            query += " LIMIT ? OFFSET ?"
            rows = conn.execute(query, params + [page_size, offset]).fetchall()
            conn.close()
            return {
                "devices": [self._row_to_dict(row) for row in rows],
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": (total + page_size - 1) // page_size,
            }

        rows = conn.execute(query, params).fetchall()
        conn.close()
        return [self._row_to_dict(row) for row in rows]

    def get_summary(self, exclude_acknowledged: bool = True) -> dict[str, Any]:
        conn = self._connect()
        ack_filter = ""
        if exclude_acknowledged:
            ack_filter = " AND canonical_id NOT IN (SELECT canonical_id FROM acknowledged_devices)"
        status_counts = conn.execute(
            f"SELECT status, COUNT(*) as cnt FROM devices WHERE deleted_at IS NULL{ack_filter} GROUP BY status"
        ).fetchall()
        all_rows = conn.execute(
            f"SELECT sources FROM devices WHERE deleted_at IS NULL{ack_filter}"
        ).fetchall()
        conn.close()

        summary: dict[str, Any] = {
            "by_status": {row["status"]: row["cnt"] for row in status_counts},
            "by_source": {},
            "total": sum(row["cnt"] for row in status_counts),
        }
        source_counts: dict[str, int] = {}
        for row in all_rows:
            sources = self._deserialize(row["sources"], [])
            for s in sources:
                source_counts[s] = source_counts.get(s, 0) + 1
        summary["by_source"] = source_counts
        return summary

    # ── Acknowledge ──────────────────────────────────────────────────

    def acknowledge_device(self, canonical_id: str, reason: str = "", by: str = "") -> None:
        conn = self._connect()
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT OR REPLACE INTO acknowledged_devices (canonical_id, reason, acknowledged_by, acknowledged_at) VALUES (?, ?, ?, ?)",
            (canonical_id, reason, by, now),
        )
        conn.commit()
        conn.close()

    def unacknowledge_device(self, canonical_id: str) -> None:
        conn = self._connect()
        conn.execute("DELETE FROM acknowledged_devices WHERE canonical_id = ?", (canonical_id,))
        conn.commit()
        conn.close()

    def save_okta_users(self, users: list[dict[str, Any]]) -> None:
        """Replace all okta_users with fresh data from Okta API."""
        conn = self._connect()
        conn.execute("DELETE FROM okta_users")
        for u in users:
            conn.execute(
                """INSERT OR REPLACE INTO okta_users
                   (id, email, first_name, last_name, status, user_type, google_ou, manager_id, last_login, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (u.get("id"), u.get("email", "").lower(), u.get("first_name"), u.get("last_name"),
                 u.get("status"), u.get("user_type"), u.get("google_ou"), u.get("manager_id"),
                 u.get("last_login"), u.get("created_at"), datetime.now(timezone.utc).isoformat()),
            )
        conn.commit()
        conn.close()

    def get_okta_users(self, exclude_types: list[str] | None = None) -> list[dict[str, Any]]:
        """Get all Okta users, optionally excluding certain user types."""
        conn = self._connect()
        rows = conn.execute("SELECT * FROM okta_users").fetchall()
        conn.close()
        users = [dict(row) for row in rows]
        if exclude_types:
            users = [u for u in users if u.get("user_type") not in exclude_types]
        return users

    def get_acknowledged(self) -> set[str]:
        conn = self._connect()
        rows = conn.execute("SELECT canonical_id FROM acknowledged_devices").fetchall()
        conn.close()
        return {row["canonical_id"] for row in rows}

    def get_acknowledged_details(self) -> dict[str, dict[str, str]]:
        conn = self._connect()
        rows = conn.execute("SELECT * FROM acknowledged_devices").fetchall()
        conn.close()
        return {row["canonical_id"]: {"reason": row["reason"], "by": row["acknowledged_by"], "at": row["acknowledged_at"]} for row in rows}

    def get_low_confidence(self, threshold: float = 0.5) -> list[dict[str, Any]]:
        conn = self._connect()
        rows = conn.execute(
            "SELECT * FROM devices WHERE deleted_at IS NULL AND confidence_score < ? ORDER BY confidence_score ASC",
            (threshold,),
        ).fetchall()
        conn.close()
        return [self._row_to_dict(row) for row in rows]

    def save_sync_run(self, run: dict[str, Any]) -> int:
        conn = self._connect()
        cursor = conn.execute(
            """
            INSERT INTO sync_runs (
                started_at, finished_at, status, total_raw_devices,
                duplicates_removed, final_count, sources_ok, sources_failed
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run.get("started_at"),
                run.get("finished_at"),
                run.get("status"),
                run.get("total_raw_devices", 0),
                run.get("duplicates_removed", 0),
                run.get("final_count", 0),
                self._serialize(run.get("sources_ok", [])),
                self._serialize(run.get("sources_failed", [])),
            ),
        )
        row_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return row_id

    def get_last_sync_run(self) -> dict[str, Any] | None:
        conn = self._connect()
        row = conn.execute(
            "SELECT * FROM sync_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
        conn.close()
        if not row:
            return None
        return self._row_to_dict(row)

    def get_previous_canonical_ids(self) -> set[str]:
        """Get canonical_ids from the soft-deleted generation (previous sync)."""
        conn = self._connect()
        rows = conn.execute(
            """SELECT DISTINCT canonical_id FROM devices
               WHERE deleted_at IS NOT NULL
               AND deleted_at = (SELECT MAX(deleted_at) FROM devices WHERE deleted_at IS NOT NULL)""",
        ).fetchall()
        conn.close()
        return {row["canonical_id"] for row in rows}

    def get_new_devices(self) -> list[dict[str, Any]]:
        """Get devices that appeared in this sync but not the previous one.

        Excludes false positives where the serial number existed in the
        previous sync (device was re-merged with a different canonical_id).
        """
        prev_ids = self.get_previous_canonical_ids()
        if not prev_ids:
            return []  # First sync, everything is new
        conn = self._connect()
        rows = conn.execute(
            "SELECT * FROM devices WHERE deleted_at IS NULL"
        ).fetchall()
        conn.close()
        current = [self._row_to_dict(row) for row in rows]
        new_by_id = [d for d in current if d["canonical_id"] not in prev_ids]

        if not new_by_id:
            return []

        # Get serials from previous sync to filter re-merged devices
        conn2 = self._connect()
        prev_rows = conn2.execute(
            """SELECT serial_number FROM devices
               WHERE deleted_at IS NOT NULL AND serial_number IS NOT NULL AND serial_number != ''
               AND deleted_at = (SELECT MAX(deleted_at) FROM devices WHERE deleted_at IS NOT NULL)"""
        ).fetchall()
        conn2.close()
        prev_serials = {r["serial_number"].lower() for r in prev_rows}

        return [d for d in new_by_id
                if not ((d.get("serial_number") or "").lower() in prev_serials
                        and (d.get("serial_number") or "").lower())]

    def get_recently_deleted(self) -> list[dict[str, Any]]:
        """Get devices that were soft-deleted in the most recent sync (disappeared).

        Excludes false positives where the serial number still exists in
        the active inventory (device was re-merged with a different canonical_id).
        """
        conn = self._connect()
        rows = conn.execute(
            """
            SELECT * FROM devices
            WHERE deleted_at IS NOT NULL
              AND status IN ('MANAGED', 'FULLY_MANAGED', 'SERVER')
              AND deleted_at = (SELECT MAX(deleted_at) FROM devices WHERE deleted_at IS NOT NULL)
              AND canonical_id NOT IN (SELECT canonical_id FROM devices WHERE deleted_at IS NULL)
            ORDER BY last_seen DESC
            """,
        ).fetchall()
        conn.close()

        # Filter out false positives: if the serial still exists in active devices,
        # the device was re-merged under a different canonical_id, not truly disappeared
        if not rows:
            return []
        active_serials = set()
        conn2 = self._connect()
        active_rows = conn2.execute(
            "SELECT serial_number FROM devices WHERE deleted_at IS NULL AND serial_number IS NOT NULL AND serial_number != ''"
        ).fetchall()
        conn2.close()
        active_serials = {r["serial_number"].lower() for r in active_rows}

        result = []
        for row in rows:
            d = self._row_to_dict(row)
            serial = (d.get("serial_number") or "").lower()
            if serial and serial in active_serials:
                continue  # Serial still active — false positive (re-merged)
            result.append(d)
        return result

    def get_newly_stale(self, previous_days: int = 7) -> list[dict[str, Any]]:
        """Get devices that recently became stale (were active last sync, now >90 days)."""
        conn = self._connect()
        rows = conn.execute(
            """
            SELECT * FROM devices
            WHERE deleted_at IS NULL
              AND status = 'STALE'
              AND days_since_seen BETWEEN 90 AND ?
            ORDER BY days_since_seen ASC
            """,
            (90 + previous_days,),
        ).fetchall()
        conn.close()
        return [self._row_to_dict(row) for row in rows]

    def save_status_snapshot(self, sync_run_id: int, status_counts: dict[str, int]) -> None:
        conn = self._connect()
        now = datetime.now(timezone.utc).isoformat()
        total = sum(status_counts.values())
        conn.execute(
            """
            INSERT INTO status_snapshots (
                sync_run_id, recorded_at, total,
                fully_managed, managed, no_edr, no_mdm, idp_only, stale, unknown, server
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                sync_run_id,
                now,
                total,
                status_counts.get("FULLY_MANAGED", 0),
                status_counts.get("MANAGED", 0),
                status_counts.get("NO_EDR", 0),
                status_counts.get("NO_MDM", 0),
                status_counts.get("IDP_ONLY", 0),
                status_counts.get("STALE", 0),
                status_counts.get("UNKNOWN", 0),
                status_counts.get("SERVER", 0),
            ),
        )
        conn.commit()
        conn.close()

    def get_status_history(self, limit: int = 30) -> list[dict[str, Any]]:
        conn = self._connect()
        rows = conn.execute(
            "SELECT * FROM status_snapshots ORDER BY recorded_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        conn.close()
        return [dict(row) for row in reversed(rows)]

    def get_previous_snapshot(self) -> dict[str, Any] | None:
        """Get the second-to-last snapshot for trend comparison."""
        conn = self._connect()
        rows = conn.execute(
            "SELECT * FROM status_snapshots ORDER BY recorded_at DESC LIMIT 2"
        ).fetchall()
        conn.close()
        if len(rows) < 2:
            return None
        return dict(rows[1])

    def _row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        d["hostnames"] = self._deserialize(d.get("hostnames"), [])
        d["mac_addresses"] = self._deserialize(d.get("mac_addresses"), [])
        d["sources"] = self._deserialize(d.get("sources"), [])
        d["source_ids"] = self._deserialize(d.get("source_ids"), {})
        d["coverage_gaps"] = self._deserialize(d.get("coverage_gaps"), [])
        d["sources_ok"] = self._deserialize(d.get("sources_ok"), [])
        d["sources_failed"] = self._deserialize(d.get("sources_failed"), [])
        d["is_active_vpn"] = bool(d.get("is_active_vpn", 0))
        return d
