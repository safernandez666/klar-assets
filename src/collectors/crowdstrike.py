from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Any

import structlog
from falconpy import Hosts

from src.collectors.base import BaseCollector
from src.models import RawDevice

logger = structlog.get_logger(__name__)


class CrowdStrikeCollector(BaseCollector):
    def __init__(self) -> None:
        super().__init__("crowdstrike")
        self.client_id = os.getenv("CS_CLIENT_ID", "")
        self.client_secret = os.getenv("CS_CLIENT_SECRET", "")
        self.base_url = os.getenv("CS_BASE_URL", "https://api.crowdstrike.com")
        self.client: Hosts | None = None
        if self.client_id and self.client_secret:
            self.client = Hosts(
                client_id=self.client_id,
                client_secret=self.client_secret,
                base_url=self.base_url,
            )

    def _parse_last_seen(self, value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except Exception:
            return None

    def _fetch_with_retry(self) -> list[dict[str, Any]]:
        if not self.client:
            self.log.warning("crowdstrike_credentials_missing")
            return []
        all_devices: list[dict[str, Any]] = []
        offset = 0
        limit = 500
        max_retries = 3
        while True:
            for attempt in range(1, max_retries + 1):
                try:
                    response = self.client.query_devices_by_filter(
                        limit=limit,
                        offset=offset,
                    )
                    if response["status_code"] == 429:
                        if attempt < max_retries:
                            sleep_time = 2 ** attempt
                            self.log.warning("rate_limited", attempt=attempt, sleep=sleep_time)
                            time.sleep(sleep_time)
                            continue
                        else:
                            raise RuntimeError("CrowdStrike rate limit exhausted")
                    if response["status_code"] not in (200, 201):
                        raise RuntimeError(f"CrowdStrike API error {response['status_code']}")
                    resources = response.get("body", {}).get("resources", [])
                    if not resources:
                        return all_devices
                    # Fetch device details for this batch
                    details_resp = self.client.get_device_details(ids=resources)
                    if details_resp["status_code"] in (200, 201):
                        devices = details_resp.get("body", {}).get("resources", [])
                        all_devices.extend(devices)
                    offset += len(resources)
                    if len(resources) < limit:
                        return all_devices
                    break
                except Exception as exc:
                    self.log.error("fetch_error", error=str(exc), attempt=attempt)
                    if attempt >= max_retries:
                        raise
                    time.sleep(2 ** attempt)
        return all_devices

    def collect(self) -> list[RawDevice]:
        raw_devices = self._fetch_with_retry()
        results: list[RawDevice] = []
        for item in raw_devices:
            aid = item.get("device_id") or item.get("aid", "")
            hostname = item.get("hostname") or ""
            serial = item.get("serial_number") or ""
            mac = item.get("mac_address") or ""
            os_type = item.get("platform_name") or item.get("os_product_name", "")
            os_version = item.get("os_version") or ""
            last_user = item.get("last_interactive_user_name") or ""
            last_seen = self._parse_last_seen(item.get("last_seen"))
            macs = []
            if mac:
                macs.append(self.normalize_mac(mac))
            results.append(
                RawDevice(
                    device_id=aid,
                    hostname=hostname,
                    serial_number=serial if self.is_valid_serial(serial) else None,
                    mac_addresses=macs,
                    os_type=os_type,
                    os_version=os_version,
                    last_user=last_user,
                    last_seen=last_seen,
                    source="crowdstrike",
                    source_device_id=aid,
                    raw_data=item,
                )
            )
        return results
