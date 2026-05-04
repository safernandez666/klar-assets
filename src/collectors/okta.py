from __future__ import annotations

import os
import re
import time
from datetime import datetime, timezone
from typing import Any

import requests
import structlog

from src.collectors.base import BaseCollector
from src.models import RawDevice

logger = structlog.get_logger(__name__)


class OktaCollector(BaseCollector):
    def __init__(self) -> None:
        super().__init__("okta")
        self.domain = os.getenv("OKTA_DOMAIN", "")
        self.token = os.getenv("OKTA_API_TOKEN", "")
        self.base_url = f"https://{self.domain}" if self.domain else ""
        self.session = requests.Session()
        if self.token:
            self.session.headers.update({
                "Authorization": f"SSWS {self.token}",
                "Accept": "application/json",
            })

    def _request_with_retry(self, url: str, params: dict[str, Any] | None = None, max_retries: int = 3) -> requests.Response:
        """Make a GET request with rate-limit awareness and retry on 429."""
        for attempt in range(1, max_retries + 1):
            resp = self.session.get(url, params=params or {}, timeout=30)

            if resp.status_code == 429:
                # Okta sends X-Rate-Limit-Reset as a Unix timestamp
                reset_at = resp.headers.get("X-Rate-Limit-Reset")
                if reset_at:
                    wait = max(int(reset_at) - int(time.time()), 1)
                    wait = min(wait, 30)  # cap wait at 30s
                else:
                    wait = 2 ** attempt

                self.log.warning("rate_limited", attempt=attempt, wait=wait)
                time.sleep(wait)
                continue

            # Check remaining rate limit and preemptively slow down
            remaining = resp.headers.get("X-Rate-Limit-Remaining")
            if remaining and int(remaining) < 10:
                self.log.info("rate_limit_low", remaining=remaining)
                time.sleep(1)

            return resp

        # Exhausted retries — return last response
        return resp

    def _parse_last_seen(self, value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            if value.endswith("Z"):
                value = value[:-1] + "+00:00"
            return datetime.fromisoformat(value)
        except Exception:
            return None

    def _fetch_devices(self) -> list[dict[str, Any]]:
        devices: list[dict[str, Any]] = []
        if not self.base_url:
            self.log.warning("okta_credentials_missing")
            return devices
        url = f"{self.base_url}/api/v1/devices"
        # `expand=user` returns user assignments inline under
        # `_embedded.users[]`. Without it, each device requires an extra API
        # call to /api/v1/devices/{id}/users — which exhausts the 50 req/min
        # rate limit for tenants with more than ~50 devices.
        params: dict[str, Any] = {"limit": 200, "expand": "user"}
        after: str | None = None
        for _ in range(1000):
            if after:
                params["after"] = after
            resp = self._request_with_retry(url, params=params)
            if resp.status_code == 429:
                self.log.error("rate_limit_exhausted_devices", fetched_so_far=len(devices))
                break
            resp.raise_for_status()
            data = resp.json()
            if not isinstance(data, list):
                break
            devices.extend(data)
            link_header = resp.headers.get("link", "")
            next_after = None
            for part in link_header.split(","):
                if 'rel="next"' in part:
                    for segment in part.split(";"):
                        if "after=" in segment:
                            m = re.search(r'after=([^&>]+)', segment)
                            if m:
                                next_after = m.group(1)
                    break
            if not next_after or next_after == after:
                break
            after = next_after
        return devices

    def collect_users(self) -> list[dict[str, Any]]:
        """Fetch all active users from Okta /api/v1/users."""
        users: list[dict[str, Any]] = []
        if not self.base_url:
            self.log.warning("okta_credentials_missing")
            return users
        url = f"{self.base_url}/api/v1/users"
        params: dict[str, Any] = {"limit": 200, "filter": 'status eq "ACTIVE"'}
        after: str | None = None
        for _ in range(1000):
            if after:
                params["after"] = after
            resp = self._request_with_retry(url, params=params)
            if resp.status_code == 429:
                self.log.error("rate_limit_exhausted_users_list", fetched_so_far=len(users))
                break
            resp.raise_for_status()
            data = resp.json()
            if not isinstance(data, list) or not data:
                break
            for u in data:
                profile = u.get("profile", {})
                users.append({
                    "id": u.get("id", ""),
                    "email": profile.get("email", "") or profile.get("login", ""),
                    "first_name": profile.get("firstName", ""),
                    "last_name": profile.get("lastName", ""),
                    "status": u.get("status", ""),
                    "user_type": profile.get("klar_user_type", ""),
                    "google_ou": profile.get("google_ou", ""),
                    "manager_id": profile.get("managerId", ""),
                    "last_login": u.get("lastLogin"),
                    "created_at": u.get("created"),
                })
            # Pagination via Link header
            link_header = resp.headers.get("link", "")
            next_after = None
            for part in link_header.split(","):
                if 'rel="next"' in part:
                    for segment in part.split(";"):
                        if "after=" in segment:
                            m = re.search(r'after=([^&>]+)', segment)
                            if m:
                                next_after = m.group(1)
                    break
            if not next_after or next_after == after:
                break
            after = next_after
        self.log.info("okta_users_fetched", count=len(users))
        return users

    def collect(self) -> list[RawDevice]:
        devices = self._fetch_devices()
        self.log.info("devices_fetched", count=len(devices))
        results: list[RawDevice] = []
        for dev in devices:
            device_id = dev.get("id", "")
            display_name = dev.get("displayName") or dev.get("profile", {}).get("displayName", "")
            platform = dev.get("platform") or dev.get("profile", {}).get("platform", "")
            serial = dev.get("serialNumber") or dev.get("profile", {}).get("serialNumber", "")
            status = dev.get("status") or ""
            registered = dev.get("registered") or False
            last_seen = self._parse_last_seen(dev.get("lastSeen"))

            # Users come inline under _embedded.users[] thanks to expand=user.
            users = dev.get("_embedded", {}).get("users") or []

            if not users:
                results.append(
                    RawDevice(
                        device_id=device_id,
                        hostname=display_name,
                        serial_number=serial if self.is_valid_serial(serial) else None,
                        mac_addresses=[],
                        os_type=platform,
                        os_version="",
                        last_user=None,
                        last_seen=last_seen,
                        source="okta",
                        source_device_id=device_id,
                        raw_data={
                            **dev,
                            "okta_users": [],
                            "status": status,
                            "registered": registered,
                        },
                    )
                )
                continue

            for assignment in users:
                user_obj = assignment.get("user") or {}
                profile = user_obj.get("profile") or {}
                user_login = profile.get("login") or profile.get("email") or ""
                first = profile.get("firstName") or ""
                last = profile.get("lastName") or ""
                user_name = profile.get("displayName") or (f"{first} {last}".strip() or None)
                results.append(
                    RawDevice(
                        device_id=device_id,
                        hostname=display_name,
                        serial_number=serial if self.is_valid_serial(serial) else None,
                        mac_addresses=[],
                        os_type=platform,
                        os_version="",
                        last_user=user_login or None,
                        last_seen=last_seen,
                        source="okta",
                        source_device_id=device_id,
                        raw_data={
                            **dev,
                            "okta_users": [assignment],
                            "status": status,
                            "registered": registered,
                            "owner_email": user_login,
                            "owner_name": user_name,
                        },
                    )
                )
        return results
