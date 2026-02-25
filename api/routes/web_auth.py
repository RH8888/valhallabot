"""Web UI authentication routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
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


__all__ = ["router"]
