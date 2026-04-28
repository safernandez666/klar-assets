from __future__ import annotations

import pytest

from src.config import ConfigError, validate_config


_FULL_ENV = {
    "CS_CLIENT_ID": "cs-id",
    "CS_CLIENT_SECRET": "cs-secret",
    "JC_API_KEY": "jc-key",
    "OKTA_DOMAIN": "example.okta.com",
    "OKTA_API_TOKEN": "okta-token",
    "JWT_SECRET": "jwt",
    "AUTH_PASSWORD": "pw",
    "OPENAI_API_KEY": "oai",
    "SLACK_WEBHOOK_URL": "https://hooks.slack.com/x",
    "OKTA_OIDC_ISSUER": "https://example.okta.com/oauth2/default",
    "OKTA_OIDC_CLIENT_ID": "client-id",
    "OKTA_OIDC_CLIENT_SECRET": "client-secret",
}


def _apply(monkeypatch: pytest.MonkeyPatch, env: dict[str, str]) -> None:
    for key in list(_FULL_ENV.keys()) + ["AUTH_USERNAME"]:
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)


def test_all_required_set_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    _apply(monkeypatch, _FULL_ENV)
    validate_config()


def test_missing_required_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    env = dict(_FULL_ENV)
    del env["CS_CLIENT_ID"]
    _apply(monkeypatch, env)
    with pytest.raises(ConfigError, match="CS_CLIENT_ID"):
        validate_config()


def test_blank_required_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    env = dict(_FULL_ENV)
    env["JC_API_KEY"] = "   "
    _apply(monkeypatch, env)
    with pytest.raises(ConfigError, match="JC_API_KEY"):
        validate_config()


def test_missing_optional_only_warns(monkeypatch: pytest.MonkeyPatch) -> None:
    env = {k: v for k, v in _FULL_ENV.items() if k not in {"OPENAI_API_KEY", "SLACK_WEBHOOK_URL"}}
    _apply(monkeypatch, env)
    validate_config()


def test_missing_recommended_only_warns(monkeypatch: pytest.MonkeyPatch) -> None:
    env = {k: v for k, v in _FULL_ENV.items() if k not in {"OKTA_DOMAIN", "OKTA_API_TOKEN", "JWT_SECRET"}}
    _apply(monkeypatch, env)
    validate_config()


def test_no_auth_configured_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    env = {
        k: v
        for k, v in _FULL_ENV.items()
        if k not in {"AUTH_PASSWORD", "OKTA_OIDC_ISSUER", "OKTA_OIDC_CLIENT_ID", "OKTA_OIDC_CLIENT_SECRET"}
    }
    _apply(monkeypatch, env)
    with pytest.raises(ConfigError, match="auth method"):
        validate_config()


def test_okta_oidc_alone_satisfies_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    env = {k: v for k, v in _FULL_ENV.items() if k != "AUTH_PASSWORD"}
    _apply(monkeypatch, env)
    validate_config()


def test_local_auth_alone_satisfies_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    env = {
        k: v
        for k, v in _FULL_ENV.items()
        if k not in {"OKTA_OIDC_ISSUER", "OKTA_OIDC_CLIENT_ID", "OKTA_OIDC_CLIENT_SECRET"}
    }
    _apply(monkeypatch, env)
    validate_config()


def test_partial_okta_oidc_fails_when_no_local_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    env = {
        k: v
        for k, v in _FULL_ENV.items()
        if k not in {"AUTH_PASSWORD", "OKTA_OIDC_CLIENT_SECRET"}
    }
    _apply(monkeypatch, env)
    with pytest.raises(ConfigError, match="auth method"):
        validate_config()
