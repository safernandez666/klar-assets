#!/usr/bin/env python3
"""
Sync JumpCloud `displayName` to the current OS-level hostname.

Use after the rename script ran on a batch of endpoints. CrowdStrike
typically reflects the new hostname within minutes, while JumpCloud's
`displayName` stays stuck at the enrollment-time value forever.

Usage:
  python sync_jc_displayname.py SERIAL [SERIAL ...]
  python sync_jc_displayname.py --all-klr      # everything matching KLR-* in CS
  python sync_jc_displayname.py --dry-run ...  # preview without writing
"""
from __future__ import annotations

import argparse
import os
import sys

import requests
from dotenv import load_dotenv
from falconpy import Hosts

load_dotenv()

JC_API_KEY = os.environ["JC_API_KEY"]
JC_BASE = "https://console.jumpcloud.com/api"
HEADERS = {"x-api-key": JC_API_KEY, "Accept": "application/json", "Content-Type": "application/json"}


def cs_hostname_by_serial(cs: Hosts, serial: str) -> str | None:
    ids = cs.query_devices_by_filter(filter=f'serial_number:"{serial}"')["body"].get("resources") or []
    if not ids:
        return None
    devs = cs.get_device_details(ids=ids)["body"].get("resources") or []
    return devs[0].get("hostname") if devs else None


def cs_all_klr_hostnames(cs: Hosts) -> dict[str, str]:
    """Return {serial: hostname} for every CS device whose hostname starts with KLR-."""
    out: dict[str, str] = {}
    offset = None
    while True:
        kw: dict = {"filter": "hostname:*'KLR-*'", "limit": 1000}
        if offset:
            kw["offset"] = offset
        resp = cs.query_devices_by_filter_scroll(**kw)["body"]
        ids = resp.get("resources") or []
        if not ids:
            break
        devs = cs.get_device_details(ids=ids)["body"].get("resources") or []
        for d in devs:
            sn = (d.get("serial_number") or "").strip().upper()
            hn = d.get("hostname")
            if sn and hn and hn.startswith("KLR-"):
                out[sn] = hn
        offset = resp.get("meta", {}).get("pagination", {}).get("offset")
        if not offset:
            break
    return out


def jc_lookup_by_serial(serial: str) -> dict | None:
    body = {"filter": {"and": [{"serialNumber": serial}]}}
    r = requests.post(f"{JC_BASE}/search/systems", headers=HEADERS, json=body, timeout=30)
    r.raise_for_status()
    results = r.json().get("results") or []
    return results[0] if results else None


def jc_patch_displayname(system_id: str, new_name: str) -> dict:
    r = requests.put(f"{JC_BASE}/systems/{system_id}", headers=HEADERS, json={"displayName": new_name}, timeout=30)
    r.raise_for_status()
    return r.json()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("serials", nargs="*", help="Serial numbers to sync")
    ap.add_argument("--all-klr", action="store_true", help="Sync every CS host whose name starts with KLR-")
    ap.add_argument("--dry-run", action="store_true", help="Preview without writing to JC")
    args = ap.parse_args()

    cs = Hosts(client_id=os.environ["CS_CLIENT_ID"], client_secret=os.environ["CS_CLIENT_SECRET"])

    if args.all_klr:
        print("[*] Scanning CrowdStrike for KLR-* hostnames…")
        targets = cs_all_klr_hostnames(cs)
        print(f"[*] Found {len(targets)} candidates in CS.")
    elif args.serials:
        targets = {s.upper(): cs_hostname_by_serial(cs, s.upper()) for s in args.serials}
    else:
        ap.print_help()
        return 1

    updated = skipped = failed = 0
    for serial, cs_name in targets.items():
        if not cs_name:
            print(f"  [skip] {serial:14s} → not in CrowdStrike")
            skipped += 1
            continue

        sysrec = jc_lookup_by_serial(serial)
        if not sysrec:
            print(f"  [skip] {serial:14s} → not in JumpCloud")
            skipped += 1
            continue

        sid = sysrec["_id"]
        cur = sysrec.get("displayName") or ""
        if cur == cs_name:
            print(f"  [ok]   {serial:14s} → {cs_name} (already in sync)")
            continue

        if args.dry_run:
            print(f"  [DRY]  {serial:14s} → {cur!r:50s} → {cs_name!r}")
            continue

        try:
            jc_patch_displayname(sid, cs_name)
            print(f"  [PUT]  {serial:14s} → {cur!r:50s} → {cs_name!r}")
            updated += 1
        except requests.HTTPError as e:
            print(f"  [err]  {serial:14s} → {e}")
            failed += 1

    print(f"\n[*] Done. updated={updated} skipped={skipped} failed={failed}")
    return 0 if not failed else 2


if __name__ == "__main__":
    sys.exit(main())
