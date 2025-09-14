from datetime import datetime
from typing import List
import secrets

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, ConfigDict

from bot import with_mysql_cursor, admin_ids, expand_owner_ids, canonical_owner_id
from api.auth import require_admin, require_super_admin


def _owner_id() -> int:
    admins = admin_ids()
    return canonical_owner_id(next(iter(admins)) if admins else 0)


def _owner_ids() -> list[int]:
    return expand_owner_ids(_owner_id())

router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])


@router.get("/token", summary="Get admin token", dependencies=[Depends(require_super_admin)])
def get_admin_token():
    with with_mysql_cursor() as cur:
        cur.execute("SELECT api_token FROM admins WHERE is_super=1 LIMIT 1")
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Token not set")
    return {"api_token": row["api_token"]}


@router.post("/token", summary="Rotate admin token", dependencies=[Depends(require_super_admin)])
def rotate_admin_token():
    token = secrets.token_hex(32)
    with with_mysql_cursor() as cur:
        cur.execute("UPDATE admins SET api_token=%s WHERE is_super=1", (token,))
        if cur.rowcount == 0:
            cur.execute("INSERT INTO admins (api_token, is_super) VALUES (%s, 1)", (token,))
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
    placeholders = ",".join(["%s"] * len(ids))
    with with_mysql_cursor() as cur:
        cur.execute(
            f"SELECT * FROM panels WHERE telegram_user_id IN ({placeholders})",
            tuple(ids),
        )
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
    placeholders = ",".join(["%s"] * len(ids))
    params = (panel_id, *ids)
    with with_mysql_cursor() as cur:
        cur.execute(
            f"SELECT * FROM panels WHERE id=%s AND telegram_user_id IN ({placeholders})",
            params,
        )
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
    placeholders = ",".join(["%s"] * len(ids))
    sets = ", ".join(f"{k}=%s" for k in fields)
    params = list(fields.values()) + [panel_id] + ids
    with with_mysql_cursor() as cur:
        cur.execute(
            f"UPDATE panels SET {sets} WHERE id=%s AND telegram_user_id IN ({placeholders})",
            tuple(params),
        )
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Panel not found")
        cur.execute("SELECT * FROM panels WHERE id=%s", (panel_id,))
        row = cur.fetchone()
    return PanelOut(**row)


@router.delete("/panels/{panel_id}", summary="Delete a panel")
def delete_panel(panel_id: int):
    ids = _owner_ids()
    placeholders = ",".join(["%s"] * len(ids))
    params = (panel_id, *ids)
    with with_mysql_cursor() as cur:
        cur.execute(
            f"DELETE FROM panels WHERE id=%s AND telegram_user_id IN ({placeholders})",
            params,
        )
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
