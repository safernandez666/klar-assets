from __future__ import annotations

import os

import structlog

logger = structlog.get_logger(__name__)


# Vars whose absence makes the app pointless: the sync engine treats CrowdStrike
# and JumpCloud as "critical sources" and aborts the run if either fails.
REQUIRED: list[tuple[str, str]] = [
    ("CS_CLIENT_ID", "CrowdStrike client ID — needed for EDR sync (critical source)"),
    ("CS_CLIENT_SECRET", "CrowdStrike client secret"),
    ("JC_API_KEY", "JumpCloud API key — needed for MDM sync (critical source)"),
]

# Vars that significantly degrade functionality but don't prevent startup.
RECOMMENDED: list[tuple[str, str]] = [
    ("OKTA_DOMAIN", "Okta IDP sync and compliance controls (CTL-004/005) will be incomplete"),
    ("OKTA_API_TOKEN", "Okta IDP sync and compliance controls (CTL-004/005) will be incomplete"),
    ("JWT_SECRET", "Sessions invalidate on every restart (a random secret is generated each boot)"),
]

# Vars that disable a non-essential feature when missing.
OPTIONAL: list[tuple[str, str]] = [
    ("OPENAI_API_KEY", "AI-enhanced device matching disabled"),
    ("SLACK_WEBHOOK_URL", "Slack alerts disabled"),
]

# Auth: at least one of these paths must be configured, otherwise no one can log in.
_OKTA_OIDC_VARS = ("OKTA_OIDC_ISSUER", "OKTA_OIDC_CLIENT_ID", "OKTA_OIDC_CLIENT_SECRET")


class ConfigError(RuntimeError):
    pass


def _is_set(name: str) -> bool:
    return bool(os.getenv(name, "").strip())


def validate_config() -> None:
    """Validate environment configuration at startup.

    Raises ConfigError when a required variable is missing or when no auth
    method is configured. Logs warnings for recommended/optional gaps so
    operators see them in the boot log.
    """
    missing_required = [name for name, _ in REQUIRED if not _is_set(name)]
    missing_recommended = [(name, hint) for name, hint in RECOMMENDED if not _is_set(name)]
    missing_optional = [(name, hint) for name, hint in OPTIONAL if not _is_set(name)]

    has_local_auth = _is_set("AUTH_PASSWORD")
    has_okta_oidc = all(_is_set(v) for v in _OKTA_OIDC_VARS)

    for name, hint in REQUIRED:
        if name in missing_required:
            logger.error("config_missing_required", var=name, impact=hint)

    for name, hint in missing_recommended:
        logger.warning("config_missing_recommended", var=name, impact=hint)

    for name, hint in missing_optional:
        logger.info("config_missing_optional", var=name, impact=hint)

    errors: list[str] = []
    if missing_required:
        errors.append(
            "Missing required environment variables: " + ", ".join(missing_required)
        )
    if not has_local_auth and not has_okta_oidc:
        errors.append(
            "No auth method configured: set AUTH_PASSWORD for local login, "
            "or all of " + ", ".join(_OKTA_OIDC_VARS) + " for Okta SSO"
        )

    if errors:
        for msg in errors:
            logger.error("config_validation_failed", error=msg)
        raise ConfigError(" | ".join(errors))

    logger.info(
        "config_validated",
        required_ok=len(REQUIRED),
        recommended_missing=len(missing_recommended),
        optional_missing=len(missing_optional),
        auth=("okta_oidc" if has_okta_oidc else "local") + ("+local" if has_okta_oidc and has_local_auth else ""),
    )
