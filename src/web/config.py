"""Centralized environment-variable reads and immutable constants for the web layer.

Every `os.getenv()` call that lived in `server.py` is now here. Other modules
import the resulting constants instead of re-reading the environment.
"""
from __future__ import annotations

import os
import secrets
from pathlib import Path

# ── Database & app URLs ──────────────────────────────────────────────────────
DB_PATH = os.getenv("DB_PATH", "data/devices.db")
APP_URL = os.getenv("APP_URL", "http://localhost:8080")
_IS_HTTPS = APP_URL.startswith("https://")

# ── Sync scheduler ───────────────────────────────────────────────────────────
SYNC_INTERVAL_HOURS = int(os.getenv("SYNC_INTERVAL_HOURS", "6"))
SYNC_ON_STARTUP = os.getenv("SYNC_ON_STARTUP", "true").lower() == "true"

# ── Auth (local) ─────────────────────────────────────────────────────────────
AUTH_USERNAME = os.getenv("AUTH_USERNAME", "admin")
AUTH_PASSWORD = os.getenv("AUTH_PASSWORD", "")
JWT_SECRET = os.getenv("JWT_SECRET", secrets.token_hex(32))
JWT_EXPIRY_HOURS = 24
SESSION_COOKIE = os.getenv("SESSION_COOKIE", "dn_session")

# ── Auth (Okta OIDC) ────────────────────────────────────────────────────────
OKTA_OIDC_ISSUER = os.getenv("OKTA_OIDC_ISSUER", "")
OKTA_OIDC_CLIENT_ID = os.getenv("OKTA_OIDC_CLIENT_ID", "")
OKTA_OIDC_CLIENT_SECRET = os.getenv("OKTA_OIDC_CLIENT_SECRET", "")
OKTA_ALLOWED_DOMAINS = os.getenv("OKTA_ALLOWED_DOMAINS", "").strip()
_OKTA_OIDC_ENABLED = bool(OKTA_OIDC_ISSUER and OKTA_OIDC_CLIENT_ID and OKTA_OIDC_CLIENT_SECRET)

# ── Source-configured flags (for /api/settings status panel) ────────────────
CS_CONFIGURED = bool(os.getenv("CS_CLIENT_ID"))
JC_CONFIGURED = bool(os.getenv("JC_API_KEY"))
OKTA_CONFIGURED = bool(os.getenv("OKTA_API_TOKEN"))
OPENAI_CONFIGURED = bool(os.getenv("OPENAI_API_KEY"))
SLACK_CONFIGURED = bool(os.getenv("SLACK_WEBHOOK_URL"))

# ── Console deep-link URLs ──────────────────────────────────────────────────
# Falcon UI host mirrors the API host (api.us-2.crowdstrike.com → falcon.us-2.crowdstrike.com)
_CS_API = os.getenv("CS_BASE_URL", "https://api.crowdstrike.com").rstrip("/")
_CS_FALCON = _CS_API.replace("//api.", "//falcon.")
_OKTA_DOMAIN = os.getenv("OKTA_DOMAIN", "").strip().rstrip("/")
if _OKTA_DOMAIN.endswith(".okta.com"):
    _OKTA_ADMIN = f"https://{_OKTA_DOMAIN[:-len('.okta.com')]}-admin.okta.com"
elif _OKTA_DOMAIN:
    _OKTA_ADMIN = f"https://{_OKTA_DOMAIN}"
else:
    _OKTA_ADMIN = ""

CONSOLE_URLS: dict[str, str] = {
    "crowdstrike": f"{_CS_FALCON}/hosts/details/{{id}}",
    "jumpcloud": "https://console.jumpcloud.com/#/devices/{id}/details",
    "okta": f"{_OKTA_ADMIN}/admin/devices/{{id}}" if _OKTA_ADMIN else "",
}


def build_source_urls(source_ids: dict[str, str] | None) -> dict[str, str]:
    """Materialize the deep-link URL for each source the device was seen in."""
    if not source_ids:
        return {}
    out: dict[str, str] = {}
    for source, sid in source_ids.items():
        template = CONSOLE_URLS.get(source)
        if template and sid:
            out[source] = template.replace("{id}", sid)
    return out

# ── Frontend bundle ──────────────────────────────────────────────────────────
DIST_DIR = Path(__file__).resolve().parents[2] / "frontend" / "dist"

# ── Build metadata ───────────────────────────────────────────────────────────
APP_VERSION = os.getenv("APP_VERSION", "dev")
APP_BUILD_DATE = os.getenv("APP_BUILD_DATE", "")

# ── Public routes (skipped by auth middleware) ───────────────────────────────
PUBLIC_PATHS = {
    "/auth/login",
    "/auth/logout",
    "/auth/okta",
    "/auth/okta/callback",
    "/auth/me",
    "/favicon.svg",
    "/healthz",
    "/api/version",
}

# ── Risk scoring weights (per device status) ─────────────────────────────────
RISK_WEIGHTS: dict[str, int] = {
    "FULLY_MANAGED": 100,
    "MANAGED": 80,
    "SERVER": 75,
    "NO_MDM": 40,
    "NO_EDR": 25,
    "IDP_ONLY": 15,
    "STALE": 5,
    "UNKNOWN": 10,
}

# ── CSV/XLSX export columns ──────────────────────────────────────────────────
EXPORT_COLUMNS = [
    "canonical_id", "hostnames", "serial_number", "owner_email", "owner_name",
    "os_type", "status", "sources", "coverage_gaps", "confidence_score",
    "match_reason", "days_since_seen", "first_seen", "last_seen",
]

# ── Compliance controls metadata (CTL-001 .. CTL-008) ────────────────────────
CONTROLS_META = [
    {"id": "CTL-001", "ref": "", "title": "Dispositivos Okta sin MDM",
     "objective": "Detectar dispositivos que acceden pero no están en MDM",
     "description": "Verifica que todos los dispositivos registrados en Okta (IDP) tengan un agente JumpCloud (MDM) instalado. "
                    "Un dispositivo solo en Okta significa que el usuario accede a recursos corporativos desde un equipo sin gestión centralizada. "
                    "Acción: validar si el dispositivo es personal (aceptable) o corporativo sin MDM (requiere instalación de JC).",
     "source_from": "okta", "source_to": "jumpcloud"},
    {"id": "CTL-002", "ref": "KRI0021", "title": "Dispositivos JC sin EDR",
     "objective": "Asegurar cobertura de seguridad (antimalware)",
     "description": "Verifica que todos los dispositivos gestionados por JumpCloud (MDM) tengan el agente CrowdStrike (EDR) instalado. "
                    "Un equipo con MDM pero sin EDR tiene gestión pero no protección contra amenazas. "
                    "Acción: instalar CrowdStrike en los dispositivos afectados. Asociado al indicador de riesgo KRI0021.",
     "source_from": "jumpcloud", "source_to": "crowdstrike"},
    {"id": "CTL-003", "ref": "", "title": "EDR en dispositivos sin MDM",
     "objective": "Detectar shadow IT o drift",
     "description": "Detecta dispositivos que tienen CrowdStrike (EDR) pero no JumpCloud (MDM). "
                    "Esto puede indicar shadow IT (equipo no autorizado con solo el agente de seguridad), "
                    "drift de configuración, o un equipo que perdió la conexión con JC. "
                    "Acción: verificar si el equipo debe estar en JC o si es un equipo personal/no gestionado.",
     "source_from": "crowdstrike", "source_to": "jumpcloud"},
    {"id": "CTL-004", "ref": "", "title": "Acceso sin protección",
     "objective": "Riesgo real de acceso — usuarios sin MDM ni EDR",
     "description": "Identifica usuarios que acceden a recursos corporativos vía Okta desde dispositivos sin MDM ni EDR. "
                    "Es el escenario de mayor riesgo: acceso sin visibilidad ni protección. "
                    "Acción: contactar al usuario para validar el dispositivo e instalar los agentes correspondientes.",
     "source_from": "okta", "source_to": ""},
    {"id": "CTL-005", "ref": "CIS0102", "title": "Usuarios sin device en MDM",
     "objective": "Depuración de MDM — usuarios Okta activos sin device en JC",
     "description": "Cruza la lista de usuarios activos de Okta (excluyendo agentes externos y cuentas de sistema) "
                    "contra los owners de dispositivos en JumpCloud. Un usuario sin device en JC puede significar que "
                    "usa un equipo personal, que no se le asignó equipo, o que el binding usuario-device no está configurado. "
                    "Acción: verificar si el usuario necesita un equipo corporativo asignado. Asociado al control CIS0102.",
     "source_from": "okta", "source_to": "jumpcloud"},
    {"id": "CTL-006", "ref": "", "title": "Device MDM sin usuario asignado",
     "objective": "Depuración de MDM — devices JC sin owner",
     "description": "Detecta dispositivos en JumpCloud que no tienen un usuario asignado. "
                    "Un device sin owner dificulta la trazabilidad y la respuesta ante incidentes. "
                    "Puede ser un equipo de contingencia, un server mal clasificado, o falta de binding en JC. "
                    "Acción: asignar el usuario correspondiente en JumpCloud o reclasificar como equipo compartido.",
     "source_from": "jumpcloud", "source_to": ""},
    {"id": "CTL-007", "ref": "CIS0101", "title": "Device MDM sin reportar",
     "objective": "Efectividad de MDM — agentes JC sin responder 30+ días",
     "description": "Detecta dispositivos con agente JumpCloud que no reportan hace más de 30 días. "
                    "Puede indicar un equipo apagado, desvinculado, robado, o con el agente dañado. "
                    "Impacta la efectividad real del MDM — tener un agente que no reporta es como no tenerlo. "
                    "Acción: contactar al usuario, verificar estado del equipo. Asociado al control CIS0101.",
     "source_from": "jumpcloud", "source_to": ""},
    {"id": "CTL-008", "ref": "KRI0022", "title": "EDR sin reportar",
     "objective": "Efectividad de EDR — agentes CS con firmas desactualizadas",
     "description": "Detecta dispositivos con agente CrowdStrike que no reportan hace más de 30 días. "
                    "Un EDR sin reportar no protege contra amenazas actuales — las firmas quedan desactualizadas "
                    "y no hay telemetría para detección de incidentes. "
                    "Acción: verificar conectividad del agente y forzar check-in. Asociado al indicador KRI0022.",
     "source_from": "crowdstrike", "source_to": ""},
]
