"""
Authentication middleware — Simple single-password protection.
No user management. One password set via ACCESS_PASSWORD env var.
Session stored in a signed cookie (itsdangerous).
"""
import os
import secrets
from functools import lru_cache
from typing import Optional

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from itsdangerous import BadSignature, SignatureExpired, TimestampSigner
from starlette.middleware.base import BaseHTTPMiddleware

SECRET_KEY = os.getenv("SECRET_KEY", secrets.token_hex(32))
ACCESS_PASSWORD = os.getenv("ACCESS_PASSWORD", "osint_changeme")
COOKIE_NAME = "osint_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 7  # 7 days

signer = TimestampSigner(SECRET_KEY)

# Public paths that bypass auth
PUBLIC_PATHS = {
    "/auth/login",
    "/auth/logout",
    "/health",
}

# Static file patterns that bypass auth
PUBLIC_PREFIXES = ("/static/",)


def sign_session() -> str:
    """Create a signed session token."""
    return signer.sign("authenticated").decode()


def verify_session(token: str) -> bool:
    """Verify the session token validity."""
    try:
        signer.unsign(token, max_age=SESSION_MAX_AGE)
        return True
    except (BadSignature, SignatureExpired):
        return False


class AuthMiddleware(BaseHTTPMiddleware):
    """
    Middleware that protects all routes except public paths.
    Authentication is done via a signed cookie after password submission.
    """

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Allow public paths
        if path in PUBLIC_PATHS:
            return await call_next(request)

        # Allow static file prefixes
        if any(path.startswith(prefix) for prefix in PUBLIC_PREFIXES):
            return await call_next(request)

        # Allow WebSocket upgrades (auth checked separately in WS handler)
        if request.headers.get("upgrade", "").lower() == "websocket":
            # Check cookie on WS too
            token = request.cookies.get(COOKIE_NAME)
            if token and verify_session(token):
                return await call_next(request)
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)

        # Check session cookie
        token = request.cookies.get(COOKIE_NAME)
        if token and verify_session(token):
            return await call_next(request)

        # Not authenticated — return 401 for API calls, redirect hint for others
        accept = request.headers.get("accept", "")
        if "application/json" in accept or path.startswith("/api/"):
            return JSONResponse(
                {"detail": "Not authenticated", "redirect": "/auth/login"},
                status_code=401,
            )

        # For browser navigation, return a redirect-like 401
        return JSONResponse(
            {"detail": "Not authenticated", "redirect": "/auth/login"},
            status_code=401,
        )
