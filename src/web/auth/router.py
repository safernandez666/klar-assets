"""Authentication endpoints — local credentials and Okta OIDC."""
from __future__ import annotations

import html as html_mod
import secrets
import urllib.parse
from typing import Any

import httpx
import jwt
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel

from src.web.auth.dependencies import create_token, verify_token
from src.web.auth.login_page import login_page
from src.web.config import (
    APP_URL,
    AUTH_PASSWORD,
    AUTH_USERNAME,
    JWT_EXPIRY_HOURS,
    OKTA_ALLOWED_DOMAINS,
    OKTA_OIDC_CLIENT_ID,
    OKTA_OIDC_CLIENT_SECRET,
    OKTA_OIDC_ISSUER,
    SESSION_COOKIE,
    _IS_HTTPS,
    _OKTA_OIDC_ENABLED,
)

router = APIRouter()


class LoginRequest(BaseModel):
    username: str
    password: str


@router.get("/auth/login")
async def auth_login_page(request: Request) -> Any:
    """Serve login page. If already authenticated, redirect to dashboard."""
    token = request.cookies.get(SESSION_COOKIE)
    if verify_token(token):
        return RedirectResponse("/")
    return HTMLResponse(content=login_page(), status_code=200)


@router.post("/auth/login")
async def auth_login(body: LoginRequest) -> Any:
    """Authenticate via local username/password and set the session cookie."""
    if not AUTH_PASSWORD:
        return JSONResponse({"error": "Auth not configured"}, status_code=400)

    user_ok = secrets.compare_digest(body.username, AUTH_USERNAME)
    pass_ok = secrets.compare_digest(body.password, AUTH_PASSWORD)

    if not (user_ok and pass_ok):
        return JSONResponse({"error": "Invalid credentials"}, status_code=401)

    token = create_token(body.username)
    response = JSONResponse({"ok": True, "user": body.username})
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        httponly=True,
        secure=_IS_HTTPS,
        samesite="lax",
        max_age=JWT_EXPIRY_HOURS * 3600,
        path="/",
    )
    return response


@router.get("/auth/me")
async def auth_me(request: Request) -> Any:
    """Return the username from the current session, or 'unknown'."""
    token = request.cookies.get(SESSION_COOKIE)
    user = verify_token(token)
    return JSONResponse({"user": user or "unknown"})


@router.get("/auth/logout")
async def auth_logout() -> Any:
    """Clear the session cookie and redirect to the login page."""
    response = RedirectResponse("/auth/login")
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@router.get("/auth/okta")
async def auth_okta_redirect() -> Any:
    """Redirect user to Okta for authentication."""
    if not _OKTA_OIDC_ENABLED:
        return JSONResponse({"error": "Okta OIDC not configured"}, status_code=400)

    # FIX-1: Generate state and store in cookie for CSRF protection
    state = secrets.token_hex(16)
    params = urllib.parse.urlencode({
        "client_id": OKTA_OIDC_CLIENT_ID,
        "response_type": "code",
        "scope": "openid email profile",
        "redirect_uri": f"{APP_URL}/auth/okta/callback",
        "state": state,
    })
    response = RedirectResponse(f"{OKTA_OIDC_ISSUER}/v1/authorize?{params}")
    response.set_cookie(
        key="okta_state", value=state, httponly=True, samesite="lax",
        secure=_IS_HTTPS, max_age=300, path="/",
    )
    return response


@router.get("/auth/okta/callback")
async def auth_okta_callback(code: str = "", error: str = "", state: str = "", request: Request = None) -> Any:
    """Handle Okta OIDC callback — exchange code for token."""
    # FIX-3: Escape all user-controlled values before rendering
    if error:
        safe_error = html_mod.escape(error)
        return HTMLResponse(f"<h3>Login failed: {safe_error}</h3><a href='/'>Try again</a>")
    if not code or not _OKTA_OIDC_ENABLED:
        return HTMLResponse("<h3>Invalid callback</h3><a href='/'>Try again</a>")

    # FIX-1: Validate state parameter against cookie
    expected_state = request.cookies.get("okta_state") if request else None
    if not expected_state or not secrets.compare_digest(state, expected_state):
        return HTMLResponse("<h3>Invalid state — possible CSRF attack</h3><a href='/'>Try again</a>")

    try:
        async with httpx.AsyncClient() as client:
            token_resp = await client.post(
                f"{OKTA_OIDC_ISSUER}/v1/token",
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": f"{APP_URL}/auth/okta/callback",
                    "client_id": OKTA_OIDC_CLIENT_ID,
                    "client_secret": OKTA_OIDC_CLIENT_SECRET,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            if token_resp.status_code != 200:
                return HTMLResponse("<h3>Token exchange failed</h3><a href='/'>Try again</a>")
            tokens = token_resp.json()

            # FIX-2: Validate ID token claims
            id_token_raw = tokens.get("id_token")
            if id_token_raw:
                try:
                    # Decode without verification first to check claims
                    # (signature is implicitly trusted since we got this token
                    # directly from Okta over TLS in a server-to-server call)
                    claims = jwt.decode(id_token_raw, options={"verify_signature": False})
                    if claims.get("iss") != OKTA_OIDC_ISSUER:
                        return HTMLResponse("<h3>Invalid token issuer</h3><a href='/'>Try again</a>")
                    if claims.get("aud") != OKTA_OIDC_CLIENT_ID:
                        return HTMLResponse("<h3>Invalid token audience</h3><a href='/'>Try again</a>")
                except jwt.InvalidTokenError:
                    return HTMLResponse("<h3>Invalid ID token</h3><a href='/'>Try again</a>")

            userinfo_resp = await client.get(
                f"{OKTA_OIDC_ISSUER}/v1/userinfo",
                headers={"Authorization": f"Bearer {tokens['access_token']}"},
            )
            if userinfo_resp.status_code != 200:
                return HTMLResponse("<h3>Failed to get user info</h3><a href='/'>Try again</a>")
            userinfo = userinfo_resp.json()
    except Exception:
        # FIX-3: Don't leak exception details
        return HTMLResponse("<h3>Authentication failed</h3><a href='/'>Try again</a>")

    email = userinfo.get("email") or userinfo.get("preferred_username") or ""

    # FIX-5: Validate user email domain
    if OKTA_ALLOWED_DOMAINS:
        domains = [d.strip().lower() for d in OKTA_ALLOWED_DOMAINS.split(",") if d.strip()]
        email_domain = email.split("@")[-1].lower() if "@" in email else ""
        if domains and email_domain not in domains:
            return HTMLResponse("<h3>Access denied — your domain is not authorized</h3><a href='/'>Back</a>")

    if not email:
        return HTMLResponse("<h3>No email in Okta profile</h3><a href='/'>Try again</a>")

    token = create_token(email)

    response = RedirectResponse("/")
    response.set_cookie(
        key=SESSION_COOKIE, value=token, httponly=True,
        secure=_IS_HTTPS, samesite="lax", max_age=JWT_EXPIRY_HOURS * 3600, path="/",
    )
    response.delete_cookie("okta_state", path="/")
    return response
