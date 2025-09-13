from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from bot import (
    expand_owner_ids,
    with_mysql_cursor,
    upsert_local_user,
    update_limit,
    reset_used,
    renew_user,
    list_user_links,
    get_api,
)
from api.auth import get_identity, Identity
from bot import set_local_user_service  # async function


router = APIRouter(prefix="/users", dependencies=[Depends(get_identity)])


class UserOut(BaseModel):
    username: str
    plan_limit_bytes: int
    used_bytes: int
    expire_at: datetime | None
    service_id: int | None = None
    disabled: bool = Field(..., description="Whether the user is disabled")


class UserCreate(BaseModel):
    username: str
    limit_bytes: int = Field(0, description="Byte limit for the user")
    duration_days: int = Field(0, description="Validity period in days")
    service_id: int | None = Field(None, description="Assigned service ID")
    owner_id: int | None = Field(None, description="Target agent ID (admin only)")


class UserUpdate(BaseModel):
    limit_bytes: int | None = Field(None, description="New byte limit")
    reset_used: bool = Field(False, description="Reset used traffic")
    renew_days: int | None = Field(None, description="Days to add to expiry")
    service_id: int | None = Field(None, description="Change service assignment")
    owner_id: int | None = Field(None, description="Target agent ID (admin only)")


class UserListResponse(BaseModel):
    total: int
    users: List[UserOut]


class UsageOut(BaseModel):
    username: str
    used_bytes: int
    plan_limit_bytes: int
    expire_at: datetime | None


# ---- helpers -----------------------------------------------------------------

def _fetch_user(owner_id: int, username: str) -> dict | None:
    ids = expand_owner_ids(owner_id)
    placeholders = ",".join(["%s"] * len(ids))
    with with_mysql_cursor() as cur:
        cur.execute(
            f"SELECT username,plan_limit_bytes,used_bytes,expire_at,service_id,disabled_pushed "
            f"FROM local_users WHERE owner_id IN ({placeholders}) AND username=%s",
            tuple(ids) + (username,),
        )
        return cur.fetchone()


def _list_users(
    owner_id: int,
    search: str | None,
    offset: int,
    limit: int,
    service_id: int | None,
) -> tuple[List[dict], int]:
    ids = expand_owner_ids(owner_id)
    placeholders = ",".join(["%s"] * len(ids))
    conds = [f"owner_id IN ({placeholders})"]
    params: List[object] = list(ids)
    if search:
        conds.append("username LIKE %s")
        params.append(f"%{search}%")
    if service_id is not None:
        conds.append("service_id=%s")
        params.append(service_id)
    where_clause = " AND ".join(conds)
    with with_mysql_cursor() as cur:
        cur.execute(
            f"SELECT username,plan_limit_bytes,used_bytes,expire_at,service_id,disabled_pushed "
            f"FROM local_users WHERE {where_clause} ORDER BY username ASC LIMIT %s OFFSET %s",
            tuple(params) + (limit, offset),
        )
        rows = cur.fetchall()
        cur.execute(
            f"SELECT COUNT(*) AS c FROM local_users WHERE {where_clause}",
            tuple(params),
        )
        total = int(cur.fetchone()["c"])
    return rows, total


def _set_user_disabled(owner_id: int, username: str, disabled: bool) -> None:
    for row in list_user_links(owner_id, username):
        api = get_api(row.get("panel_type"))
        remotes = (
            row["remote_username"].split(",")
            if row.get("panel_type") == "sanaei"
            else [row["remote_username"]]
        )
        for rn in remotes:
            if disabled:
                api.disable_remote_user(row["panel_url"], row["access_token"], rn)
            else:
                api.enable_remote_user(row["panel_url"], row["access_token"], rn)
    ids = expand_owner_ids(owner_id)
    placeholders = ",".join(["%s"] * len(ids))
    sql = (
        f"UPDATE local_users SET disabled_pushed=%s, disabled_pushed_at="
        f"{'UTC_TIMESTAMP()' if disabled else 'NULL'} "
        f"WHERE owner_id IN ({placeholders}) AND username=%s"
    )
    params = [1 if disabled else 0, *ids, username]
    with with_mysql_cursor() as cur:
        cur.execute(sql, params)


# ---- endpoints ----------------------------------------------------------------

@router.post("", response_model=UserOut)
async def create_user(data: UserCreate, identity: Identity = Depends(get_identity)):
    owner_id = identity.agent_id if identity.role == "agent" else data.owner_id
    if owner_id is None:
        raise HTTPException(status_code=400, detail="owner_id required")
    upsert_local_user(owner_id, data.username, data.limit_bytes, data.duration_days)
    if data.service_id is not None:
        await set_local_user_service(owner_id, data.username, data.service_id)
    row = _fetch_user(owner_id, data.username)
    if not row:
        raise HTTPException(status_code=500, detail="user not found after create")
    return UserOut(
        username=row["username"],
        plan_limit_bytes=row.get("plan_limit_bytes", 0),
        used_bytes=row.get("used_bytes", 0),
        expire_at=row.get("expire_at"),
        service_id=row.get("service_id"),
        disabled=bool(row.get("disabled_pushed")),
    )


@router.get("", response_model=UserListResponse)
def list_users(
    search: str | None = Query(None, description="Search term"),
    offset: int = 0,
    limit: int = 25,
    service_id: int | None = None,
    owner_id: int | None = None,
    identity: Identity = Depends(get_identity),
):
    real_owner = identity.agent_id if identity.role == "agent" else owner_id
    if real_owner is None:
        raise HTTPException(status_code=400, detail="owner_id required")
    rows, total = _list_users(real_owner, search, offset, limit, service_id)
    users = [
        UserOut(
            username=r["username"],
            plan_limit_bytes=r.get("plan_limit_bytes", 0),
            used_bytes=r.get("used_bytes", 0),
            expire_at=r.get("expire_at"),
            service_id=r.get("service_id"),
            disabled=bool(r.get("disabled_pushed")),
        )
        for r in rows
    ]
    return UserListResponse(total=total, users=users)


@router.patch("/{username}", response_model=UserOut)
async def edit_user(
    username: str,
    data: UserUpdate,
    identity: Identity = Depends(get_identity),
):
    owner_id = identity.agent_id if identity.role == "agent" else data.owner_id
    if owner_id is None:
        raise HTTPException(status_code=400, detail="owner_id required")
    if data.limit_bytes is not None:
        update_limit(owner_id, username, data.limit_bytes)
    if data.reset_used:
        reset_used(owner_id, username)
    if data.renew_days is not None:
        renew_user(owner_id, username, data.renew_days)
    if data.service_id is not None:
        await set_local_user_service(owner_id, username, data.service_id)
    row = _fetch_user(owner_id, username)
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    return UserOut(
        username=row["username"],
        plan_limit_bytes=row.get("plan_limit_bytes", 0),
        used_bytes=row.get("used_bytes", 0),
        expire_at=row.get("expire_at"),
        service_id=row.get("service_id"),
        disabled=bool(row.get("disabled_pushed")),
    )


@router.delete("/{username}")
async def toggle_user(
    username: str,
    disable: bool = True,
    owner_id: int | None = None,
    identity: Identity = Depends(get_identity),
):
    real_owner = identity.agent_id if identity.role == "agent" else owner_id
    if real_owner is None:
        raise HTTPException(status_code=400, detail="owner_id required")
    _set_user_disabled(real_owner, username, disable)
    return {"status": "disabled" if disable else "enabled"}


@router.get("/{username}/usage", response_model=UsageOut)
def get_usage(
    username: str,
    owner_id: int | None = None,
    identity: Identity = Depends(get_identity),
):
    real_owner = identity.agent_id if identity.role == "agent" else owner_id
    if real_owner is None:
        raise HTTPException(status_code=400, detail="owner_id required")
    row = _fetch_user(real_owner, username)
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    return UsageOut(
        username=row["username"],
        used_bytes=row.get("used_bytes", 0),
        plan_limit_bytes=row.get("plan_limit_bytes", 0),
        expire_at=row.get("expire_at"),
    )


__all__ = ("router",)
