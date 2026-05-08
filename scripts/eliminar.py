#!/usr/bin/env python3
"""
Elimina una máquina por número de serie de las tres fuentes:
JumpCloud (DELETE), CrowdStrike (hide_host) y Okta (deactivate + delete).

Uso:
    python3 scripts/eliminar.py SERIAL
    python3 scripts/eliminar.py SERIAL --dry-run
    python3 scripts/eliminar.py SERIAL --yes
    python3 scripts/eliminar.py SERIAL --skip jumpcloud,okta

Lee credenciales de .env en el directorio actual:
    JC_API_KEY
    CS_CLIENT_ID, CS_CLIENT_SECRET, CS_BASE_URL
    OKTA_DOMAIN, OKTA_API_TOKEN
"""
from __future__ import annotations

import argparse
import os
import sys
import warnings
from typing import Any

# ── Suprimir warnings molestos de urllib3/OpenSSL ANTES de importarlos ─
warnings.filterwarnings("ignore", message=".*NotOpenSSLWarning.*")
warnings.filterwarnings("ignore", message=".*urllib3 v2 only supports OpenSSL.*")

import requests
from dotenv import load_dotenv
from falconpy import Hosts


# ── Colores ANSI ──────────────────────────────────────────────────────
class C:
    HEADER = "\033[95m"
    OKBLUE = "\033[94m"
    OKCYAN = "\033[96m"
    OKGREEN = "\033[92m"
    WARNING = "\033[93m"
    FAIL = "\033[91m"
    BOLD = "\033[1m"
    UNDERLINE = "\033[4m"
    DIM = "\033[2m"
    END = "\033[0m"


def _ok(text: str) -> str:
    return f"{C.OKGREEN}✓{C.END} {text}"


def _err(text: str) -> str:
    return f"{C.FAIL}✗{C.END} {text}"


def _warn(text: str) -> str:
    return f"{C.WARNING}⚠{C.END} {text}"


def _info(text: str) -> str:
    return f"{C.OKBLUE}ℹ{C.END} {text}"


# ──────────────────────────────────────────────────────────────────────
# Lookup helpers
# ──────────────────────────────────────────────────────────────────────

def jc_find(serial: str, api_key: str) -> dict[str, Any] | None:
    r = requests.post(
        "https://console.jumpcloud.com/api/search/systems",
        headers={"x-api-key": api_key, "Content-Type": "application/json", "Accept": "application/json"},
        json={"searchFilter": {"searchTerm": serial, "fields": ["serialNumber"]}},
        timeout=30,
    )
    r.raise_for_status()
    results = r.json().get("results", [])
    return results[0] if results else None


def cs_find(serial: str, client: Hosts) -> dict[str, Any] | None:
    q = client.query_devices_by_filter(filter=f"serial_number:'{serial}'")
    if q.get("status_code") != 200:
        raise RuntimeError(f"CS query failed: {q}")
    ids = q["body"].get("resources", [])
    if not ids:
        return None
    d = client.get_device_details(ids=ids)
    if d.get("status_code") != 200:
        raise RuntimeError(f"CS detail failed: {d}")
    resources = d["body"].get("resources", [])
    return resources[0] if resources else None


def okta_find(serial: str, domain: str, token: str) -> dict[str, Any] | None:
    r = requests.get(
        f"https://{domain}/api/v1/devices",
        headers={"Authorization": f"SSWS {token}", "Accept": "application/json"},
        params={"search": f'profile.serialNumber eq "{serial}"', "limit": 20},
        timeout=30,
    )
    r.raise_for_status()
    items = r.json()
    return items[0] if items else None


# ──────────────────────────────────────────────────────────────────────
# Delete helpers
# ──────────────────────────────────────────────────────────────────────

def jc_delete(system_id: str, api_key: str) -> None:
    r = requests.delete(
        f"https://console.jumpcloud.com/api/systems/{system_id}",
        headers={"x-api-key": api_key, "Accept": "application/json"},
        timeout=30,
    )
    if r.status_code not in (200, 204):
        raise RuntimeError(f"JC delete failed [{r.status_code}]: {r.text}")


def cs_hide(aid: str, client: Hosts) -> None:
    resp = client.perform_action(action_name="hide_host", body={"ids": [aid]})
    if resp.get("status_code") not in (200, 202):
        raise RuntimeError(f"CS hide_host failed: {resp}")
    errors = resp.get("body", {}).get("errors") or []
    if errors:
        raise RuntimeError(f"CS hide_host errors: {errors}")


def okta_delete(device_id: str, status: str, domain: str, token: str) -> None:
    base = f"https://{domain}/api/v1/devices/{device_id}"
    headers = {"Authorization": f"SSWS {token}", "Accept": "application/json"}
    if status and status.upper() == "ACTIVE":
        r = requests.post(f"{base}/lifecycle/deactivate", headers=headers, timeout=30)
        if r.status_code not in (200, 204):
            raise RuntimeError(f"Okta deactivate failed [{r.status_code}]: {r.text}")
    r = requests.delete(base, headers=headers, timeout=30)
    if r.status_code not in (200, 204):
        raise RuntimeError(f"Okta delete failed [{r.status_code}]: {r.text}")


# ──────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("serial", help="Número de serie del equipo a eliminar")
    ap.add_argument("--dry-run", action="store_true", help="Solo busca y muestra; no elimina")
    ap.add_argument("--yes", action="store_true", help="Salta confirmación")
    ap.add_argument("--skip", default="", help="CSV de fuentes a saltear: jumpcloud,crowdstrike,okta")
    args = ap.parse_args()

    load_dotenv()
    skip = {s.strip().lower() for s in args.skip.split(",") if s.strip()}
    serial = args.serial.strip()

    jc_key = os.getenv("JC_API_KEY", "")
    cs_id = os.getenv("CS_CLIENT_ID", "")
    cs_sec = os.getenv("CS_CLIENT_SECRET", "")
    cs_base = os.getenv("CS_BASE_URL", "https://api.crowdstrike.com")
    okta_dom = os.getenv("OKTA_DOMAIN", "")
    okta_tok = os.getenv("OKTA_API_TOKEN", "")

    cs_client = Hosts(client_id=cs_id, client_secret=cs_sec, base_url=cs_base) if cs_id and cs_sec else None

    print(f"\n{C.BOLD}{C.HEADER}🔍 Buscando serial:{C.END} {C.OKCYAN}{serial}{C.END}\n")
    findings: dict[str, dict[str, Any] | None] = {}

    # JumpCloud
    if "jumpcloud" in skip or not jc_key:
        findings["jumpcloud"] = None
        reason = "--skip" if "jumpcloud" in skip else "no JC_API_KEY"
        print(f"  {C.DIM}[JC]{C.END}   {_warn(f'skipped ({reason})')}")
    else:
        try:
            jc = jc_find(serial, jc_key)
            findings["jumpcloud"] = jc
            if jc:
                host = jc.get("hostname", "?")
                sid = jc.get("_id", "?")
                active = jc.get("active", "?")
                act_color = C.OKGREEN if active is True else C.FAIL
                print(f"  {C.OKBLUE}[JC]{C.END}   {_ok(f'{host}')} (id={C.DIM}{sid}{C.END}) active={act_color}{active}{C.END}")
            else:
                print(f"  {C.DIM}[JC]{C.END}   — no encontrado —")
        except Exception as e:
            print(f"  {C.OKBLUE}[JC]{C.END}   {_err(f'ERROR: {e}')}")
            findings["jumpcloud"] = None

    # CrowdStrike
    if "crowdstrike" in skip or not cs_client:
        findings["crowdstrike"] = None
        reason = "--skip" if "crowdstrike" in skip else "no CS credentials"
        print(f"  {C.DIM}[CS]{C.END}   {_warn(f'skipped ({reason})')}")
    else:
        try:
            cs = cs_find(serial, cs_client)
            findings["crowdstrike"] = cs
            if cs:
                host = cs.get("hostname", "?")
                aid = cs.get("device_id", "?")
                status = cs.get("status", "?")
                print(f"  {C.OKBLUE}[CS]{C.END}   {_ok(f'{host}')} (aid={C.DIM}{aid}{C.END}) status={C.OKCYAN}{status}{C.END}")
            else:
                print(f"  {C.DIM}[CS]{C.END}   — no encontrado —")
        except Exception as e:
            print(f"  {C.OKBLUE}[CS]{C.END}   {_err(f'ERROR: {e}')}")
            findings["crowdstrike"] = None

    # Okta
    if "okta" in skip or not (okta_dom and okta_tok):
        findings["okta"] = None
        reason = "--skip" if "okta" in skip else "no OKTA credentials"
        print(f"  {C.DIM}[Okta]{C.END} {_warn(f'skipped ({reason})')}")
    else:
        try:
            ok = okta_find(serial, okta_dom, okta_tok)
            findings["okta"] = ok
            if ok:
                p = ok.get("profile", {}) or {}
                disp = p.get("displayName", "?")
                oid = ok.get("id", "?")
                status = ok.get("status", "?")
                print(f"  {C.OKBLUE}[Okta]{C.END} {_ok(f'{disp}')} (id={C.DIM}{oid}{C.END}) status={C.OKCYAN}{status}{C.END}")
            else:
                print(f"  {C.DIM}[Okta]{C.END} — no encontrado —")
        except Exception as e:
            print(f"  {C.OKBLUE}[Okta]{C.END} {_err(f'ERROR: {e}')}")
            findings["okta"] = None

    targets = [k for k, v in findings.items() if v]
    if not targets:
        print(f"\n{C.WARNING}No hay nada que eliminar.{C.END} Saliendo.\n")
        return 0

    print(f"\n{C.BOLD}A eliminar en:{C.END} {C.OKGREEN}{', '.join(targets)}{C.END}")
    if args.dry_run:
        print(f"\n{C.WARNING}{C.BOLD}Modo --dry-run:{C.END} no se elimina nada.\n")
        return 0

    if not args.yes:
        try:
            ans = input(f"\n{C.BOLD}¿Confirmar eliminación?{C.END} (escribí '{C.OKGREEN}si{C.END}'): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print(f"\n{C.FAIL}Cancelado.{C.END}\n")
            return 1
        if ans not in ("si", "sí", "yes", "y"):
            print(f"{C.FAIL}Cancelado.{C.END}\n")
            return 1

    print()
    failed = []
    if findings["jumpcloud"]:
        try:
            jc_delete(findings["jumpcloud"]["_id"], jc_key)
            print(f"  {C.OKBLUE}[JC]{C.END}   {_ok('eliminado')}")
        except Exception as e:
            print(f"  {C.OKBLUE}[JC]{C.END}   {_err(f'FAIL: {e}')}")
            failed.append("jumpcloud")
    if findings["crowdstrike"]:
        try:
            cs_hide(findings["crowdstrike"]["device_id"], cs_client)
            print(f"  {C.OKBLUE}[CS]{C.END}   {_ok('hide_host disparado')} {C.DIM}(CS no borra; oculta del inventario){C.END}")
        except Exception as e:
            print(f"  {C.OKBLUE}[CS]{C.END}   {_err(f'FAIL: {e}')}")
            failed.append("crowdstrike")
    if findings["okta"]:
        try:
            okta_delete(findings["okta"]["id"], findings["okta"].get("status", ""), okta_dom, okta_tok)
            print(f"  {C.OKBLUE}[Okta]{C.END} {_ok('deactivate + delete')}")
        except Exception as e:
            print(f"  {C.OKBLUE}[Okta]{C.END} {_err(f'FAIL: {e}')}")
            failed.append("okta")

    print()
    if failed:
        print(f"{C.FAIL}{C.BOLD}Terminado con errores en:{C.END} {', '.join(failed)}\n")
        return 2
    print(f"{C.OKGREEN}{C.BOLD}Terminado OK.{C.END}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
