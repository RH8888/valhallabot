from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, ConfigDict, field_validator

from services import with_mysql_cursor, mysql_errors, errorcode
from services import get_admin_token as service_get_admin_token
from services import rotate_admin_token as service_rotate_admin_token
from api.subscription_aggregator import admin_ids, canonical_owner_id
from api.auth import require_admin, require_super_admin


def _owner_id() -> int:
    admins = admin_ids()
    return canonical_owner_id(next(iter(admins)) if admins else 0)


def _owner_ids() -> list[int]:
    admins = admin_ids()
    return list(admins)

router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])


@router.get("/token", summary="Get admin token", dependencies=[Depends(require_super_admin)])
def get_admin_token():
    token = service_get_admin_token()
    if not token:
        raise HTTPException(status_code=404, detail="Token not set")
    return {"api_token": token}


@router.post("/token", summary="Rotate admin token", dependencies=[Depends(require_super_admin)])
def rotate_admin_token():
    token = service_rotate_admin_token()
    return {"api_token": token}


# ---------------------- Panels ----------------------
class PanelBase(BaseModel):
    panel_url: str = Field(..., description="Base URL of the panel")
    name: str = Field(..., description="Display name for the panel")
    panel_type: str = Field("marzneshin", description="Panel type")
    admin_username: str = Field(..., description="Administrator username")
    access_token: str = Field(..., description="Access token for API calls")
    template_username: str | None = Field(None, description="Template user on the panel")
    sub_url: str | None = Field(None, description="Subscription URL for name filtering")


class PanelCreate(PanelBase):
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "panel_url": "https://panel.example.com",
            "name": "Main Panel",
            "panel_type": "marzneshin",
            "admin_username": "admin",
            "access_token": "token",
            "template_username": "template",
            "sub_url": "https://panel.example.com/sub",
        }
    })


class PanelUpdate(BaseModel):
    panel_url: str | None = None
    name: str | None = None
    panel_type: str | None = None
    admin_username: str | None = None
    access_token: str | None = None
    template_username: str | None = None
    sub_url: str | None = None
    model_config = ConfigDict(json_schema_extra={"example": {"name": "Updated Panel"}})


class PanelOut(PanelBase):
    id: int
    created_at: datetime


@router.get("/panels", response_model=List[PanelOut], summary="List panels")
def list_panels():
    ids = _owner_ids()
    with with_mysql_cursor() as cur:
        if ids:
            placeholders = ",".join(["%s"] * len(ids))
            cur.execute(
                f"SELECT * FROM panels WHERE telegram_user_id IN ({placeholders})",
                tuple(ids),
            )
        else:
            cur.execute("SELECT * FROM panels")
        rows = cur.fetchall()
    return [PanelOut(**row) for row in rows]


@router.post("/panels", response_model=PanelOut, summary="Create a panel")
def create_panel(data: PanelCreate):
    with with_mysql_cursor() as cur:
        cur.execute(
            """
            INSERT INTO panels (
                telegram_user_id, panel_url, name, panel_type,
                admin_username, access_token, template_username, sub_url
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                _owner_id(),
                data.panel_url,
                data.name,
                data.panel_type,
                data.admin_username,
                data.access_token,
                data.template_username,
                data.sub_url,
            ),
        )
        panel_id = cur.lastrowid
        cur.execute("SELECT * FROM panels WHERE id=%s", (panel_id,))
        row = cur.fetchone()
    return PanelOut(**row)


@router.get("/panels/{panel_id}", response_model=PanelOut, summary="Get a panel")
def get_panel(panel_id: int):
    ids = _owner_ids()
    if ids:
        placeholders = ",".join(["%s"] * len(ids))
        sql = f"SELECT * FROM panels WHERE id=%s AND telegram_user_id IN ({placeholders})"
        params = (panel_id, *ids)
    else:
        sql = "SELECT * FROM panels WHERE id=%s"
        params = (panel_id,)
    with with_mysql_cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Panel not found")
    return PanelOut(**row)


@router.put("/panels/{panel_id}", response_model=PanelOut, summary="Update a panel")
def update_panel(panel_id: int, data: PanelUpdate):
    fields = data.model_dump(exclude_unset=True)
    if not fields:
        return get_panel(panel_id)
    ids = _owner_ids()
    sets = ", ".join(f"{k}=%s" for k in fields)
    if ids:
        placeholders = ",".join(["%s"] * len(ids))
        sql = f"UPDATE panels SET {sets} WHERE id=%s AND telegram_user_id IN ({placeholders})"
        params = list(fields.values()) + [panel_id] + ids
    else:
        sql = f"UPDATE panels SET {sets} WHERE id=%s"
        params = list(fields.values()) + [panel_id]
    with with_mysql_cursor() as cur:
        cur.execute(sql, tuple(params))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Panel not found")
        cur.execute("SELECT * FROM panels WHERE id=%s", (panel_id,))
        row = cur.fetchone()
    return PanelOut(**row)


@router.delete("/panels/{panel_id}", summary="Delete a panel")
def delete_panel(panel_id: int):
    ids = _owner_ids()
    if ids:
        placeholders = ",".join(["%s"] * len(ids))
        sql = f"DELETE FROM panels WHERE id=%s AND telegram_user_id IN ({placeholders})"
        params = (panel_id, *ids)
    else:
        sql = "DELETE FROM panels WHERE id=%s"
        params = (panel_id,)
    with with_mysql_cursor() as cur:
        cur.execute(sql, params)
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Panel not found")
    return {"status": "deleted"}


# ---------------------- Agents ----------------------
class AgentBase(BaseModel):
    telegram_user_id: int = Field(..., description="Agent Telegram user ID")
    name: str = Field(..., description="Display name for the agent")
    plan_limit_bytes: int = Field(0, description="Total byte limit for the agent")
    expire_at: datetime | None = Field(None, description="Expiry timestamp")
    active: bool = Field(True, description="Whether the agent is active")
    user_limit: int = Field(0, description="Maximum number of users allowed")
    max_user_bytes: int = Field(0, description="Per-user byte limit")


class AgentCreate(AgentBase):
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "telegram_user_id": 123456,
            "name": "Agent Smith",
            "plan_limit_bytes": 1000000000,
            "expire_at": "2025-01-01T00:00:00",
            "active": True,
            "user_limit": 100,
            "max_user_bytes": 100000000,
        }
    })


class AgentUpdate(BaseModel):
    name: str | None = None
    plan_limit_bytes: int | None = None
    expire_at: datetime | None = None
    active: bool | None = None
    user_limit: int | None = None
    max_user_bytes: int | None = None
    model_config = ConfigDict(json_schema_extra={"example": {"name": "New Name", "active": False}})


class AgentOut(AgentBase):
    id: int
    created_at: datetime
    total_used_bytes: int = Field(0, description="Total bytes consumed by the agent")


@router.get("/agents", response_model=List[AgentOut], summary="List agents")
def list_agents():
    with with_mysql_cursor() as cur:
        cur.execute("SELECT * FROM agents")
        rows = cur.fetchall()
    return [AgentOut(**row) for row in rows]


@router.post("/agents", response_model=AgentOut, summary="Create an agent")
def create_agent(data: AgentCreate):
    with with_mysql_cursor() as cur:
        cur.execute(
            """
            INSERT INTO agents (
                telegram_user_id, name, plan_limit_bytes, expire_at,
                active, user_limit, max_user_bytes
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                data.telegram_user_id,
                data.name,
                data.plan_limit_bytes,
                data.expire_at,
                int(data.active),
                data.user_limit,
                data.max_user_bytes,
            ),
        )
        agent_id = cur.lastrowid
        cur.execute("SELECT * FROM agents WHERE id=%s", (agent_id,))
        row = cur.fetchone()
    return AgentOut(**row)


@router.get("/agents/{agent_id}", response_model=AgentOut, summary="Get an agent")
def get_agent(agent_id: int):
    with with_mysql_cursor() as cur:
        cur.execute("SELECT * FROM agents WHERE id=%s", (agent_id,))
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Agent not found")
    return AgentOut(**row)


@router.put("/agents/{agent_id}", response_model=AgentOut, summary="Update an agent")
def update_agent(agent_id: int, data: AgentUpdate):
    fields = data.model_dump(exclude_unset=True)
    if not fields:
        return get_agent(agent_id)
    if "active" in fields and fields["active"] is not None:
        fields["active"] = int(fields["active"])
    sets = ", ".join(f"{k}=%s" for k in fields)
    params = list(fields.values()) + [agent_id]
    with with_mysql_cursor() as cur:
        cur.execute(f"UPDATE agents SET {sets} WHERE id=%s", tuple(params))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Agent not found")
        cur.execute("SELECT * FROM agents WHERE id=%s", (agent_id,))
        row = cur.fetchone()
    return AgentOut(**row)


@router.delete("/agents/{agent_id}", summary="Delete an agent")
def delete_agent(agent_id: int):
    with with_mysql_cursor() as cur:
        cur.execute("DELETE FROM agents WHERE id=%s", (agent_id,))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Agent not found")
    return {"status": "deleted"}


# ---------------------- Services ----------------------
class ServiceBase(BaseModel):
    name: str = Field(
        ..., description="Service name", min_length=1, max_length=128
    )

    @field_validator("name")
    @classmethod
    def _trim_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Service name cannot be empty.")
        return value


class ServiceCreate(ServiceBase):
    model_config = ConfigDict(json_schema_extra={"example": {"name": "Premium"}})


class ServiceUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=128)
    model_config = ConfigDict(json_schema_extra={"example": {"name": "Updated"}})

    @field_validator("name")
    @classmethod
    def _trim_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("Service name cannot be empty.")
        return trimmed


class ServiceOut(ServiceBase):
    id: int
    created_at: datetime
    panel_count: int = Field(0, description="Number of panels assigned")
    user_count: int = Field(0, description="Number of users assigned")


class ServicePanelsUpdate(BaseModel):
    panel_ids: list[int] = Field(
        default_factory=list, description="IDs of panels assigned to the service"
    )


class ServicePanelsResponse(BaseModel):
    service: ServiceOut
    panels: List[PanelOut]


_SERVICE_SUMMARY_SELECT = """
    SELECT
        s.id,
        s.name,
        s.created_at,
        COALESCE(sp.panel_count, 0) AS panel_count,
        COALESCE(lu.user_count, 0) AS user_count
    FROM services s
    LEFT JOIN (
        SELECT service_id, COUNT(*) AS panel_count
        FROM service_panels
        GROUP BY service_id
    ) sp ON sp.service_id = s.id
    LEFT JOIN (
        SELECT service_id, COUNT(*) AS user_count
        FROM local_users
        WHERE service_id IS NOT NULL
        GROUP BY service_id
    ) lu ON lu.service_id = s.id
"""


def _fetch_service(cur, service_id: int):
    cur.execute(f"{_SERVICE_SUMMARY_SELECT} WHERE s.id=%s", (service_id,))
    return cur.fetchone()


def _fetch_service_panels(cur, service_id: int) -> list[PanelOut]:
    cur.execute(
        """
        SELECT p.*
        FROM service_panels sp
        JOIN panels p ON p.id = sp.panel_id
        WHERE sp.service_id=%s
        ORDER BY p.name
        """,
        (service_id,),
    )
    rows = cur.fetchall()
    return [PanelOut(**row) for row in rows]


@router.get("/services", response_model=List[ServiceOut], summary="List services")
def list_services():
    with with_mysql_cursor() as cur:
        cur.execute(f"{_SERVICE_SUMMARY_SELECT} ORDER BY s.created_at DESC")
        rows = cur.fetchall()
    return [ServiceOut(**row) for row in rows]


@router.post("/services", response_model=ServiceOut, summary="Create a service")
def create_service(data: ServiceCreate):
    with with_mysql_cursor() as cur:
        try:
            cur.execute(
                "INSERT INTO services (name) VALUES (%s)",
                (data.name,),
            )
        except mysql_errors.IntegrityError as exc:  # type: ignore[attr-defined]
            if exc.errno == errorcode.ER_DUP_ENTRY:
                raise HTTPException(
                    status_code=400, detail="A service with this name already exists."
                ) from exc
            raise
        service_id = cur.lastrowid
        row = _fetch_service(cur, service_id)
    return ServiceOut(**row)


@router.get("/services/{service_id}", response_model=ServiceOut, summary="Get a service")
def get_service(service_id: int):
    with with_mysql_cursor() as cur:
        row = _fetch_service(cur, service_id)
    if not row:
        raise HTTPException(status_code=404, detail="Service not found")
    return ServiceOut(**row)


@router.put("/services/{service_id}", response_model=ServiceOut, summary="Update a service")
def update_service(service_id: int, data: ServiceUpdate):
    fields = data.model_dump(exclude_unset=True)
    if not fields:
        return get_service(service_id)
    sets = ", ".join(f"{k}=%s" for k in fields)
    params = list(fields.values()) + [service_id]
    with with_mysql_cursor() as cur:
        try:
            cur.execute(f"UPDATE services SET {sets} WHERE id=%s", tuple(params))
        except mysql_errors.IntegrityError as exc:  # type: ignore[attr-defined]
            if exc.errno == errorcode.ER_DUP_ENTRY:
                raise HTTPException(
                    status_code=400, detail="A service with this name already exists."
                ) from exc
            raise
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Service not found")
        row = _fetch_service(cur, service_id)
    return ServiceOut(**row)


@router.get(
    "/services/{service_id}/panels",
    response_model=ServicePanelsResponse,
    summary="List panels assigned to a service",
)
def get_service_panels(service_id: int):
    with with_mysql_cursor() as cur:
        service_row = _fetch_service(cur, service_id)
        if not service_row:
            raise HTTPException(status_code=404, detail="Service not found")
        panels = _fetch_service_panels(cur, service_id)
    return ServicePanelsResponse(service=ServiceOut(**service_row), panels=panels)


@router.put(
    "/services/{service_id}/panels",
    response_model=ServicePanelsResponse,
    summary="Update service panel assignments",
)
def update_service_panels(service_id: int, data: ServicePanelsUpdate):
    panel_ids = {int(pid) for pid in data.panel_ids}
    with with_mysql_cursor() as cur:
        service_row = _fetch_service(cur, service_id)
        if not service_row:
            raise HTTPException(status_code=404, detail="Service not found")

        if panel_ids:
            placeholders = ",".join(["%s"] * len(panel_ids))
            owner_ids = _owner_ids()
            if owner_ids:
                owner_placeholders = ",".join(["%s"] * len(owner_ids))
                cur.execute(
                    f"""
                    SELECT id FROM panels
                    WHERE id IN ({placeholders})
                    AND telegram_user_id IN ({owner_placeholders})
                    """,
                    tuple(panel_ids) + tuple(owner_ids),
                )
            else:
                cur.execute(
                    f"SELECT id FROM panels WHERE id IN ({placeholders})",
                    tuple(panel_ids),
                )
            found_ids = {row["id"] for row in cur.fetchall()}
            missing = panel_ids - found_ids
            if missing:
                raise HTTPException(
                    status_code=400,
                    detail="One or more panels could not be found or are not accessible.",
                )

        cur.execute("DELETE FROM service_panels WHERE service_id=%s", (service_id,))
        if panel_ids:
            cur.executemany(
                "INSERT INTO service_panels (service_id, panel_id) VALUES (%s, %s)",
                [(service_id, pid) for pid in sorted(panel_ids)],
            )

        updated_service = _fetch_service(cur, service_id)
        panels = _fetch_service_panels(cur, service_id)

    return ServicePanelsResponse(service=ServiceOut(**updated_service), panels=panels)


@router.delete("/services/{service_id}", summary="Delete a service")
def delete_service(service_id: int):
    with with_mysql_cursor() as cur:
        cur.execute("SELECT id FROM services WHERE id=%s", (service_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="Service not found")

        cur.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM local_users WHERE service_id=%s) AS user_count,
                (SELECT COUNT(*) FROM agents WHERE service_id=%s) AS agent_count
            """,
            (service_id, service_id),
        )
        counts = cur.fetchone() or {"user_count": 0, "agent_count": 0}
        user_count = counts.get("user_count", 0)
        agent_count = counts.get("agent_count", 0)
        if user_count or agent_count:
            parts = []
            if user_count:
                parts.append(f"{user_count} user{'s' if user_count != 1 else ''}")
            if agent_count:
                parts.append(f"{agent_count} agent{'s' if agent_count != 1 else ''}")
            joined = " and ".join(parts)
            raise HTTPException(
                status_code=400,
                detail=f"Cannot delete service while {joined} are assigned.",
            )

        cur.execute("DELETE FROM services WHERE id=%s", (service_id,))
    return {"status": "deleted"}


# ---------------------- Settings ----------------------
class SettingOut(BaseModel):
    key: str
    value: str


class SettingValue(BaseModel):
    value: str = Field(..., description="Setting value")
    model_config = ConfigDict(json_schema_extra={"example": {"value": "hello"}})


@router.get("/settings", response_model=List[SettingOut], summary="List settings")
def list_settings():
    ids = _owner_ids()
    placeholders = ",".join(["%s"] * len(ids))
    with with_mysql_cursor() as cur:
        cur.execute(
            f"SELECT `key`, `value` FROM settings WHERE owner_id IN ({placeholders})",
            tuple(ids),
        )
        rows = cur.fetchall()
    return [SettingOut(**row) for row in rows]


@router.get("/settings/{key}", response_model=SettingOut, summary="Get a setting")
def get_setting_api(key: str):
    ids = _owner_ids()
    placeholders = ",".join(["%s"] * len(ids))
    params = (key, *ids)
    with with_mysql_cursor() as cur:
        cur.execute(
            f"SELECT `value` FROM settings WHERE `key`=%s AND owner_id IN ({placeholders})",
            params,
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Setting not found")
    return SettingOut(key=key, value=row["value"])


@router.put("/settings/{key}", response_model=SettingOut, summary="Create or update a setting")
def set_setting(key: str, data: SettingValue):
    with with_mysql_cursor() as cur:
        cur.execute(
            "REPLACE INTO settings (owner_id, `key`, `value`) VALUES (%s, %s, %s)",
            (_owner_id(), key, data.value),
        )
    return SettingOut(key=key, value=data.value)


@router.delete("/settings/{key}", summary="Delete a setting")
def delete_setting(key: str):
    with with_mysql_cursor() as cur:
        cur.execute(
            "DELETE FROM settings WHERE owner_id=%s AND `key`=%s",
            (_owner_id(), key),
        )
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Setting not found")
    return {"status": "deleted"}


__all__ = ("router",)
