"""Unit tests for the Okta collector — focused on the `expand=user` shape."""
from __future__ import annotations

from unittest.mock import patch

from src.collectors.okta import OktaCollector


def _device_fixture(
    device_id: str = "dev-1",
    display_name: str = "LAPTOP-001",
    serial: str = "SN-OKTA-001",
    users: list[dict] | None = None,
) -> dict:
    return {
        "id": device_id,
        "status": "ACTIVE",
        "displayName": display_name,
        "platform": "MACOS",
        "lastSeen": "2026-05-04T10:00:00.000Z",
        "registered": True,
        "profile": {
            "displayName": display_name,
            "platform": "MACOS",
            "serialNumber": serial,
        },
        "_embedded": {"users": users or []},
    }


def _user_assignment(login: str, first: str = "Test", last: str = "User") -> dict:
    return {
        "managementStatus": "NOT_MANAGED",
        "screenLockType": "BIOMETRIC",
        "user": {
            "id": f"00u-{login}",
            "status": "ACTIVE",
            "profile": {
                "login": login,
                "email": login,
                "firstName": first,
                "lastName": last,
                "displayName": f"{first} {last}",
            },
        },
    }


class TestOktaCollectExpandUser:
    def test_parses_inline_user_assignment(self) -> None:
        """A device with one inline user yields one RawDevice with that owner."""
        fixture = [
            _device_fixture(
                device_id="dev-alejandra",
                display_name="Alex's MacBook Pro",
                serial="L3073WL9G6",
                users=[_user_assignment("alejandra.ortiz@klar.mx", "Alejandra", "Ortiz")],
            )
        ]
        c = OktaCollector()
        with patch.object(c, "_fetch_devices", return_value=fixture):
            results = c.collect()

        assert len(results) == 1
        d = results[0]
        assert d.source == "okta"
        assert d.source_device_id == "dev-alejandra"
        assert d.serial_number == "L3073WL9G6"
        assert d.last_user == "alejandra.ortiz@klar.mx"
        assert d.raw_data["owner_email"] == "alejandra.ortiz@klar.mx"
        assert d.raw_data["owner_name"] == "Alejandra Ortiz"

    def test_device_without_users_yields_empty_owner(self) -> None:
        """A device with no inline users still produces one RawDevice (no owner)."""
        fixture = [_device_fixture(device_id="orphan", users=[])]
        c = OktaCollector()
        with patch.object(c, "_fetch_devices", return_value=fixture):
            results = c.collect()

        assert len(results) == 1
        assert results[0].last_user is None
        assert results[0].raw_data["okta_users"] == []

    def test_multiple_users_per_device_yield_multiple_records(self) -> None:
        """Shared devices (>1 inline user) emit one RawDevice per user."""
        fixture = [
            _device_fixture(
                device_id="shared-mac",
                serial="SN-SHARED",
                users=[
                    _user_assignment("user.one@klar.mx", "User", "One"),
                    _user_assignment("user.two@klar.mx", "User", "Two"),
                ],
            )
        ]
        c = OktaCollector()
        with patch.object(c, "_fetch_devices", return_value=fixture):
            results = c.collect()

        assert len(results) == 2
        emails = {r.last_user for r in results}
        assert emails == {"user.one@klar.mx", "user.two@klar.mx"}

    def test_falls_back_to_email_when_login_missing(self) -> None:
        """If the user profile lacks a `login`, fall back to `email`."""
        assignment = {
            "user": {"profile": {"email": "fallback@klar.mx", "firstName": "F", "lastName": "B"}}
        }
        fixture = [_device_fixture(device_id="fb", users=[assignment])]
        c = OktaCollector()
        with patch.object(c, "_fetch_devices", return_value=fixture):
            results = c.collect()

        assert results[0].last_user == "fallback@klar.mx"

    def test_no_per_device_users_endpoint_calls(self) -> None:
        """Regression: collect must not invoke any per-device user fetch.

        The legacy collector hit /api/v1/devices/{id}/users for every device,
        causing a 50 req/min Okta rate-limit storm. With expand=user the
        bulk /devices response must be sufficient.
        """
        fixture = [
            _device_fixture(
                device_id=f"dev-{i}",
                serial=f"SN-{i:03d}",
                users=[_user_assignment(f"user{i}@klar.mx")],
            )
            for i in range(20)
        ]
        c = OktaCollector()
        # `_request_with_retry` is the single chokepoint for HTTP calls.
        # If anyone reintroduces a per-device fetch, this assertion fires.
        with patch.object(c, "_fetch_devices", return_value=fixture), \
             patch.object(c, "_request_with_retry") as mock_http:
            results = c.collect()

        assert len(results) == 20
        assert mock_http.call_count == 0
