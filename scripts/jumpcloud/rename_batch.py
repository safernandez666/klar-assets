#!/usr/bin/env python3
"""Run KLR · Rename macOS on a controlled batch of Macs at a time.

JumpCloud's trigger API fires the command for **every** associated system at
once, so the only way to limit the blast radius is to manage associations
per batch. This helper does the bookkeeping:

1. Lists active Macs in JumpCloud.
2. Picks the next N candidates (by default, those whose hostname doesn't
   yet start with ``KLR-``).
3. Replaces the trigger command's full association list with just that
   batch — disassociates the rest.
4. Fires the trigger.
5. Optionally polls until every Mac in the batch has rotated to ``KLR-*``
   (or a configurable timeout elapses).

Re-run for each subsequent batch:

    python scripts/jumpcloud/rename_batch.py                   # next 10 not-yet-renamed
    python scripts/jumpcloud/rename_batch.py --count 5         # next 5
    python scripts/jumpcloud/rename_batch.py --serials A,B,C   # specific serials
    python scripts/jumpcloud/rename_batch.py --dry-run         # preview
    python scripts/jumpcloud/rename_batch.py --restore-all     # re-associate every Mac (cleanup)

Safety:
- Always asks for confirmation before touching JC (skip with ``--no-confirm``).
- ``--dry-run`` prints what would happen and exits without writing.
- Rename script itself is idempotent — re-running on an already-correct Mac
  just kicks the JC agent and exits 0.
"""
from __future__ import annotations

import argparse
import sys
import time

import requests
from dotenv import dotenv_values

ENV = dotenv_values(".env")
if not ENV.get("JC_API_KEY"):
    sys.exit("JC_API_KEY missing from .env")

H = {
    "x-api-key": ENV["JC_API_KEY"],
    "Accept": "application/json",
    "Content-Type": "application/json",
}
BASE = "https://console.jumpcloud.com/api"
V2 = BASE.replace("/api", "/api/v2")
TRIGGER_CMD = "69fbf860463ca835588d0e62"   # KLR · Rename macOS (Trigger)
TRIGGER_NAME = "klr955910d8a4"


# ── JC API thin wrappers ─────────────────────────────────────────────────

def _get_systems_page(skip: int) -> list[dict]:
    fields = "_id hostname displayName serialNumber os osFamily active lastContact"
    r = requests.get(
        f"{BASE}/systems?skip={skip}&limit=100&fields={fields.replace(' ', '%20')}",
        headers=H, timeout=30,
    )
    r.raise_for_status()
    return r.json().get("results", [])


def list_active_macs() -> list[dict]:
    out: list[dict] = []
    skip = 0
    while True:
        items = _get_systems_page(skip)
        for s in items:
            if s.get("active") is not True:
                continue
            os_low = (s.get("os") or "").lower()
            if s.get("osFamily") == "darwin" or "mac" in os_low:
                out.append(s)
        if len(items) < 100:
            break
        skip += 100
    return out


def get_associated() -> set[str]:
    associated: set[str] = set()
    skip = 0
    while True:
        r = requests.get(
            f"{V2}/commands/{TRIGGER_CMD}/associations?targets=system&skip={skip}&limit=100",
            headers=H, timeout=30,
        )
        if r.status_code != 200:
            break
        items = r.json()
        if not isinstance(items, list) or not items:
            break
        for it in items:
            if isinstance(it, dict) and it.get("to", {}).get("id"):
                associated.add(it["to"]["id"])
        if len(items) < 100:
            break
        skip += 100
    return associated


def add_association(sid: str) -> bool:
    r = requests.post(
        f"{V2}/commands/{TRIGGER_CMD}/associations",
        headers=H, json={"op": "add", "type": "system", "id": sid}, timeout=30,
    )
    return r.status_code in (200, 204)


def remove_association(sid: str) -> bool:
    r = requests.post(
        f"{V2}/commands/{TRIGGER_CMD}/associations",
        headers=H, json={"op": "remove", "type": "system", "id": sid}, timeout=30,
    )
    return r.status_code in (200, 204)


def fire_trigger() -> dict:
    r = requests.post(
        f"{BASE}/command/trigger/{TRIGGER_NAME}",
        headers=H, json={}, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def patch_displayname(system_id: str, name: str) -> bool:
    """Force JC's console ``displayName`` to match a freshly-set hostname.

    JC's agent never refreshes ``displayName`` — that field is set at
    enrollment and stays sticky forever. After a rename, the technical
    ``hostname`` updates correctly but the console search bar (which
    looks at ``displayName``) keeps returning the old label. This PUT
    is the only way to align them without waiting for the app's 6h
    auto-reconciler.
    """
    r = requests.put(
        f"{BASE}/systems/{system_id}",
        headers=H, json={"displayName": name}, timeout=30,
    )
    return r.status_code in (200, 204)


# ── Selection ────────────────────────────────────────────────────────────

def pick_batch(macs: list[dict], *, count: int, include_renamed: bool, serials: list[str] | None) -> list[dict]:
    if serials:
        wanted = {s.strip().upper() for s in serials}
        return [m for m in macs if (m.get("serialNumber") or "").upper() in wanted]
    pool = macs if include_renamed else [
        m for m in macs if not (m.get("hostname") or "").startswith("KLR-")
    ]
    pool.sort(key=lambda m: (m.get("serialNumber") or "", m.get("_id") or ""))
    return pool[:count]


# ── Collision detection (avoid the LAST5 dup foot-gun) ───────────────────

LAST_N = 5  # Mirrors the rename script's LAST5 suffix.


def _suffix(serial: str) -> str:
    s = (serial or "").strip().upper()
    return s[-LAST_N:] if len(s) >= LAST_N else ""


def find_collisions(batch: list[dict], all_macs: list[dict]) -> list[tuple[str, list[dict]]]:
    """Return ``[(suffix, [macs...])]`` for any LAST5 suffix shared by two
    or more Macs, considering both the batch and the rest of the active
    fleet. The rename script does ``KLR-XXX-<LAST5>`` so any duplicate
    suffix means duplicate hostname after the rename runs.

    Only collisions that involve at least one batch member are returned —
    pre-existing duplicates that don't touch this batch aren't our problem
    right now.
    """
    by_suffix: dict[str, list[dict]] = {}
    seen_ids: set[str] = set()
    for m in batch + all_macs:
        if m.get("_id") in seen_ids:
            continue
        seen_ids.add(m.get("_id") or "")
        suf = _suffix(m.get("serialNumber") or "")
        if suf:
            by_suffix.setdefault(suf, []).append(m)
    batch_ids = {m["_id"] for m in batch}
    out: list[tuple[str, list[dict]]] = []
    for suf, group in by_suffix.items():
        if len(group) < 2:
            continue
        if any(m["_id"] in batch_ids for m in group):
            out.append((suf, group))
    return out


# ── Verification ─────────────────────────────────────────────────────────

def verify_batch(batch_ids: set[str], *, timeout_s: int, poll_every: int) -> dict[str, str]:
    """Poll JC until every batch system reports a hostname starting with ``KLR-``,
    or the timeout elapses. Returns ``{system_id: hostname}`` for the final state."""
    deadline = time.time() + timeout_s
    last_state: dict[str, str] = {}
    while time.time() < deadline:
        fresh = list_active_macs()
        last_state = {m["_id"]: (m.get("hostname") or "") for m in fresh if m["_id"] in batch_ids}
        renamed = sum(1 for h in last_state.values() if h.startswith("KLR-"))
        print(f"  poll @ {int(time.time() - (deadline - timeout_s))}s: {renamed}/{len(batch_ids)} renamed")
        if renamed == len(batch_ids):
            return last_state
        time.sleep(poll_every)
    return last_state


# ── Main ────────────────────────────────────────────────────────────────

def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--count", type=int, default=10,
                   help="How many Macs to include in this batch (default 10)")
    p.add_argument("--serials", default="",
                   help="Comma-separated serials. Overrides --count and --include-renamed.")
    p.add_argument("--include-renamed", action="store_true",
                   help="Also include Macs already named KLR-* (rename will idempotent-skip)")
    p.add_argument("--dry-run", action="store_true",
                   help="Print what would happen and exit. No JC writes.")
    p.add_argument("--no-confirm", action="store_true",
                   help="Skip the interactive prompt (use in scripts)")
    p.add_argument("--no-verify", action="store_true",
                   help="Don't poll for hostname rotation after firing")
    p.add_argument("--verify-timeout", type=int, default=300,
                   help="Seconds to wait for all batch Macs to report KLR-* (default 300)")
    p.add_argument("--restore-all", action="store_true",
                   help="Re-associate every active Mac to the trigger command and exit "
                        "(useful as cleanup after batching is done)")
    p.add_argument("--allow-collisions", action="store_true",
                   help="Proceed even if two batch Macs share the same LAST5 serial "
                        "suffix (would produce duplicate hostnames). Default is to abort.")
    p.add_argument("--skip-reconcile", action="store_true",
                   help="Don't PUT JC displayNames after the rename. Useful only if "
                        "you intend to let the app's reconciler handle it on the next "
                        "sync. Default: reconcile inline so JC console search works "
                        "immediately.")
    args = p.parse_args()

    print("Fetching active Macs from JumpCloud…")
    macs = list_active_macs()
    print(f"  {len(macs)} active Macs found.")

    if args.restore_all:
        print("\nRestoring full-fleet association on the trigger command…")
        associated = get_associated()
        all_ids = {m["_id"] for m in macs}
        to_add = all_ids - associated
        to_remove = associated - all_ids   # systems no longer active
        for sid in to_add:
            add_association(sid)
        for sid in to_remove:
            remove_association(sid)
        print(f"  added: {len(to_add)} · removed (no longer active): {len(to_remove)}")
        print(f"  total associated now: {len(get_associated())}")
        return 0

    serials = [s.strip() for s in args.serials.split(",") if s.strip()] or None
    batch = pick_batch(
        macs, count=args.count, include_renamed=args.include_renamed, serials=serials,
    )
    if not batch:
        print("\nNo eligible Macs to rename. Either everything is done or your "
              "filter excluded everyone. Try --include-renamed if you want a forced re-run.")
        return 0

    print(f"\nBatch ({len(batch)} Macs):")
    for m in batch:
        sn = m.get("serialNumber") or "—"
        name = (m.get("displayName") or m.get("hostname") or "—")[:50]
        cur = m.get("hostname") or "—"
        marker = "(already KLR-*)" if cur.startswith("KLR-") else ""
        print(f"  · {sn:14s}  {name:50s} → cur:{cur:35s} {marker}")

    # Predict LAST5 suffix collisions before firing — the rename script
    # generates ``KLR-XXX-<LAST5>`` so two serials sharing the suffix
    # would resolve to the same hostname after the rename runs.
    collisions = find_collisions(batch, macs)
    if collisions:
        print(f"\n⚠️  COLLISION WARNING — {len(collisions)} suffix(es) shared by 2+ Macs:")
        for suf, group in collisions:
            print(f"  suffix={suf}  ({len(group)} Macs would resolve to KLR-???-{suf}):")
            for m in group:
                in_batch = " (in batch)" if m["_id"] in {b["_id"] for b in batch} else ""
                cur = m.get("hostname") or "—"
                print(f"    · {m.get('serialNumber'):14s}  cur:{cur}{in_batch}")
        print("\nThe rename script would set BOTH Macs of each pair to the "
              "same hostname. Causes DNS/Bonjour conflicts on local networks.")
        if not args.allow_collisions:
            print("\nAbort. Re-run with --allow-collisions to override, "
                  "or pick a different batch.")
            return 2
        else:
            print("\n--allow-collisions set; proceeding anyway.")

    if args.dry_run:
        print("\n(dry-run; nothing changed)")
        return 0

    if not args.no_confirm:
        c = input("\nProceed? (yes/no): ").strip().lower()
        if c not in ("yes", "y"):
            print("Aborted.")
            return 1

    batch_ids = {m["_id"] for m in batch}

    print("\nUpdating associations on the trigger command…")
    associated = get_associated()
    to_remove = associated - batch_ids
    to_add = batch_ids - associated
    print(f"  before: {len(associated)} associated")
    print(f"  removing: {len(to_remove)} (other systems)")
    print(f"  adding:   {len(to_add)} (batch)")
    for sid in to_remove:
        remove_association(sid)
    for sid in to_add:
        add_association(sid)
    print(f"  after:  {len(get_associated())} associated (should be {len(batch_ids)})")

    print("\nFiring trigger…")
    out = fire_trigger()
    print(f"  response: {out}")

    if args.no_verify:
        print("\nDone. Re-run for next batch when ready.")
        return 0

    print(f"\nPolling JC inventory until all {len(batch_ids)} report KLR-* "
          f"(timeout {args.verify_timeout}s)…")
    state = verify_batch(batch_ids, timeout_s=args.verify_timeout, poll_every=20)

    print("\nFinal state:")
    ok = bad = 0
    for sid, hostname in sorted(state.items(), key=lambda kv: kv[1]):
        if hostname.startswith("KLR-"):
            print(f"  ✅  {hostname}")
            ok += 1
        else:
            print(f"  ⏳  {hostname or '<empty>'}  (system_id={sid})")
            bad += 1
    print(f"\nResult: {ok} renamed · {bad} pending/failed")
    if bad:
        print("Pending Macs may be offline or have a slow agent — re-check later "
              "or investigate per-Mac. The JC agent typically picks up the command "
              "within minutes once the Mac is online.")

    # Reconcile JC console displayNames inline. The app's auto-reconciler
    # would do this on the next 6h cron / Refresh JumpCloud click, but
    # nobody wants to switch tabs to verify the rename worked. PUT each
    # drifted displayName so the JC console search finds the device by
    # its new name immediately.
    if not args.skip_reconcile:
        print("\nReconciling JC displayNames…")
        patched = 0
        for sid, hostname in state.items():
            if not hostname.startswith("KLR-"):
                continue
            # Re-read current to learn displayName (state only has hostname)
            r = requests.get(f"{BASE}/systems/{sid}", headers=H, timeout=30)
            if r.status_code != 200:
                continue
            current = (r.json().get("displayName") or "").strip()
            if current == hostname:
                continue
            if patch_displayname(sid, hostname):
                print(f"  patched {hostname:18s}  was: {current}")
                patched += 1
        print(f"  → {patched} displayName(s) reconciled")
    return 0


if __name__ == "__main__":
    sys.exit(main())
