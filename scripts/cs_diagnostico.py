#!/usr/bin/env python3
"""
Diagnóstico de comunicación CrowdStrike.

Uso:
    python3 scripts/cs_diagnostico.py SERIAL          # un equipo puntual
    python3 scripts/cs_diagnostico.py --all           # todo el fleet CS
    python3 scripts/cs_diagnostico.py --needs-reboot  # solo los que necesitan reinicio
    python3 scripts/cs_diagnostico.py --offline       # solo offline / stale / RFM

Lee credenciales de .env en el directorio actual:
    CS_CLIENT_ID, CS_CLIENT_SECRET, CS_BASE_URL
"""
from __future__ import annotations

import argparse
import os
import sys
import warnings
from datetime import datetime, timezone
from typing import Any

# ── Suprimir warnings molestos de urllib3/OpenSSL ANTES de importarlos ─
warnings.filterwarnings("ignore", message=".*NotOpenSSLWarning.*")
warnings.filterwarnings("ignore", message=".*urllib3 v2 only supports OpenSSL.*")

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


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def fmt_hours_ago(iso: str | None) -> str:
    dt = _parse_dt(iso)
    if not dt:
        return "?"
    hours = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
    return f"{hours:.1f}h"


def diagnose_device(device: dict[str, Any]) -> dict[str, Any]:
    """Extrae los campos relevantes de comunicación."""
    return {
        "hostname": device.get("hostname") or device.get("computer_name") or "?",
        "aid": device.get("device_id") or device.get("aid") or "?",
        "serial": device.get("serial_number") or "?",
        "platform": device.get("platform_name") or device.get("os_product_name") or "?",
        "status": device.get("status") or "?",
        "reduced_functionality_mode": device.get("reduced_functionality_mode") or "?",
        "reboot_required": device.get("reboot_required") or "?",
        "connection_ip": device.get("connection_ip") or "?",
        "last_seen": device.get("last_seen") or "?",
        "hours_since_seen": fmt_hours_ago(device.get("last_seen")),
    }


def find_by_serial(serial: str, client: Hosts) -> dict[str, Any] | None:
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


def fetch_all(client: Hosts) -> list[dict[str, Any]]:
    all_devices: list[dict[str, Any]] = []
    offset = 0
    limit = 500
    while True:
        response = client.query_devices_by_filter(limit=limit, offset=offset)
        if response.get("status_code") != 200:
            raise RuntimeError(f"CS query failed: {response}")
        resources = response.get("body", {}).get("resources", [])
        if not resources:
            break
        details = client.get_device_details(ids=resources)
        if details.get("status_code") == 200:
            all_devices.extend(details.get("body", {}).get("resources", []))
        offset += len(resources)
        if len(resources) < limit:
            break
    return all_devices


def print_device(diag: dict[str, Any], highlight: bool = False) -> None:
    marker = f" {C.FAIL}{C.BOLD}>>> ATENCIÓN <<<{C.END}" if highlight else ""
    status_color = C.OKGREEN if str(diag["status"]).lower() == "normal" else C.WARNING if str(diag["status"]).lower() == "contained" else C.FAIL
    rfm_color = C.FAIL if str(diag["reduced_functionality_mode"]).lower() in ("true", "yes", "1") else C.OKGREEN
    reboot_color = C.FAIL if str(diag["reboot_required"]).lower() in ("true", "yes", "1") else C.OKGREEN

    print(
        f"\n  {C.BOLD}Hostname{C.END} : {C.OKCYAN}{diag['hostname']}{C.END}{marker}\n"
        f"  {C.BOLD}AID{C.END}      : {C.DIM}{diag['aid']}{C.END}\n"
        f"  {C.BOLD}Serial{C.END}   : {diag['serial']}\n"
        f"  {C.BOLD}Platform{C.END} : {diag['platform']}\n"
        f"  {C.BOLD}Status{C.END}   : {status_color}{diag['status']}{C.END}\n"
        f"  {C.BOLD}RFM{C.END}      : {rfm_color}{diag['reduced_functionality_mode']}{C.END}\n"
        f"  {C.BOLD}Reboot{C.END}   : {reboot_color}{diag['reboot_required']}{C.END}\n"
        f"  {C.BOLD}Last IP{C.END}  : {C.OKBLUE}{diag['connection_ip']}{C.END}\n"
        f"  {C.BOLD}Last seen{C.END}: {C.DIM}{diag['last_seen']}{C.END} ({diag['hours_since_seen']})"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("serial", nargs="?", help="Número de serie a consultar")
    ap.add_argument("--all", action="store_true", help="Listar todo el fleet")
    ap.add_argument("--needs-reboot", action="store_true", help="Solo los que necesitan reinicio")
    ap.add_argument("--offline", action="store_true", help="Solo offline / stale / RFM")
    args = ap.parse_args()

    load_dotenv()
    cs_id = os.getenv("CS_CLIENT_ID", "")
    cs_sec = os.getenv("CS_CLIENT_SECRET", "")
    cs_base = os.getenv("CS_BASE_URL", "https://api.crowdstrike.com")

    if not (cs_id and cs_sec):
        print(f"{C.FAIL}ERROR:{C.END} faltan CS_CLIENT_ID / CS_CLIENT_SECRET en .env\n")
        return 1

    client = Hosts(client_id=cs_id, client_secret=cs_sec, base_url=cs_base)

    # Modo puntual por serial
    if args.serial:
        print(f"\n{C.BOLD}{C.HEADER}🔍 Buscando serial:{C.END} {C.OKCYAN}{args.serial}{C.END}\n")
        dev = find_by_serial(args.serial.strip(), client)
        if not dev:
            print(f"  {C.FAIL}No encontrado en CrowdStrike.{C.END}\n")
            return 1
        diag = diagnose_device(dev)
        needs_attention = (
            str(diag.get("reboot_required", "")).lower() in ("true", "yes", "1")
            or str(diag.get("reduced_functionality_mode", "")).lower() in ("true", "yes", "1")
            or str(diag.get("status", "")).lower() in ("offline", "contained")
        )
        print_device(diag, highlight=needs_attention)
        print()
        return 0

    # Modos de listado
    if args.all or args.needs_reboot or args.offline:
        print(f"{C.BOLD}{C.HEADER}Consultando CrowdStrike…{C.END} {C.DIM}(puede tardar){C.END}")
        devices = fetch_all(client)
        print(f"{C.OKGREEN}Total de hosts:{C.END} {C.BOLD}{len(devices)}{C.END}\n")

        for dev in devices:
            diag = diagnose_device(dev)
            reboot = str(diag.get("reboot_required", "")).lower() in ("true", "yes", "1")
            rfm = str(diag.get("reduced_functionality_mode", "")).lower() in ("true", "yes", "1")
            offline = str(diag.get("status", "")).lower() in ("offline", "contained")

            if args.needs_reboot and not reboot:
                continue
            if args.offline and not (offline or rfm):
                continue

            print_device(diag, highlight=(reboot or rfm or offline))
        print()
        return 0

    print(f"{C.WARNING}Usá --help para ver opciones.{C.END}\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())
