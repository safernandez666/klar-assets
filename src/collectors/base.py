from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import structlog

from src.models import RawDevice

logger = structlog.get_logger(__name__)


@dataclass
class CollectResult:
    devices: list[RawDevice]
    success: bool


class BaseCollector(ABC):
    def __init__(self, source_name: str) -> None:
        self.source_name = source_name
        self.log = logger.bind(source=source_name)

    @abstractmethod
    def collect(self) -> list[RawDevice]:
        """Collect devices from the source. Must return a list of RawDevice."""
        ...

    @staticmethod
    def normalize_mac(mac: str | None) -> str:
        if not mac:
            return ""
        return "".join(c for c in mac.lower() if c.isalnum())

    @staticmethod
    def is_valid_serial(serial: str | None) -> bool:
        if not serial:
            return False
        return serial.strip().lower() not in {"", "n/a", "unknown"}

    # OUI blacklist for virtualization / cloned VMs
    _UNTRUSTED_OUI = {
        "005056",  # VMware
        "000c29",  # VMware
        "000569",  # VMware
        "025041",  # VMware (locally administered)
        "080027",  # VirtualBox
        "00155d",  # Hyper-V
        "00163e",  # Xen
    }

    @classmethod
    def is_trusted_mac(cls, mac: str | None) -> bool:
        if not mac:
            return False
        norm = cls.normalize_mac(mac)
        if len(norm) < 12:
            return False
        oui = norm[:6]
        return oui not in cls._UNTRUSTED_OUI

    def safe_collect(self) -> CollectResult:
        try:
            devices = self.collect()
            self.log.info("collect_succeeded", count=len(devices))
            return CollectResult(devices=devices, success=True)
        except Exception as exc:
            self.log.error("collect_failed", error=str(exc))
            return CollectResult(devices=[], success=False)
