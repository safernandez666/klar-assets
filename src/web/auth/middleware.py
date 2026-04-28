"""HTTP middleware that enforces authentication on protected paths."""
from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse

from src.web.auth.dependencies import verify_token
from src.web.auth.login_page import login_page
from src.web.config import (
    AUTH_PASSWORD,
    PUBLIC_PATHS,
    SESSION_COOKIE,
    _OKTA_OIDC_ENABLED,
)


async def auth_middleware(request: Request, call_next: Any) -> Any:
    """Block unauthenticated traffic, except for public paths and static assets."""
    path = request.url.path

    # Skip auth only if no auth method is configured at all
    if not AUTH_PASSWORD and not _OKTA_OIDC_ENABLED:
        return await call_next(request)
    if path in PUBLIC_PATHS or path.startswith("/assets/"):
        return await call_next(request)

    token = request.cookies.get(SESSION_COOKIE)
    user = verify_token(token)

    if not user:
        # API calls get 401, page requests get redirect to login
        if path.startswith("/api/"):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
        return HTMLResponse(content=login_page(), status_code=200)

    return await call_next(request)
