from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any

from rapidfuzz import fuzz

from src.collectors.base import BaseCollector
from src.models import NormalizedDevice, RawDevice


_SUFFIX_RE = re.compile(r"-(ARG|AR|US|UK|BR)$", re.IGNORECASE)


def _strip_hostname_suffix(hostname: str | None) -> str:
    if not hostname:
        return ""
    h = hostname.strip().lower()
    return _SUFFIX_RE.sub("", h)


def _normalize_hostname(hostname: str | None) -> str:
    return (hostname or "").strip().lower()


_GENERIC_HOSTNAME_RE = re.compile(
    r"^ip-\d+-\d+-\d+-\d+\..*\.(?:compute|ec2)\.internal$|"
    r"^\d+\.\d+\.\d+\.\d+$|"
    r"\.internal\.cloudapp\.net$|"
    r"\.c\.\w+\.internal$"
)


def _is_generic_hostname(hostname: str | None) -> bool:
    if not hostname:
        return True
    return bool(_GENERIC_HOSTNAME_RE.search(hostname.lower().strip()))


def _normalize_os(os_type: str | None) -> str:
    """Normalize OS type to a canonical form for comparison."""
    if not os_type:
        return ""
    os_lower = os_type.lower().strip()
    if any(w in os_lower for w in ("mac", "darwin", "osx")):
        return "macos"
    if any(w in os_lower for w in ("win", "windows")):
        return "windows"
    if any(w in os_lower for w in ("linux", "ubuntu", "centos", "rhel", "debian")):
        return "linux"
    if any(w in os_lower for w in ("ios", "iphone", "ipad")):
        return "ios"
    if "android" in os_lower:
        return "android"
    return os_lower


def _is_mobile_device(device: RawDevice) -> bool:
    """Detect mobile devices (phones/tablets) that should be excluded from analysis."""
    os_norm = _normalize_os(device.os_type)
    if os_norm in ("ios", "android"):
        return True
    # Heuristic: Okta devices with mobile-looking hostnames
    hostname = (device.hostname or "").lower()
    mobile_keywords = ("iphone", "ipad", "galaxy", "pixel", "redmi", "oppo",
                       "huawei", "honor", "xiaomi", "samsung", "motorola",
                       "oneplus", "realme", "vivo", "poco", "nothing phone")
    if any(kw in hostname for kw in mobile_keywords):
        return True
    return False


def _make_canonical_id(group: list[RawDevice]) -> str:
    serials = sorted(
        {
            d.serial_number.lower()
            for d in group
            if d.serial_number and BaseCollector.is_valid_serial(d.serial_number)
        }
    )
    macs = sorted(
        {
            BaseCollector.normalize_mac(m)
            for d in group
            for m in d.mac_addresses
            if BaseCollector.normalize_mac(m)
        }
    )
    cs_aids = sorted(
        {d.source_device_id for d in group if d.source == "crowdstrike" and d.source_device_id}
    )
    okta_ids = sorted(
        {d.source_device_id for d in group if d.source == "okta" and d.source_device_id}
    )

    if serials:
        return f"serial-{serials[0]}"
    if macs:
        return f"mac-{macs[0]}"
    if cs_aids:
        return f"cs-{cs_aids[0]}"
    if okta_ids:
        return f"okta-{okta_ids[0]}"

    parts = sorted({f"{d.source}:{d.source_device_id}" for d in group})
    key = "|".join(parts)
    h = hashlib.sha256(key.encode()).hexdigest()[:16]
    return f"host-{h}"


class Deduplicator:
    def deduplicate(self, devices: list[RawDevice]) -> list[NormalizedDevice]:
        # Filter out mobile devices — only analyze desktop/laptop
        devices = [d for d in devices if not _is_mobile_device(d)]

        # Build Okta email pool for owner validation
        okta_emails: set[str] = set()
        for d in devices:
            if d.source == "okta" and d.last_user:
                okta_emails.add(d.last_user.lower())

        # Detect cloned/outlier MACs (appear more than 5 times) and serials (>3 times)
        from collections import Counter
        all_macs = [
            BaseCollector.normalize_mac(m)
            for d in devices
            for m in d.mac_addresses
            if BaseCollector.normalize_mac(m) and BaseCollector.is_trusted_mac(m)
        ]
        mac_counts = Counter(all_macs)
        untrusted_macs: set[str] = {m for m, c in mac_counts.items() if c > 5}

        all_serials = [
            d.serial_number.lower()
            for d in devices
            if d.serial_number and BaseCollector.is_valid_serial(d.serial_number)
        ]
        serial_counts = Counter(all_serials)
        untrusted_serials: set[str] = {s for s, c in serial_counts.items() if c > 3}

        # Build an index of owner_email → group for cross-source matching
        groups: list[list[RawDevice]] = []
        group_match_reasons: list[str] = []
        serial_index: dict[str, list[int]] = {}
        mac_index: dict[str, list[int]] = {}
        cs_aid_index: dict[str, list[int]] = {}
        okta_id_index: dict[str, list[int]] = {}
        owner_os_index: dict[str, list[int]] = {}  # "email|os" → group indices
        group_hostnames: list[list[str]] = []
        group_os: list[str] = []  # normalized OS per group

        def _usable_mac(mac: str | None) -> str:
            norm = BaseCollector.normalize_mac(mac)
            if not norm or not BaseCollector.is_trusted_mac(mac):
                return ""
            if norm in untrusted_macs:
                return ""
            return norm

        def _usable_serial(serial: str | None) -> str:
            if not serial or not BaseCollector.is_valid_serial(serial):
                return ""
            s = serial.lower()
            if s in untrusted_serials:
                return ""
            return s

        def _add_to_group(group_idx: int, device: RawDevice, reason: str = "") -> None:
            groups[group_idx].append(device)
            if reason and (not group_match_reasons[group_idx] or group_match_reasons[group_idx].startswith("single_source:")):
                group_match_reasons[group_idx] = reason
            serial = device.serial_number
            s_key = _usable_serial(serial)
            if s_key:
                serial_index.setdefault(s_key, []).append(group_idx)
            for mac in device.mac_addresses:
                m_key = _usable_mac(mac)
                if m_key:
                    mac_index.setdefault(m_key, []).append(group_idx)
            if device.source == "crowdstrike" and device.source_device_id:
                cs_aid_index.setdefault(device.source_device_id, []).append(group_idx)
            if device.source == "okta" and device.source_device_id:
                okta_id_index.setdefault(device.source_device_id, []).append(group_idx)
            sh = _strip_hostname_suffix(device.hostname)
            if sh:
                group_hostnames[group_idx].append(sh)
            # Update OS for group if not yet set
            dev_os = _normalize_os(device.os_type)
            if dev_os and not group_os[group_idx]:
                group_os[group_idx] = dev_os
            # Owner+OS index for cross-source matching
            if device.last_user and dev_os:
                key = f"{device.last_user.lower()}|{dev_os}"
                owner_os_index.setdefault(key, []).append(group_idx)

        # Sort: devices with serial first, so serial index is populated early
        devices = sorted(devices, key=lambda d: (0 if _usable_serial(d.serial_number) else 1, d.source))

        for dev in devices:
            matched_group: int | None = None
            match_reason = ""

            # 1. serial_number exact (trusted only, no outliers)
            s_key = _usable_serial(dev.serial_number)
            if s_key:
                if s_key in serial_index:
                    matched_group = serial_index[s_key][0]
                    match_reason = "serial_number:exact"

            # 2. mac_address exact (trusted only, no outliers)
            if matched_group is None:
                for mac in dev.mac_addresses:
                    m_key = _usable_mac(mac)
                    if m_key and m_key in mac_index:
                        matched_group = mac_index[m_key][0]
                        match_reason = "mac:exact"
                        break

            # 3. crowdstrike_aid exact
            if matched_group is None:
                if dev.source == "crowdstrike" and dev.source_device_id:
                    aid = dev.source_device_id
                    if aid in cs_aid_index:
                        matched_group = cs_aid_index[aid][0]
                        match_reason = "crowdstrike_aid:exact"

            # 4. okta_device_id exact
            if matched_group is None:
                if dev.source == "okta" and dev.source_device_id:
                    oid = dev.source_device_id
                    if oid in okta_id_index:
                        matched_group = okta_id_index[oid][0]
                        match_reason = "okta_device_id:exact"

            # 5. Owner email + OS type match (cross-source correlation)
            #    Only match across different sources to avoid self-matching
            #    BLOCK if both have serial numbers and they differ
            if matched_group is None:
                if dev.last_user:
                    dev_os = _normalize_os(dev.os_type)
                    dev_serial = _usable_serial(dev.serial_number)
                    if dev_os:
                        key = f"{dev.last_user.lower()}|{dev_os}"
                        if key in owner_os_index:
                            for candidate_idx in owner_os_index[key]:
                                group_sources = {d.source for d in groups[candidate_idx]}
                                if dev.source not in group_sources:
                                    # Block if serials conflict
                                    if dev_serial:
                                        group_serials = {
                                            _usable_serial(d.serial_number)
                                            for d in groups[candidate_idx]
                                            if _usable_serial(d.serial_number)
                                        }
                                        if group_serials and dev_serial not in group_serials:
                                            continue
                                    matched_group = candidate_idx
                                    match_reason = "owner_os:exact"
                                    break

            # 6. hostname fuzzy >= 95% (stricter) + same OS type
            #    BLOCK if both have serial numbers and they differ — different devices
            if matched_group is None:
                sh = _strip_hostname_suffix(dev.hostname)
                dev_os = _normalize_os(dev.os_type)
                dev_serial = _usable_serial(dev.serial_number)
                if sh and not _is_generic_hostname(dev.hostname):
                    for gidx, gh_list in enumerate(group_hostnames):
                        # Require same OS family if both are known
                        g_os = group_os[gidx]
                        if dev_os and g_os and dev_os != g_os:
                            continue
                        # If both have serials and they differ, skip — different devices
                        if dev_serial:
                            group_serials = {
                                _usable_serial(d.serial_number)
                                for d in groups[gidx]
                                if _usable_serial(d.serial_number)
                            }
                            if group_serials and dev_serial not in group_serials:
                                continue
                        for gh in gh_list:
                            if _is_generic_hostname(gh):
                                continue
                            score = fuzz.ratio(sh, gh)
                            if score >= 95:
                                matched_group = gidx
                                match_reason = f"hostname:fuzzy:{score}%"
                                break
                        if matched_group is not None:
                            break

            if matched_group is not None:
                _add_to_group(matched_group, dev, match_reason)
            else:
                new_idx = len(groups)
                groups.append([dev])
                group_match_reasons.append(match_reason if match_reason else f"single_source:{dev.source}")
                hostnames_list: list[str] = []
                if dev.hostname and not _is_generic_hostname(dev.hostname):
                    hostnames_list.append(_strip_hostname_suffix(dev.hostname))
                group_hostnames.append(hostnames_list)
                group_os.append(_normalize_os(dev.os_type))
                if s_key:
                    serial_index.setdefault(s_key, []).append(new_idx)
                for mac in dev.mac_addresses:
                    m_key = _usable_mac(mac)
                    if m_key:
                        mac_index.setdefault(m_key, []).append(new_idx)
                if dev.source == "crowdstrike" and dev.source_device_id:
                    cs_aid_index.setdefault(dev.source_device_id, []).append(new_idx)
                if dev.source == "okta" and dev.source_device_id:
                    okta_id_index.setdefault(dev.source_device_id, []).append(new_idx)
                # Owner+OS index
                if dev.last_user:
                    dev_os = _normalize_os(dev.os_type)
                    if dev_os:
                        key = f"{dev.last_user.lower()}|{dev_os}"
                        owner_os_index.setdefault(key, []).append(new_idx)

        normalized: list[NormalizedDevice] = []
        for gidx, group in enumerate(groups):
            nd = self._merge_group(group, okta_emails, group_match_reasons[gidx])
            normalized.append(nd)

        # Post-merge: combine devices that share the same serial but ended up
        # in different groups (e.g. due to okta_device_id matching first)
        normalized = self._post_merge_by_serial(normalized)
        return normalized

    def _post_merge_by_serial(self, devices: list[NormalizedDevice]) -> list[NormalizedDevice]:
        """Merge normalized devices that share the same serial number."""
        serial_groups: dict[str, list[int]] = {}
        for i, d in enumerate(devices):
            if d.serial_number and BaseCollector.is_valid_serial(d.serial_number):
                sn = d.serial_number.lower()
                serial_groups.setdefault(sn, []).append(i)

        merged_indices: set[int] = set()
        for sn, indices in serial_groups.items():
            if len(indices) <= 1:
                continue
            # Merge all into the first one
            primary_idx = indices[0]
            primary = devices[primary_idx]
            for secondary_idx in indices[1:]:
                secondary = devices[secondary_idx]
                # Merge secondary into primary
                for h in secondary.hostnames:
                    if h not in primary.hostnames:
                        primary.hostnames.append(h)
                for m in secondary.mac_addresses:
                    if m not in primary.mac_addresses:
                        primary.mac_addresses.append(m)
                for s in secondary.sources:
                    if s not in primary.sources:
                        primary.sources.append(s)
                for k, v in secondary.source_ids.items():
                    if k not in primary.source_ids:
                        primary.source_ids[k] = v
                if not primary.owner_email and secondary.owner_email:
                    primary.owner_email = secondary.owner_email
                    primary.owner_name = secondary.owner_name
                if secondary.last_seen and (not primary.last_seen or secondary.last_seen > primary.last_seen):
                    primary.last_seen = secondary.last_seen
                if secondary.first_seen and (not primary.first_seen or secondary.first_seen < primary.first_seen):
                    primary.first_seen = secondary.first_seen
                merged_indices.add(secondary_idx)

            # Update confidence based on merged sources
            n_sources = len(primary.sources)
            if n_sources >= 3:
                primary.confidence_score = 1.0
                primary.match_reason = "serial_number:post_merge"
            elif n_sources >= 2:
                primary.confidence_score = 0.85
                primary.match_reason = "serial_number:post_merge"
            primary.canonical_id = _make_canonical_id(
                [RawDevice(device_id="", hostname=h, serial_number=primary.serial_number,
                           mac_addresses=[], os_type="", os_version="", last_user="",
                           last_seen=None, source=s, source_device_id=primary.source_ids.get(s, ""), raw_data={})
                 for h in primary.hostnames for s in primary.sources]
            )

        return [d for i, d in enumerate(devices) if i not in merged_indices]

    def _merge_group(
        self,
        group: list[RawDevice],
        okta_emails: set[str],
        match_reason: str,
    ) -> NormalizedDevice:
        hostnames: list[str] = []
        serials: list[str] = []
        macs: list[str] = []
        sources: list[str] = []
        source_ids: dict[str, str] = {}
        os_type = ""
        timezone_str: str | None = None
        first_seen: datetime | None = None
        last_seen: datetime | None = None

        # Owner candidates
        okta_binding: tuple[str, str] | None = None
        okta_verify: tuple[str, str] | None = None
        cs_user: str | None = None
        jc_user: str | None = None

        for d in group:
            if d.hostname:
                h = d.hostname.strip()
                if h and h not in hostnames:
                    hostnames.append(h)
            if d.serial_number and BaseCollector.is_valid_serial(d.serial_number):
                s = d.serial_number.strip()
                if s and s not in serials:
                    serials.append(s)
            for m in d.mac_addresses:
                nm = BaseCollector.normalize_mac(m)
                if nm and nm not in macs:
                    macs.append(nm)
            if d.source not in sources:
                sources.append(d.source)
            if d.source not in source_ids:
                source_ids[d.source] = d.source_device_id
            # OS preference: crowdstrike > okta > jumpcloud
            if d.os_type:
                if not os_type:
                    os_type = d.os_type
                elif d.source == "crowdstrike":
                    os_type = d.os_type
            # Timezone preference: crowdstrike > jumpcloud (Okta devices rarely expose it)
            if d.timezone:
                if not timezone_str:
                    timezone_str = d.timezone
                elif d.source == "crowdstrike":
                    timezone_str = d.timezone
            # First/last seen
            if d.last_seen:
                if first_seen is None or d.last_seen < first_seen:
                    first_seen = d.last_seen
                if last_seen is None or d.last_seen > last_seen:
                    last_seen = d.last_seen

            # Owner extraction
            if d.source == "okta":
                owner_email = d.raw_data.get("owner_email") or d.last_user
                owner_name = d.raw_data.get("owner_name") or ""
                if owner_email:
                    okta_binding = (owner_email, owner_name or "")
                if d.raw_data.get("registered"):
                    okta_verify = (owner_email or d.last_user or "", owner_name or "")
            elif d.source == "crowdstrike" and d.last_user:
                cs_user = d.last_user
            elif d.source == "jumpcloud" and d.last_user:
                jc_user = d.last_user

        owner_email: str | None = None
        owner_name: str | None = None

        # Owner priority: JumpCloud user (MDM truth) > CrowdStrike user
        # (validated against Okta pool) > Okta binding.
        # JC user email should match Okta identity in most cases.
        if jc_user:
            owner_email = jc_user
            owner_name = None
        elif cs_user and cs_user.lower() in okta_emails:
            owner_email = cs_user
            owner_name = None
        elif okta_binding and okta_binding[0]:
            owner_email = okta_binding[0]
            owner_name = okta_binding[1] or None
        elif okta_verify and okta_verify[0]:
            owner_email = okta_verify[0]
            owner_name = okta_verify[1] or None

        # Confidence score
        unique_sources = len(sources)
        if match_reason.startswith("serial_number:exact") and unique_sources >= 3:
            confidence = 1.0
        elif match_reason.startswith("serial_number:exact") and unique_sources >= 2:
            confidence = 0.85
        elif match_reason.startswith("serial_number:exact"):
            confidence = 0.7
        elif match_reason.startswith("mac:exact") and unique_sources >= 2:
            confidence = 0.8
        elif match_reason.startswith("mac:exact"):
            confidence = 0.6
        elif match_reason.startswith("owner_os:exact") and unique_sources >= 2:
            confidence = 0.65
        elif match_reason.startswith("crowdstrike_aid:exact") or match_reason.startswith("okta_device_id:exact"):
            confidence = 0.6
        elif match_reason.startswith("hostname:fuzzy") and unique_sources >= 3:
            confidence = 0.75
        elif match_reason.startswith("hostname:fuzzy") and unique_sources >= 2:
            confidence = 0.55
        elif match_reason.startswith("hostname:fuzzy"):
            confidence = 0.4
        else:
            confidence = 0.2
            match_reason = f"single_source:{sources[0]}"

        now = datetime.now(timezone.utc)
        if first_seen is None:
            first_seen = now
        if last_seen is None:
            last_seen = now

        from src.normalizer.region import region_from_timezone
        return NormalizedDevice(
            canonical_id=_make_canonical_id(group),
            hostnames=hostnames,
            serial_number=serials[0] if serials else None,
            mac_addresses=macs,
            owner_email=owner_email,
            owner_name=owner_name,
            os_type=os_type or None,
            sources=sources,
            source_ids=source_ids,
            status="UNKNOWN",
            confidence_score=confidence,
            match_reason=match_reason,
            is_active_vpn=False,
            coverage_gaps=[],
            days_since_seen=None,
            timezone=timezone_str,
            region=region_from_timezone(timezone_str),
            first_seen=first_seen,
            last_seen=last_seen,
            deleted_at=None,
        )
