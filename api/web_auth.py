"""Cookie-based authentication helpers for web UI endpoints."""
from __future__ import annotations

import os
import logging
import hashlib
from dataclasses import dataclass

from fastapi import Cookie, Depends, HTTPException, Request, status
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from api.subscription_aggregator import canonical_owner_id, ordered_admin_ids

WEB_SESSION_COOKIE_NAME = "web_session"
WEB_SESSION_TTL_SECONDS = int(os.getenv("WEB_SESSION_TTL_SECONDS", "43200"))


def _fallback_session_secret() -> str:
    """Build a deterministic fallback secret when no explicit secret is configured.

    This keeps cookies valid across multiple workers in the same deployment.
    """

    seed = "|".join(
        [
            (os.getenv("MYSQL_HOST") or "").strip(),
            (os.getenv("MYSQL_DATABASE") or "").strip(),
            (os.getenv("APP_ENV") or os.getenv("ENV") or "").strip(),
            (os.getenv("FLASK_PORT") or "").strip(),
        ]
    )
    if not seed.replace("|", ""):
        return "valhalla-web-session-fallback-secret"
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


_WEB_SESSION_FALLBACK_SECRET = _fallback_session_secret()
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
    owner_id: int | None = None


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


def create_web_session_cookie(username: str, role: str = "web_admin", owner_id: int | None = None) -> str:
    serializer = web_session_serializer()
    payload = {"username": username, "role": role}
    if owner_id is not None:
        payload["owner_id"] = int(owner_id)
    return serializer.dumps(payload)


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
    owner_id = payload.get("owner_id")
    if owner_id is not None:
        try:
            owner_id = int(owner_id)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized") from exc

    identity = WebIdentity(username=username, role=role, owner_id=owner_id)
    request.state.web_identity = identity
    return identity


async def require_web_admin(identity: WebIdentity = Depends(get_web_identity)) -> WebIdentity:
    if identity.role != "web_admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    return identity


async def require_web_user(identity: WebIdentity = Depends(get_web_identity)) -> WebIdentity:
    if identity.role not in {"web_admin", "web_agent"}:
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
    "require_web_user",
    "web_session_secure_cookie",
]
