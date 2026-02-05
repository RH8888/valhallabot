from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, ConfigDict

from services import with_mysql_cursor
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
    usage_multiplier: float = Field(1.0, description="Usage multiplier for quota deductions")
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
            "usage_multiplier": 1.0,
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
    usage_multiplier: float | None = None
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
                telegram_user_id, panel_url, name, panel_type, usage_multiplier,
                admin_username, access_token, template_username, sub_url
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                _owner_id(),
                data.panel_url,
                data.name,
                data.panel_type,
                data.usage_multiplier,
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


class PanelUsageOut(BaseModel):
    panel_id: int
    panel_name: str
    panel_type: str
    panel_url: str
    used_bytes: int


class AgentPanelUsageOut(BaseModel):
    agent_id: int
    total_used_bytes: int
    panels: List[PanelUsageOut]


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


@router.get(
    "/agents/{agent_id}/usage-by-panel",
    response_model=AgentPanelUsageOut,
    summary="Get agent usage grouped by panel",
    dependencies=[Depends(require_super_admin)],
)
def get_agent_usage_by_panel(agent_id: int):
    with with_mysql_cursor() as cur:
        cur.execute(
            "SELECT telegram_user_id FROM agents WHERE telegram_user_id=%s LIMIT 1",
            (agent_id,),
        )
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="Agent not found")

        cur.execute(
            """
            SELECT DISTINCT p.id, p.name, p.panel_type, p.panel_url
            FROM agent_services ags
            JOIN service_panels sp ON sp.service_id = ags.service_id
            JOIN panels p ON p.id = sp.panel_id
            WHERE ags.agent_tg_id = %s
            ORDER BY p.id ASC
            """,
            (agent_id,),
        )
        panel_rows = cur.fetchall()

        cur.execute(
            """
            SELECT
                lup.panel_id,
                COALESCE(SUM(ROUND(lup.last_used_traffic * COALESCE(p.usage_multiplier, 1.0))), 0) AS used_bytes
            FROM local_user_panel_links lup
            JOIN local_users lu
              ON lu.owner_id = lup.owner_id
             AND lu.username = lup.local_username
            JOIN agent_services ags
              ON ags.agent_tg_id = lu.owner_id
             AND ags.service_id = lu.service_id
            JOIN service_panels sp
              ON sp.service_id = lu.service_id
             AND sp.panel_id = lup.panel_id
            JOIN panels p ON p.id = lup.panel_id
            WHERE lu.owner_id = %s
            GROUP BY lup.panel_id
            """,
            (agent_id,),
        )
        usage_rows = cur.fetchall()

    usage_map = {int(r["panel_id"]): int(r["used_bytes"] or 0) for r in usage_rows}
    panels = [
        PanelUsageOut(
            panel_id=int(r["id"]),
            panel_name=r["name"],
            panel_type=r["panel_type"],
            panel_url=r["panel_url"],
            used_bytes=usage_map.get(int(r["id"]), 0),
        )
        for r in panel_rows
    ]
    return AgentPanelUsageOut(
        agent_id=agent_id,
        total_used_bytes=sum(p.used_bytes for p in panels),
        panels=panels,
    )


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
    name: str = Field(..., description="Service name")


class ServiceCreate(ServiceBase):
    model_config = ConfigDict(json_schema_extra={"example": {"name": "Premium"}})


class ServiceUpdate(BaseModel):
    name: str | None = None
    model_config = ConfigDict(json_schema_extra={"example": {"name": "Updated"}})


class ServiceOut(ServiceBase):
    id: int
    created_at: datetime


@router.get("/services", response_model=List[ServiceOut], summary="List services")
def list_services():
    with with_mysql_cursor() as cur:
        cur.execute("SELECT * FROM services")
        rows = cur.fetchall()
    return [ServiceOut(**row) for row in rows]


@router.post("/services", response_model=ServiceOut, summary="Create a service")
def create_service(data: ServiceCreate):
    with with_mysql_cursor() as cur:
        cur.execute(
            "INSERT INTO services (name) VALUES (%s)",
            (data.name,),
        )
        service_id = cur.lastrowid
        cur.execute("SELECT * FROM services WHERE id=%s", (service_id,))
        row = cur.fetchone()
    return ServiceOut(**row)


@router.get("/services/{service_id}", response_model=ServiceOut, summary="Get a service")
def get_service(service_id: int):
    with with_mysql_cursor() as cur:
        cur.execute("SELECT * FROM services WHERE id=%s", (service_id,))
        row = cur.fetchone()
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
        cur.execute(f"UPDATE services SET {sets} WHERE id=%s", tuple(params))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Service not found")
        cur.execute("SELECT * FROM services WHERE id=%s", (service_id,))
        row = cur.fetchone()
    return ServiceOut(**row)


@router.delete("/services/{service_id}", summary="Delete a service")
def delete_service(service_id: int):
    with with_mysql_cursor() as cur:
        cur.execute("DELETE FROM services WHERE id=%s", (service_id,))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Service not found")
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
