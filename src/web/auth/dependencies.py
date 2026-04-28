"""JWT token issuance and verification."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt

from src.web.config import JWT_EXPIRY_HOURS, JWT_SECRET


def create_token(username: str) -> str:
    """Sign a session JWT for `username` valid for JWT_EXPIRY_HOURS hours."""
    return jwt.encode(
        {
            "sub": username,
            "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRY_HOURS),
        },
        JWT_SECRET,
        algorithm="HS256",
    )


def verify_token(token: str | None) -> str | None:
    """Return the `sub` claim if the token is valid, otherwise None."""
    if not token:
        return None
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        return payload.get("sub")
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None
