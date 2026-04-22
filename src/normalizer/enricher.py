from __future__ import annotations

from datetime import datetime, timezone

from src.models import NormalizedDevice


class Enricher:
    def enrich(self, devices: list[NormalizedDevice]) -> list[NormalizedDevice]:
        now = datetime.now(timezone.utc)
        stale_threshold_days = 90

        for dev in devices:
            # Days since last seen
            if dev.last_seen:
                dev.days_since_seen = int((now - dev.last_seen).total_seconds() / 86400)
            else:
                dev.days_since_seen = None

            # Coverage gaps
            gaps: list[str] = []
            has_cs = "crowdstrike" in dev.sources
            has_okta = "okta" in dev.sources
            has_jc = "jumpcloud" in dev.sources

            if not has_cs:
                gaps.append("missing_edr")
            if not has_okta:
                gaps.append("missing_idp")
            if not has_jc:
                gaps.append("missing_mdm")
            dev.coverage_gaps = gaps

            # Status — source of truth for device management is JumpCloud (MDM)
            # MANAGED = JC + CS (device is enrolled in MDM and has EDR)
            # FULLY_MANAGED = JC + CS + Okta + owner (complete visibility)
            is_stale = False
            if dev.days_since_seen is not None and dev.days_since_seen > stale_threshold_days:
                is_stale = True

            if is_stale:
                dev.status = "STALE"
            elif has_jc and has_cs and has_okta and dev.owner_email:
                dev.status = "FULLY_MANAGED"
            elif has_jc and has_cs:
                dev.status = "MANAGED"
            elif has_jc and not has_cs:
                dev.status = "NO_EDR"
            elif has_cs and not has_jc:
                dev.status = "NO_MDM"
            elif has_okta and not has_cs and not has_jc:
                dev.status = "IDP_ONLY"
            else:
                dev.status = "UNKNOWN"

        return devices
