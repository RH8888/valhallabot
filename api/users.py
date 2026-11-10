from __future__ import annotations

from datetime import datetime
import re
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api.subscription_aggregator import expand_owner_ids
from services import with_mysql_cursor
from bot import (
    _set_user_disabled_db,
    apply_user_updates,
    delete_local_user,
    upsert_local_user,
    list_service_panel_ids,
    list_user_links,
    get_api,
    remote_names_for_panel,
    sync_user_panels_async,
)
from api.auth import get_identity, Identity


router = APIRouter(prefix="/users", dependencies=[Depends(get_identity)])

USERNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]{2,19}$")
MIN_GUARDCORE_CREATE_LIMIT_BYTES = 20 * (1024**3)


class UserOut(BaseModel):
    username: str
    plan_limit_bytes: int
    used_bytes: int
    expire_at: datetime | None
    service_id: int | None = None
    disabled: bool = Field(..., description="Whether the user is disabled")
    manual_disabled: bool = Field(
        False, description="Whether the user was manually disabled"
    )
    access_key: str | None = Field(None, description="Subscription access key")
    key_expires_at: datetime | None = Field(
        None, description="Expiration timestamp for the access key"
    )


class UserCreate(BaseModel):
    username: str
    limit_bytes: int = Field(0, description="Byte limit for the user")
    duration_days: int = Field(0, description="Validity period in days")
    service_id: int | None = Field(None, description="Assigned service ID")
    template_username: str | None = Field(
        None, description="Template user to copy the service assignment from"
    )
    owner_id: int | None = Field(None, description="Target agent ID (admin only)")


class UserUpdate(BaseModel):
    limit_bytes: int | None = Field(
        None, description="Additional bytes to add to the remaining quota"
    )
    reset_used: bool = Field(False, description="Reset used traffic")
    renew_days: int | None = Field(None, description="Days to add to expiry")
    service_id: int | None = Field(None, description="Change service assignment")
    owner_id: int | None = Field(None, description="Target agent ID (admin only)")


class UserListResponse(BaseModel):
    total: int
    total_used_bytes: int = 0
    users: List[UserOut]


class PanelUsageOut(BaseModel):
    panel_id: int
    panel_name: str
    panel_type: str | None = None
    panel_url: str | None = None
    used_bytes: int


class OwnerPanelUsageResponse(BaseModel):
    total_used_bytes: int = 0
    panels: List[PanelUsageOut]


class UsageOut(BaseModel):
    username: str
    used_bytes: int
    plan_limit_bytes: int
    expire_at: datetime | None


class UsageRequest(BaseModel):
    owner_id: int | None = Field(None, description="Target agent ID (admin only)")


# ---- helpers -----------------------------------------------------------------

def _resolve_owner_id(identity: Identity, requested_owner_id: Any) -> int:
    """Resolve and enforce owner ID authorization for agents and admins.

    - If identity is an agent, they can only access their own agent_id. If they attempt
      to provide a different owner_id, the request is rejected with 403 Forbidden.
    - If identity is an admin/super_admin, they must supply an owner_id (either via body
      or query parameter). Missing owner_id results in 400 Bad Request.
    """
    from fastapi.params import Query, Depends, Param

    # Normalize default FastAPI param objects when functions are called directly in tests
    if isinstance(requested_owner_id, (Param, type(None))):
        clean_owner_id = None
    else:
        try:
            clean_owner_id = int(requested_owner_id)
        except (ValueError, TypeError):
            clean_owner_id = None

    if identity.role == "agent":
        if clean_owner_id is not None and clean_owner_id != int(identity.agent_id):
            raise HTTPException(
                status_code=403,
                detail="Agents cannot access or modify users of another owner",
            )
        return int(identity.agent_id)

    # Admin / super_admin
    if clean_owner_id is None:
        raise HTTPException(status_code=400, detail="owner_id required")
    return clean_owner_id


def _fetch_user(owner_id: int, username: str) -> dict | None:
    ids = expand_owner_ids(owner_id)
    placeholders = ",".join(["%s"] * len(ids))
    with with_mysql_cursor() as cur:
        cur.execute(
            f"""
            SELECT lu.username,
                   lu.plan_limit_bytes,
                   lu.used_bytes,
                   lu.expire_at,
                   lu.service_id,
                   lu.manual_disabled,
                   lu.disabled_pushed,
                   luk.access_key,
                   luk.expires_at AS key_expires_at
            FROM local_users lu
            LEFT JOIN local_user_keys luk ON luk.local_user_id = lu.id
            WHERE lu.owner_id IN ({placeholders}) AND lu.username=%s
            """,
            tuple(ids) + (username,),
        )
        return cur.fetchone()


def get_total_usage_by_panel(owner_id: int) -> int:
    ids = expand_owner_ids(owner_id)
    placeholders = ",".join(["%s"] * len(ids))
    with with_mysql_cursor() as cur:
        cur.execute(
            f"""
            SELECT COALESCE(SUM(total_used_bytes), 0) AS total_used_bytes
            FROM agent_panel_usage_totals
            WHERE agent_tg_id IN ({placeholders})
            """,
            tuple(ids),
        )
        row = cur.fetchone() or {}
    return int(row.get("total_used_bytes") or 0)


def get_usage_by_panel(owner_id: int) -> OwnerPanelUsageResponse:
    ids = expand_owner_ids(owner_id)
    placeholders = ",".join(["%s"] * len(ids))
    with with_mysql_cursor() as cur:
        cur.execute(
            f"""
            SELECT DISTINCT p.id, p.name, p.panel_type, p.panel_url
            FROM (
                SELECT sp.panel_id
                FROM agent_services ags
                JOIN service_panels sp ON sp.service_id = ags.service_id
                WHERE ags.agent_tg_id IN ({placeholders})

                UNION

                SELECT apt.panel_id
                FROM agent_panel_usage_totals apt
                WHERE apt.agent_tg_id IN ({placeholders})
            ) owned_panels
            JOIN panels p ON p.id = owned_panels.panel_id
            ORDER BY p.id ASC
            """,
            tuple(ids) + tuple(ids),
        )
        panel_rows = cur.fetchall()

        cur.execute(
            f"""
            SELECT panel_id, COALESCE(SUM(total_used_bytes), 0) AS used_bytes
            FROM agent_panel_usage_totals
            WHERE agent_tg_id IN ({placeholders})
            GROUP BY panel_id
            """,
            tuple(ids),
        )
        usage_rows = cur.fetchall()

    usage_map = {int(r["panel_id"]): int(r["used_bytes"] or 0) for r in usage_rows}
    panels = [
        PanelUsageOut(
            panel_id=int(r["id"]),
            panel_name=r["name"],
            panel_type=r.get("panel_type"),
            panel_url=r.get("panel_url"),
            used_bytes=usage_map.get(int(r["id"]), 0),
        )
        for r in panel_rows
    ]
    return OwnerPanelUsageResponse(
        total_used_bytes=sum(p.used_bytes for p in panels),
        panels=panels,
    )


def _agent_service_ids(agent_tg_id: int) -> set[int]:
    with with_mysql_cursor() as cur:
        cur.execute(
            "SELECT service_id FROM agent_services WHERE agent_tg_id=%s",
            (agent_tg_id,),
        )
        return {int(row["service_id"]) for row in cur.fetchall()}


def _assert_agent_service_allowed(identity: Identity, service_id: int | None) -> None:
    if identity.role != "agent" or service_id is None:
        return
    if service_id not in _agent_service_ids(identity.agent_id):
        raise HTTPException(status_code=403, detail="service not assigned to agent")


def _is_valid_local_username(username: str) -> bool:
    return bool(USERNAME_RE.fullmatch((username or "").strip()))


def _service_has_guardcore_panel(service_id: int) -> bool:
    with with_mysql_cursor() as cur:
        cur.execute(
            """
            SELECT 1
            FROM service_panels sp
            JOIN panels p ON p.id = sp.panel_id
            WHERE sp.service_id=%s AND LOWER(COALESCE(p.panel_type, ''))='guardcore'
            LIMIT 1
            """,
            (service_id,),
        )
        return bool(cur.fetchone())


def _list_users(
    owner_id: int,
    search: str | None,
    offset: int,
    limit: int,
    service_id: int | None,
) -> tuple[List[dict], int]:
    ids = expand_owner_ids(owner_id)
    placeholders = ",".join(["%s"] * len(ids))
    conds = [f"lu.owner_id IN ({placeholders})"]
    params: List[object] = list(ids)
    if search:
        conds.append("lu.username LIKE %s")
        params.append(f"%{search}%")
    if service_id is not None:
        conds.append("lu.service_id=%s")
        params.append(service_id)
    where_clause = " AND ".join(conds)
    with with_mysql_cursor() as cur:
        cur.execute(
            f"""
            SELECT lu.username,
                   lu.plan_limit_bytes,
                   lu.used_bytes,
                   lu.expire_at,
                   lu.service_id,
                   lu.manual_disabled,
                   lu.disabled_pushed,
                   luk.access_key,
                   luk.expires_at AS key_expires_at
            FROM local_users lu
            LEFT JOIN local_user_keys luk ON luk.local_user_id = lu.id
            WHERE {where_clause}
            ORDER BY lu.username ASC LIMIT %s OFFSET %s
            """,
            tuple(params) + (limit, offset),
        )
        rows = cur.fetchall()
        cur.execute(
            f"SELECT COUNT(*) AS c FROM local_users lu WHERE {where_clause}",
            tuple(params),
        )
        total = int(cur.fetchone()["c"])
    return rows, total


def _set_user_disabled(owner_id: int, username: str, disabled: bool) -> None:
    with with_mysql_cursor() as cur:
        should_enable = _set_user_disabled_db(cur, owner_id, username, disabled)
    if should_enable is None:
        raise HTTPException(status_code=404, detail="User not found")

    for row in list_user_links(owner_id, username):
        api = get_api(row.get("panel_type"), row.get("sanaei_api_version"))
        remotes = remote_names_for_panel(row, row["remote_username"])
        for rn in remotes:
            if disabled:
                api.disable_remote_user(row["panel_url"], row["access_token"], rn)
            elif should_enable:
                api.enable_remote_user(row["panel_url"], row["access_token"], rn)
            else:
                api.disable_remote_user(row["panel_url"], row["access_token"], rn)


# ---- endpoints ----------------------------------------------------------------

@router.post("/create", response_model=UserOut)
async def create_user(
    data: UserCreate,
    owner_id: int | None = Query(
        None, description="Target agent ID (admin only)"
    ),
    ownerid: int | None = Query(
        None, alias="ownerid", include_in_schema=False
    ),
    identity: Identity = Depends(get_identity),
):
    requested_owner = (
        data.owner_id
        if data.owner_id is not None
        else (owner_id if owner_id is not None else ownerid)
    )
    real_owner = _resolve_owner_id(identity, requested_owner)
    if not _is_valid_local_username(data.username):
        raise HTTPException(
            status_code=400,
            detail=(
                "invalid username: only English letters and numbers are allowed, "
                "it must start with an English letter, and length must be 3-20"
            ),
        )
    service_id = data.service_id
    if service_id is None and data.template_username:
        template_row = _fetch_user(real_owner, data.template_username)
        if not template_row:
            raise HTTPException(status_code=404, detail="template user not found")
        service_id = template_row.get("service_id")
    _assert_agent_service_allowed(identity, service_id)
    if (
        service_id is not None
        and _service_has_guardcore_panel(int(service_id))
        and int(data.limit_bytes or 0) < MIN_GUARDCORE_CREATE_LIMIT_BYTES
    ):
        raise HTTPException(
            status_code=400,
            detail="minimum limit is 20GB for services that include a GuardCore panel",
        )
    local_user_existed = _fetch_user(real_owner, data.username) is not None
    upsert_local_user(
        real_owner,
        data.username,
        data.limit_bytes,
        data.duration_days,
        service_id=service_id,
    )
    if service_id is not None:
        pids = list_service_panel_ids(service_id)
        try:
            sync_errors = await sync_user_panels_async(
                real_owner,
                data.username,
                pids,
                rollback_on_error=True,
            )
        except Exception:
            if not local_user_existed:
                delete_local_user(real_owner, data.username)
            raise
        if sync_errors:
            if not local_user_existed:
                delete_local_user(real_owner, data.username)
            raise HTTPException(
                status_code=502,
                detail="User creation failed on panels and was rolled back: " + "; ".join(sync_errors[:4]),
            )
    row = _fetch_user(real_owner, data.username)
    if not row:
        raise HTTPException(status_code=500, detail="user not found after create")
    return UserOut(
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


class UserListRequest(BaseModel):
    owner_id: int | None = Field(None, description="Target agent ID (admin only)")
    offset: int = Field(0, description="Pagination offset")
    limit: int = Field(25, description="Maximum number of users to return")
    search: str | None = Field(None, description="Search term")
    service_id: int | None = Field(None, description="Filter by service ID")


@router.post("", response_model=UserListResponse)
def list_users(
    data: UserListRequest,
    identity: Identity = Depends(get_identity),
):
    real_owner = _resolve_owner_id(identity, data.owner_id)
    _assert_agent_service_allowed(identity, data.service_id)
    rows, total = _list_users(
        real_owner,
        data.search,
        data.offset,
        data.limit,
        data.service_id,
    )
    users = [
        UserOut(
            username=r["username"],
            plan_limit_bytes=r.get("plan_limit_bytes", 0),
            used_bytes=r.get("used_bytes", 0),
            expire_at=r.get("expire_at"),
            service_id=r.get("service_id"),
            disabled=bool(r.get("manual_disabled") or r.get("disabled_pushed")),
            manual_disabled=bool(r.get("manual_disabled")),
            access_key=r.get("access_key"),
            key_expires_at=r.get("key_expires_at"),
        )
        for r in rows
    ]
    return UserListResponse(
        total=total,
        total_used_bytes=get_total_usage_by_panel(real_owner),
        users=users,
    )


@router.patch("/{username}", response_model=UserOut)
async def edit_user(
    username: str,
    data: UserUpdate,
    identity: Identity = Depends(get_identity),
):
    owner_id = _resolve_owner_id(identity, data.owner_id)
    _assert_agent_service_allowed(identity, data.service_id)
    found = await apply_user_updates(
        owner_id,
        username,
        limit_bytes=data.limit_bytes,
        reset_used_flag=data.reset_used,
        renew_days=data.renew_days,
        service_id=data.service_id,
    )
    if not found:
        raise HTTPException(status_code=404, detail="User not found")
    row = _fetch_user(owner_id, username)
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    return UserOut(
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


@router.delete("/{username}")
async def toggle_user(
    username: str,
    disable: bool = True,
    owner_id: int | None = None,
    identity: Identity = Depends(get_identity),
):
    real_owner = _resolve_owner_id(identity, owner_id)
    _set_user_disabled(real_owner, username, disable)
    row = _fetch_user(real_owner, username)
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    is_disabled = bool(row.get("manual_disabled") or row.get("disabled_pushed"))
    return {"status": "disabled" if is_disabled else "enabled"}


# POST is used because the endpoint requires a JSON body. GET requests with
# required bodies are non-standard and may not be supported by some clients.
@router.post("/{username}/usage", response_model=UsageOut)
def get_usage(
    username: str,
    data: UsageRequest,
    identity: Identity = Depends(get_identity),
):
    real_owner = _resolve_owner_id(identity, data.owner_id)
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
