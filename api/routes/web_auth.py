"""Web UI authentication routes."""
from __future__ import annotations

import logging
import os
import time
from threading import Lock

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel
from werkzeug.security import check_password_hash

from api.web_auth import (
    WEB_SESSION_COOKIE_NAME,
    WEB_SESSION_TTL_SECONDS,
    WebIdentity,
    create_web_session_cookie,
    owner_settings_id,
    require_web_user,
    web_session_secure_cookie,
)
from api.users import UserListResponse, UserOut, _list_users
from services import with_mysql_cursor
from services.settings import get_setting

router = APIRouter(prefix="/web", tags=["Web Auth"])
log = logging.getLogger("valhalla.web_auth")

WEB_LOGIN_RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("WEB_LOGIN_RATE_LIMIT_WINDOW_SECONDS", "300"))
WEB_LOGIN_RATE_LIMIT_MAX_ATTEMPTS = int(os.getenv("WEB_LOGIN_RATE_LIMIT_MAX_ATTEMPTS", "5"))

_LOGIN_ATTEMPTS: dict[str, list[float]] = {}
_LOGIN_ATTEMPTS_LOCK = Lock()


def _get_setting_exact(owner_id: int, key: str) -> str:
    with with_mysql_cursor() as cur:
        cur.execute(
            "SELECT `value` FROM settings WHERE owner_id=%s AND `key`=%s LIMIT 1",
            (owner_id, key),
        )
        row = cur.fetchone()
    return ((row or {}).get("value") or "").strip()


def _login_attempt_key(client_id: str, username: str) -> str:
    return f"{client_id}:{username.lower().strip()}"


def _is_login_rate_limited(client_id: str, username: str) -> bool:
    now = time.time()
    key = _login_attempt_key(client_id, username)
    with _LOGIN_ATTEMPTS_LOCK:
        recent_attempts = [
            ts for ts in _LOGIN_ATTEMPTS.get(key, []) if now - ts <= WEB_LOGIN_RATE_LIMIT_WINDOW_SECONDS
        ]
        _LOGIN_ATTEMPTS[key] = recent_attempts
        return len(recent_attempts) >= WEB_LOGIN_RATE_LIMIT_MAX_ATTEMPTS


def _record_failed_login(client_id: str, username: str) -> int:
    now = time.time()
    key = _login_attempt_key(client_id, username)
    with _LOGIN_ATTEMPTS_LOCK:
        recent_attempts = [
            ts for ts in _LOGIN_ATTEMPTS.get(key, []) if now - ts <= WEB_LOGIN_RATE_LIMIT_WINDOW_SECONDS
        ]
        recent_attempts.append(now)
        _LOGIN_ATTEMPTS[key] = recent_attempts
        return len(recent_attempts)


def _clear_login_attempts(client_id: str, username: str) -> None:
    key = _login_attempt_key(client_id, username)
    with _LOGIN_ATTEMPTS_LOCK:
        _LOGIN_ATTEMPTS.pop(key, None)


class WebLoginRequest(BaseModel):
    username: str
    password: str


@router.post("/login")
async def web_login(payload: WebLoginRequest, request: Request, response: Response) -> dict[str, str]:
    owner_id = owner_settings_id()
    configured_username = (
        get_setting(owner_id, "webui_admin_username")
        or get_setting(owner_id, "webui_username")
        or ""
    ).strip()
    configured_password_hash = (
        get_setting(owner_id, "webui_admin_password_hash")
        or get_setting(owner_id, "webui_password_hash")
        or ""
    ).strip()
    normalized_username = (payload.username or "").strip()
    normalized_password = (payload.password or "").strip()
    forwarded_for = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    client_id = forwarded_for or (request.client.host if request.client else "unknown")

    if _is_login_rate_limited(client_id, normalized_username):
        log.warning(
            "web login blocked by rate limit client_id=%s username=%s window=%ss max_attempts=%s",
            client_id,
            normalized_username,
            WEB_LOGIN_RATE_LIMIT_WINDOW_SECONDS,
            WEB_LOGIN_RATE_LIMIT_MAX_ATTEMPTS,
        )
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many login attempts")

    admin_username_ok = normalized_username == configured_username
    admin_password_ok = bool(configured_password_hash) and check_password_hash(
        configured_password_hash, normalized_password
    )

    if admin_username_ok and admin_password_ok:
        _clear_login_attempts(client_id, normalized_username)
        session_value = create_web_session_cookie(username=configured_username, role="web_admin")
        response.set_cookie(
            key=WEB_SESSION_COOKIE_NAME,
            value=session_value,
            max_age=WEB_SESSION_TTL_SECONDS,
            httponly=True,
            secure=web_session_secure_cookie(),
            samesite="lax",
            path="/",
        )
        return {"status": "ok"}

    agent_match = None
    with with_mysql_cursor() as cur:
        cur.execute(
            """
            SELECT telegram_user_id
            FROM agents
            WHERE active=1
              AND COALESCE(NULLIF(TRIM(%s), ''), '') != ''
              AND %s = TRIM(COALESCE((
                  SELECT s.`value`
                  FROM settings s
                  WHERE s.owner_id=agents.telegram_user_id
                    AND s.`key`='webui_agent_username'
                  LIMIT 1
              ), ''))
            LIMIT 1
            """,
            (normalized_username, normalized_username),
        )
        agent_match = cur.fetchone()

    if not agent_match:
        attempts = _record_failed_login(client_id, normalized_username)
        log.warning(
            "web login failed client_id=%s username=%s failed_attempts=%s",
            client_id,
            normalized_username,
            attempts,
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")

    agent_owner_id = int(agent_match["telegram_user_id"])
    agent_password_hash = _get_setting_exact(agent_owner_id, "webui_agent_password_hash")
    if not agent_password_hash or not check_password_hash(agent_password_hash, normalized_password):
        attempts = _record_failed_login(client_id, normalized_username)
        log.warning(
            "web login failed client_id=%s username=%s failed_attempts=%s",
            client_id,
            normalized_username,
            attempts,
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")

    _clear_login_attempts(client_id, normalized_username)
    session_value = create_web_session_cookie(
        username=normalized_username,
        role="web_agent",
        owner_id=agent_owner_id,
    )
    response.set_cookie(
        key=WEB_SESSION_COOKIE_NAME,
        value=session_value,
        max_age=WEB_SESSION_TTL_SECONDS,
        httponly=True,
        secure=web_session_secure_cookie(),
        samesite="lax",
        path="/",
    )
    return {"status": "ok"}


@router.post("/logout")
async def web_logout(response: Response) -> dict[str, str]:
    response.delete_cookie(
        key=WEB_SESSION_COOKIE_NAME,
        path="/",
        httponly=True,
        secure=web_session_secure_cookie(),
        samesite="lax",
    )
    return {"status": "ok"}


@router.get("/me")
async def web_me(identity: WebIdentity = Depends(require_web_user)) -> dict[str, str | int | None]:
    return {"username": identity.username, "role": identity.role, "owner_id": identity.owner_id}


@router.get("/users", response_model=UserListResponse)
async def web_list_users(
    offset: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=200),
    search: str | None = Query(None),
    owner_id: int | None = Query(
        None,
        description="Optional explicit owner scope; defaults to canonical super-admin owner",
    ),
    identity: WebIdentity = Depends(require_web_user),
) -> UserListResponse:
    if identity.role == "web_agent":
        scoped_owner_id = identity.owner_id
    else:
        scoped_owner_id = owner_settings_id() if owner_id is None else owner_id

    if scoped_owner_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
    rows, total = _list_users(
        owner_id=scoped_owner_id,
        search=search,
        offset=offset,
        limit=limit,
        service_id=None,
    )
    users = [
        UserOut(
            username=row["username"],
            plan_limit_bytes=row.get("plan_limit_bytes", 0),
            used_bytes=row.get("used_bytes", 0),
            expire_at=row.get("expire_at"),
            service_id=row.get("service_id"),
            disabled=bool(row.get("manual_disabled") or row.get("disabled_pushed")),
            manual_disabled=bool(row.get("manual_disabled")),
            access_key=row.get("access_key"),
            key_expires_at=row.get("key_expires_at"),
        )
        for row in rows
    ]
    return UserListResponse(total=total, users=users)


__all__ = ["router"]
