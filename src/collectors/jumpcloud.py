from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any

import requests
import structlog

from src.collectors.base import BaseCollector
from src.models import RawDevice

logger = structlog.get_logger(__name__)


class JumpCloudCollector(BaseCollector):
    def __init__(self) -> None:
        super().__init__("jumpcloud")
        self.api_key = os.getenv("JC_API_KEY", "")
        self.base_url = "https://console.jumpcloud.com/api"
        self.session = requests.Session()
        if self.api_key:
            self.session.headers.update({
                "x-api-key": self.api_key,
                "Accept": "application/json",
                "Content-Type": "application/json",
            })

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any] | list[Any]:
        if not self.api_key:
            return []
        url = f"{self.base_url}{path}"
        for attempt in range(1, 4):
            resp = self.session.get(url, params=params or {}, timeout=30)
            if resp.status_code == 429:
                wait = 2 ** attempt
                self.log.warning("rate_limited", attempt=attempt, wait=wait, path=path)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()
        resp.raise_for_status()
        return resp.json()

    def _fetch_systems(self) -> list[dict[str, Any]]:
        systems: list[dict[str, Any]] = []
        if not self.api_key:
            self.log.warning("jumpcloud_credentials_missing")
            return systems
        skip = 0
        limit = 100
        for _ in range(1000):
            data = self._get("/systems", params={"skip": skip, "limit": limit})
            if isinstance(data, dict):
                results = data.get("results", [])
                systems.extend(results)
                if len(results) < limit:
                    break
                skip += limit
            elif isinstance(data, list):
                systems.extend(data)
                if len(data) < limit:
                    break
                skip += limit
            else:
                break
        return systems

    def _fetch_user_details(self, user_id: str) -> dict[str, str]:
        """Fetch a single user's email and displayname from /api/systemusers/{id}."""
        try:
            data = self._get(f"/systemusers/{user_id}")
            if isinstance(data, dict):
                return {
                    "email": data.get("email") or "",
                    "username": data.get("username") or "",
                    "displayname": data.get("displayname") or "",
                }
        except Exception as exc:
            self.log.warning("fetch_user_details_error", user_id=user_id, error=str(exc))
        return {}

    def _fetch_system_user_ids(self, system_id: str) -> list[str]:
        """Fetch user IDs associated with a system via associations API."""
        try:
            data = self._get(
                f"/v2/systems/{system_id}/associations",
                params={"targets": "user"},
            )
            if isinstance(data, list):
                user_ids = []
                for assoc in data:
                    if isinstance(assoc, dict):
                        to_val = assoc.get("to", {})
                        user_id = to_val.get("id", "")
                        if user_id:
                            user_ids.append(user_id)
                return user_ids
        except Exception as exc:
            self.log.warning("fetch_system_user_ids_error", system_id=system_id, error=str(exc))
        return []

    def collect(self) -> list[RawDevice]:
        systems = self._fetch_systems()
        results: list[RawDevice] = []

        # Step 1: Fetch all system → user_id associations in parallel
        system_user_ids: dict[str, list[str]] = {}
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = {
                executor.submit(self._fetch_system_user_ids, sys.get("id", "")): sys.get("id", "")
                for sys in systems
            }
            for future in as_completed(futures):
                sid = futures[future]
                try:
                    system_user_ids[sid] = future.result()
                except Exception:
                    system_user_ids[sid] = []

        # Step 2: Collect all unique user IDs and resolve them to emails in parallel
        all_user_ids = {uid for uids in system_user_ids.values() for uid in uids}
        user_details: dict[str, dict[str, str]] = {}
        if all_user_ids:
            with ThreadPoolExecutor(max_workers=3) as executor:
                futures = {
                    executor.submit(self._fetch_user_details, uid): uid
                    for uid in all_user_ids
                }
                for future in as_completed(futures):
                    uid = futures[future]
                    try:
                        user_details[uid] = future.result()
                    except Exception:
                        user_details[uid] = {}

        # Step 3: Build RawDevice entries
        for sys in systems:
            system_id = sys.get("id", "")
            hostname = sys.get("hostname") or sys.get("displayName", "")
            serial = sys.get("serialNumber") or ""
            os_type = sys.get("os") or ""
            os_version = sys.get("version") or ""
            last_seen_str = sys.get("lastContactDate") or sys.get("lastContact", "")
            last_seen = None
            if last_seen_str:
                try:
                    if last_seen_str.endswith("Z"):
                        last_seen_str = last_seen_str[:-1] + "+00:00"
                    last_seen = datetime.fromisoformat(last_seen_str)
                except Exception:
                    pass

            # Resolve user emails for this system
            uids = system_user_ids.get(system_id, [])
            user_emails = []
            for uid in uids:
                details = user_details.get(uid, {})
                email = details.get("email", "")
                if email:
                    user_emails.append(email)

            last_user = user_emails[0] if user_emails else None

            results.append(
                RawDevice(
                    device_id=system_id,
                    hostname=hostname,
                    serial_number=serial if self.is_valid_serial(serial) else None,
                    mac_addresses=[],
                    os_type=os_type,
                    os_version=os_version,
                    last_user=last_user,
                    last_seen=last_seen,
                    source="jumpcloud",
                    source_device_id=system_id,
                    raw_data={
                        **sys,
                        "system_users": user_emails,
                    },
                )
            )
        return results
