"""Cookie-based authentication helpers for web UI endpoints."""
from __future__ import annotations

import os
import secrets
import logging
from dataclasses import dataclass

from fastapi import Cookie, Depends, HTTPException, Request, status
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from api.subscription_aggregator import canonical_owner_id, ordered_admin_ids

WEB_SESSION_COOKIE_NAME = "web_session"
WEB_SESSION_TTL_SECONDS = int(os.getenv("WEB_SESSION_TTL_SECONDS", "43200"))
_WEB_SESSION_FALLBACK_SECRET = secrets.token_urlsafe(32)
log = logging.getLogger("valhalla.web_auth")


def web_session_secure_cookie() -> bool:
    explicit = os.getenv("WEB_SESSION_COOKIE_SECURE")
    if explicit is not None:
        return explicit.strip().lower() in {"1", "true", "yes", "on"}

    app_env = (os.getenv("APP_ENV") or os.getenv("ENV") or "").strip().lower()
    return app_env in {"prod", "production", "staging"}


@dataclass
class WebIdentity:
    role: str
    username: str


def web_session_serializer() -> URLSafeTimedSerializer:
    explicit_secret = os.getenv("WEB_SESSION_SECRET") or os.getenv("BOT_TOKEN") or os.getenv("SECRET_KEY")
    if explicit_secret:
        secret = explicit_secret.strip()
    else:
        log.warning(
            "WEB_SESSION_SECRET/BOT_TOKEN/SECRET_KEY is missing; using an in-memory fallback secret for web sessions"
        )
        secret = _WEB_SESSION_FALLBACK_SECRET
    return URLSafeTimedSerializer(secret_key=secret, salt="web-session")


def owner_settings_id() -> int:
    admins = ordered_admin_ids()
    return canonical_owner_id(admins[0] if admins else 0)


def create_web_session_cookie(username: str, role: str = "web_admin") -> str:
    serializer = web_session_serializer()
    return serializer.dumps({"username": username, "role": role})


async def get_web_identity(
    request: Request,
    web_session: str | None = Cookie(default=None, alias=WEB_SESSION_COOKIE_NAME),
) -> WebIdentity:
    if not web_session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")

    serializer = web_session_serializer()
    try:
        payload = serializer.loads(web_session, max_age=WEB_SESSION_TTL_SECONDS)
    except SignatureExpired as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized") from exc
    except BadSignature as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized") from exc

    username = payload.get("username")
    role = payload.get("role")
    if not username or not role:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")

    identity = WebIdentity(username=username, role=role)
    request.state.web_identity = identity
    return identity


async def require_web_admin(identity: WebIdentity = Depends(get_web_identity)) -> WebIdentity:
    if identity.role != "web_admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    return identity


__all__ = [
    "WEB_SESSION_COOKIE_NAME",
    "WEB_SESSION_TTL_SECONDS",
    "WebIdentity",
    "create_web_session_cookie",
    "get_web_identity",
    "owner_settings_id",
    "require_web_admin",
    "web_session_secure_cookie",
]
