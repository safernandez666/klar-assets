from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any

import requests
import structlog

from src.collectors.base import BaseCollector
from src.models import RawDevice

logger = structlog.get_logger(__name__)


class PaloAltoCollector(BaseCollector):
    def __init__(self) -> None:
        super().__init__("paloalto_vpn")
        self.panorama_host = os.getenv("PA_PANORAMA_HOST", "")
        self.api_key = os.getenv("PA_API_KEY", "")
        self.base_url = f"https://{self.panorama_host}"

    def _parse_login_time(self, value: str | None) -> datetime | None:
        if not value:
            return None
        # Palo Alto puede devolver formatos variados; intentamos ISO primero
        for fmt in ("%Y/%m/%d %H:%M:%S", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S"):
            try:
                dt = datetime.strptime(value, fmt)
                return dt.replace(tzinfo=timezone.utc)
            except Exception:
                continue
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return dt
        except Exception:
            return None

    def collect(self) -> list[RawDevice]:
        if not self.panorama_host or not self.api_key:
            self.log.warning("paloalto_credentials_missing")
            return []
        cmd = "<show><global-protect-gateway><current-user/></global-protect-gateway></show>"
        url = f"{self.base_url}/api/"
        params = {
            "type": "op",
            "cmd": cmd,
            "key": self.api_key,
        }
        resp = requests.get(url, params=params, timeout=30, verify=False)
        if resp.status_code != 200:
            raise RuntimeError(f"PaloAlto API returned {resp.status_code}")
        root = ET.fromstring(resp.content)

        results: list[RawDevice] = []
        # Estructura esperada: <response><result><entry>...
        entries = root.findall(".//entry")
        if not entries:
            # Intentar otro path posible
            entries = root.findall(".//result/entry")
        for entry in entries:
            username = entry.findtext("username") or entry.findtext("user") or ""
            public_ip = entry.findtext("public-ip") or entry.findtext("publicIp") or ""
            private_ip = entry.findtext("private-ip") or entry.findtext("privateIp") or ""
            hostname = entry.findtext("hostname") or entry.findtext("computer") or ""
            client_os = entry.findtext("client-os") or entry.findtext("clientOs") or ""
            login_time_str = entry.findtext("login-time") or entry.findtext("loginTime") or ""
            login_time = self._parse_login_time(login_time_str)
            results.append(
                RawDevice(
                    device_id=f"{username}@{hostname}" if username and hostname else f"vpn-{public_ip}",
                    hostname=hostname,
                    serial_number=None,
                    mac_addresses=[],
                    os_type=client_os,
                    os_version="",
                    last_user=username,
                    last_seen=login_time,
                    source="paloalto_vpn",
                    source_device_id=f"{username}@{hostname}" if username and hostname else f"vpn-{public_ip}",
                    raw_data={
                        "is_vpn_session": True,
                        "public_ip": public_ip,
                        "private_ip": private_ip,
                        "username": username,
                    },
                )
            )
        return results
