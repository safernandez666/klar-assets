from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class RawDevice(BaseModel):
    device_id: str | None = None
    hostname: str | None = None
    serial_number: str | None = None
    mac_addresses: list[str] = Field(default_factory=list)
    os_type: str | None = None
    os_version: str | None = None
    last_user: str | None = None
    last_seen: datetime | None = None
    source: str
    source_device_id: str
    raw_data: dict[str, Any] = Field(default_factory=dict)


class NormalizedDevice(BaseModel):
    canonical_id: str = Field(default_factory=lambda: str(uuid4()))
    hostnames: list[str] = Field(default_factory=list)
    serial_number: str | None = None
    mac_addresses: list[str] = Field(default_factory=list)
    owner_email: str | None = None
    owner_name: str | None = None
    os_type: str | None = None
    sources: list[str] = Field(default_factory=list)
    source_ids: dict[str, str] = Field(default_factory=dict)
    status: str = "UNKNOWN"
    confidence_score: float = 0.0
    match_reason: str = ""
    is_active_vpn: bool = False
    coverage_gaps: list[str] = Field(default_factory=list)
    days_since_seen: int | None = None
    first_seen: datetime = Field(default_factory=datetime.utcnow)
    last_seen: datetime = Field(default_factory=datetime.utcnow)
    deleted_at: datetime | None = None
