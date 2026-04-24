from __future__ import annotations

import re
from datetime import datetime, timezone

from src.models import NormalizedDevice


# Hostname patterns that indicate a server/VM, not a workstation
_SERVER_PATTERNS = re.compile(
    r"(?i)"
    r"bastion|server|servidor|"       # explicit server names
    r"^EC2AMAZ-|"                     # AWS Windows AMIs
    r"^ip-\d+.*\.compute\.internal$|" # AWS EC2 instances
    r"^ip-\d+.*\.us-east|^ip-\d+.*\.us-west|"  # AWS private DNS
    r"freeradius|coredns|"            # infrastructure services
    r"spei|coas-(?:live|staging|beta)|"  # banking/ops servers
    r"^ap\w+(?:drp|live)$|"          # app servers (apspeidrp, apspeilive)
    r"^bd\w+(?:drp|live)$|"          # db servers (bdspeidrp, bdspeilive)
    r"^log\w+(?:drp|live)$|"         # log servers
    r"telco-.*\.elit-i\.|"           # telecom infrastructure
    r"^CS-CORE-|"                     # core infrastructure (CS-CORE-QRO-SFA)
    r"^POAS-|^COAS$|"                # operational servers (POAS-LIVE, COAS)
    r"^OPERADOR-|"                    # operator workstations (server role)
    r"^MLCO-|"                        # MLCO servers
    r"-LIVE$|-DRP$|-STAGING$"         # environment suffixes
)


def _is_server(dev: NormalizedDevice) -> bool:
    """Detect if a device is a server/VM based on hostname patterns and characteristics."""
    for hostname in dev.hostnames:
        if _SERVER_PATTERNS.search(hostname):
            return True
    # Linux devices in CS without JC and without an owner are likely servers
    os_lower = (dev.os_type or "").lower()
    if "linux" in os_lower and not dev.owner_email:
        return True
    # VMware serial numbers indicate VMs
    if dev.serial_number and dev.serial_number.lower().startswith("vmware-"):
        return True
    return False


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

            # Detect servers/VMs — they don't need JumpCloud (MDM)
            is_server = has_cs and not has_jc and _is_server(dev)

            # Status
            is_stale = False
            if dev.days_since_seen is not None and dev.days_since_seen > stale_threshold_days:
                is_stale = True

            if is_stale:
                dev.status = "STALE"
            elif is_server:
                dev.status = "SERVER"
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
