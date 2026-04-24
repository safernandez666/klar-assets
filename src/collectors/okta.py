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
        params: dict[str, Any] = {"limit": 200}
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

    def _fetch_device_users(self, device_id: str) -> list[dict[str, Any]]:
        try:
            url = f"{self.base_url}/api/v1/devices/{device_id}/users"
            resp = self._request_with_retry(url)
            if resp.status_code == 429:
                self.log.warning("rate_limit_exhausted_users", device_id=device_id)
                return []
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list):
                return data
        except Exception as exc:
            self.log.warning("fetch_device_users_error", device_id=device_id, error=str(exc))
        return []

    def collect(self) -> list[RawDevice]:
        devices = self._fetch_devices()
        self.log.info("devices_fetched", count=len(devices))
        results: list[RawDevice] = []
        for i, dev in enumerate(devices):
            device_id = dev.get("id", "")
            display_name = dev.get("displayName") or dev.get("profile", {}).get("displayName", "")
            platform = dev.get("platform") or dev.get("profile", {}).get("platform", "")
            serial = dev.get("serialNumber") or dev.get("profile", {}).get("serialNumber", "")
            status = dev.get("status") or ""
            registered = dev.get("registered") or False
            last_seen = self._parse_last_seen(dev.get("lastSeen"))

            # Throttle: small delay every 5 devices to avoid hammering Okta
            if i > 0 and i % 5 == 0:
                time.sleep(0.2)

            users = self._fetch_device_users(device_id)
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
            else:
                for user in users:
                    user_login = user.get("login") or user.get("profile", {}).get("login", "")
                    user_name = user.get("displayName") or user.get("profile", {}).get("displayName", "")
                    results.append(
                        RawDevice(
                            device_id=device_id,
                            hostname=display_name,
                            serial_number=serial if self.is_valid_serial(serial) else None,
                            mac_addresses=[],
                            os_type=platform,
                            os_version="",
                            last_user=user_login,
                            last_seen=last_seen,
                            source="okta",
                            source_device_id=device_id,
                            raw_data={
                                **dev,
                                "okta_users": [user],
                                "status": status,
                                "registered": registered,
                                "owner_email": user_login,
                                "owner_name": user_name,
                            },
                        )
                    )
        return results
