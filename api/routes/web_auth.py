"""Web UI authentication routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel
from werkzeug.security import check_password_hash

from api.web_auth import (
    WEB_SESSION_COOKIE_NAME,
    WEB_SESSION_TTL_SECONDS,
    WebIdentity,
    create_web_session_cookie,
    owner_settings_id,
    require_web_admin,
)
from api.users import UserListResponse, UserOut, _list_users
from services.settings import get_setting

router = APIRouter(prefix="/web", tags=["Web Auth"])


class WebLoginRequest(BaseModel):
    username: str
    password: str


@router.post("/login")
async def web_login(payload: WebLoginRequest, response: Response) -> dict[str, str]:
    owner_id = owner_settings_id()
    configured_username = (get_setting(owner_id, "webui_username") or "").strip()
    configured_password_hash = (get_setting(owner_id, "webui_password_hash") or "").strip()

    if not configured_username or not configured_password_hash:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")

    username_ok = payload.username == configured_username
    password_ok = check_password_hash(configured_password_hash, payload.password)
    if not username_ok or not password_ok:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")

    session_value = create_web_session_cookie(username=configured_username)
    response.set_cookie(
        key=WEB_SESSION_COOKIE_NAME,
        value=session_value,
        max_age=WEB_SESSION_TTL_SECONDS,
        httponly=True,
        secure=True,
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
        secure=True,
        samesite="lax",
    )
    return {"status": "ok"}


@router.get("/me")
async def web_me(identity: WebIdentity = Depends(require_web_admin)) -> dict[str, str]:
    return {"username": identity.username, "role": identity.role}


@router.get("/users", response_model=UserListResponse)
async def web_list_users(
    offset: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=200),
    search: str | None = Query(None),
    owner_id: int | None = Query(
        None,
        description="Optional explicit owner scope; defaults to canonical super-admin owner",
    ),
    _identity: WebIdentity = Depends(require_web_admin),
) -> UserListResponse:
    scoped_owner_id = owner_settings_id() if owner_id is None else owner_id
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
