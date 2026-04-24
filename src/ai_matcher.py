from __future__ import annotations

import json
import os
from typing import Any

import structlog
from openai import OpenAI

from src.models import NormalizedDevice

logger = structlog.get_logger(__name__)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

MATCH_PROMPT = """You are a device inventory analyst. You will receive pairs of device records from different IT sources (JumpCloud, CrowdStrike, Okta). Your job is to determine if two records refer to the SAME physical device.

Consider:
- Serial number match is very strong evidence (almost certain match if same serial).
- Owner email match + same OS family is strong evidence.
- Hostnames can differ wildly: Okta uses display names ("Kim's MacBook Air"), JumpCloud uses network hostnames ("ip-192-168-1-72.us-east-2.compute.internal"), CrowdStrike uses OS hostnames ("MacBook-Pro-de-Klar-5.local").
- OS type must be compatible (Mac/macOS/Mac OS X/darwin are all the same; Windows/Win are the same).
- If serial numbers are present in BOTH and they DIFFER, they are DIFFERENT devices. Do not match them.
- One person CAN have multiple devices. If ambiguous, say NO.

For each pair, respond with:
- match: true/false
- confidence: 0.0-1.0
- reason: brief explanation

Respond ONLY with a JSON array: [{"pair_id": 0, "match": true, "confidence": 0.85, "reason": "same serial, compatible OS"}]"""


def _normalize_os_family(os_type: str | None) -> str:
    if not os_type:
        return ""
    os_lower = os_type.lower().strip()
    if any(w in os_lower for w in ("mac", "darwin", "osx", "macos")):
        return "macos"
    if any(w in os_lower for w in ("win", "windows")):
        return "windows"
    if any(w in os_lower for w in ("linux", "ubuntu", "centos", "rhel")):
        return "linux"
    return os_lower


def _build_candidate_pairs(devices: list[NormalizedDevice]) -> list[dict[str, Any]]:
    """Find candidate pairs of single-source devices that might be the same device."""
    # Collect all single-source low-confidence devices
    singles: list[NormalizedDevice] = []
    multi: list[NormalizedDevice] = []
    for d in devices:
        if len(d.sources) == 1 and d.confidence_score <= 0.3:
            singles.append(d)
        else:
            multi.append(d)

    if not singles:
        return []

    pairs: list[dict[str, Any]] = []

    # Strategy 1: serial match between singles from different sources
    serial_idx: dict[str, list[NormalizedDevice]] = {}
    for d in singles:
        if d.serial_number:
            sn = d.serial_number.lower()
            serial_idx.setdefault(sn, []).append(d)

    for sn, devs in serial_idx.items():
        sources_seen = {d.sources[0] for d in devs}
        if len(sources_seen) >= 2:
            # Same serial in different sources — high probability match
            for i, dev_a in enumerate(devs):
                for dev_b in devs[i + 1:]:
                    if dev_a.sources[0] != dev_b.sources[0]:
                        pairs.append(_make_pair(len(pairs), dev_a, dev_b))

    # Strategy 2: singles that might match already-matched multi-source devices
    # (a single-source device whose serial matches a multi-source device's serial)
    multi_serials = {}
    for d in multi:
        if d.serial_number:
            multi_serials[d.serial_number.lower()] = d

    for d in singles:
        if d.serial_number and d.serial_number.lower() in multi_serials:
            existing = multi_serials[d.serial_number.lower()]
            if d.sources[0] not in existing.sources:
                pairs.append(_make_pair(len(pairs), d, existing))

    # Strategy 3: owner email + OS family match between singles from different sources
    owner_os_idx: dict[str, list[NormalizedDevice]] = {}
    for d in singles:
        if d.owner_email:
            os_fam = _normalize_os_family(d.os_type)
            if os_fam:
                key = f"{d.owner_email.lower()}|{os_fam}"
                owner_os_idx.setdefault(key, []).append(d)

    for key, devs in owner_os_idx.items():
        sources_seen = {d.sources[0] for d in devs}
        if len(sources_seen) >= 2:
            for i, dev_a in enumerate(devs):
                for dev_b in devs[i + 1:]:
                    if dev_a.sources[0] != dev_b.sources[0]:
                        # Skip if serials conflict
                        if dev_a.serial_number and dev_b.serial_number:
                            if dev_a.serial_number.lower() != dev_b.serial_number.lower():
                                continue
                        pairs.append(_make_pair(len(pairs), dev_a, dev_b))

    return pairs


def _make_pair(pair_id: int, a: NormalizedDevice, b: NormalizedDevice) -> dict[str, Any]:
    return {
        "pair_id": pair_id,
        "device_a": {
            "canonical_id": a.canonical_id,
            "hostnames": a.hostnames,
            "serial": a.serial_number,
            "owner": a.owner_email,
            "os": a.os_type,
            "source": a.sources[0] if a.sources else "?",
            "sources": a.sources,
            "last_seen": a.last_seen.isoformat() if a.last_seen else None,
        },
        "device_b": {
            "canonical_id": b.canonical_id,
            "hostnames": b.hostnames,
            "serial": b.serial_number,
            "owner": b.owner_email,
            "os": b.os_type,
            "source": b.sources[0] if b.sources else "?",
            "sources": b.sources,
            "last_seen": b.last_seen.isoformat() if b.last_seen else None,
        },
    }


def ai_match(devices: list[NormalizedDevice]) -> list[NormalizedDevice]:
    """Use OpenAI to improve matching of low-confidence single-source devices."""
    if not OPENAI_API_KEY:
        logger.info("ai_matcher_skipped", reason="no_openai_key")
        return devices

    pairs = _build_candidate_pairs(devices)
    if not pairs:
        logger.info("ai_matcher_no_candidates")
        return devices

    # Limit to 30 pairs per batch
    pairs = pairs[:30]
    logger.info("ai_matcher_evaluating", pairs=len(pairs))

    try:
        client = OpenAI(api_key=OPENAI_API_KEY)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": MATCH_PROMPT},
                {"role": "user", "content": json.dumps(pairs, default=str)},
            ],
            temperature=0.1,
            max_tokens=2000,
        )
        content = (response.choices[0].message.content or "[]").strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1] if "\n" in content else content[3:]
        if content.endswith("```"):
            content = content[:-3]
        results = json.loads(content.strip())
    except Exception as exc:
        logger.error("ai_matcher_failed", error=str(exc))
        return devices

    # Apply confirmed matches
    merges: list[tuple[str, str, float, str]] = []
    for r in results:
        pid = r.get("pair_id", -1)
        if pid < 0 or pid >= len(pairs):
            continue
        if r.get("match") and r.get("confidence", 0) >= 0.7:
            pair = pairs[pid]
            merges.append((
                pair["device_a"]["canonical_id"],
                pair["device_b"]["canonical_id"],
                r["confidence"],
                r.get("reason", "ai_match"),
            ))

    if not merges:
        logger.info("ai_matcher_no_matches_confirmed")
        return devices

    logger.info("ai_matcher_merging", count=len(merges))

    dev_index = {d.canonical_id: d for d in devices}
    merged_ids: set[str] = set()

    for id_a, id_b, conf, reason in merges:
        if id_a in merged_ids or id_b in merged_ids:
            continue
        dev_a = dev_index.get(id_a)
        dev_b = dev_index.get(id_b)
        if not dev_a or not dev_b:
            continue

        # Merge B into A (keep the one with more sources)
        if len(dev_b.sources) > len(dev_a.sources):
            dev_a, dev_b = dev_b, dev_a
            id_a, id_b = id_b, id_a

        for h in dev_b.hostnames:
            if h not in dev_a.hostnames:
                dev_a.hostnames.append(h)
        if dev_b.serial_number and not dev_a.serial_number:
            dev_a.serial_number = dev_b.serial_number
        for m in dev_b.mac_addresses:
            if m not in dev_a.mac_addresses:
                dev_a.mac_addresses.append(m)
        for s in dev_b.sources:
            if s not in dev_a.sources:
                dev_a.sources.append(s)
        for k, v in dev_b.source_ids.items():
            if k not in dev_a.source_ids:
                dev_a.source_ids[k] = v
        if not dev_a.owner_email and dev_b.owner_email:
            dev_a.owner_email = dev_b.owner_email
            dev_a.owner_name = dev_b.owner_name
        if dev_b.last_seen and (not dev_a.last_seen or dev_b.last_seen > dev_a.last_seen):
            dev_a.last_seen = dev_b.last_seen
        if dev_b.first_seen and (not dev_a.first_seen or dev_b.first_seen < dev_a.first_seen):
            dev_a.first_seen = dev_b.first_seen

        dev_a.confidence_score = round(conf * 0.85, 2)  # AI confidence scaled
        dev_a.match_reason = f"ai_match:{reason}"

        merged_ids.add(id_b)
        logger.info("ai_merged",
                     a_host=dev_a.hostnames[0] if dev_a.hostnames else "?",
                     b_host=dev_b.hostnames[0] if dev_b.hostnames else "?",
                     confidence=conf, reason=reason)

    result = [d for d in devices if d.canonical_id not in merged_ids]
    logger.info("ai_matcher_done", original=len(devices), merged=len(merged_ids), final=len(result))
    return result
