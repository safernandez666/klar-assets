"""FastAPI dependency providers for the web layer."""
from __future__ import annotations

from fastapi import Request

from src.storage.repository import DeviceRepository
from src.web.config import DB_PATH, SESSION_COOKIE


def get_repo() -> DeviceRepository:
    """Yield a fresh repository instance bound to the configured DB."""
    return DeviceRepository(DB_PATH)


def get_current_user(request: Request) -> str | None:
    """Decode the session cookie and return the username, or None if absent/invalid.

    Auth enforcement is the middleware's job — this dependency is purely for
    handlers that want to know *who* is acting (e.g. ack attribution).
    """
    from src.web.auth.dependencies import verify_token

    token = request.cookies.get(SESSION_COOKIE)
    return verify_token(token)
