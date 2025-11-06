"""Agent self-service endpoints."""
from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.auth import Identity, require_agent
from services import get_agent_record, with_mysql_cursor

router = APIRouter(prefix="/agents", tags=["Agents"])


class AgentUsageSnapshot(BaseModel):
    """Lightweight view of a user's consumption for dashboard display."""

    username: str = Field(..., description="Username for the managed user")
    used_bytes: int = Field(0, description="Bytes consumed by the user")
    plan_limit_bytes: int = Field(0, description="Configured byte limit")
    expire_at: datetime | None = Field(
        None, description="Expiry timestamp for the managed user"
    )


class AgentMeResponse(BaseModel):
    """Detailed overview of the authenticated agent."""

    id: int
    telegram_user_id: int
    name: str
    plan_limit_bytes: int
    total_used_bytes: int
    expire_at: datetime | None
    active: bool
    user_limit: int
    max_user_bytes: int
    total_users: int
    created_at: datetime
    usage_snapshots: List[AgentUsageSnapshot]


@router.get("/me", response_model=AgentMeResponse)
def get_agent_me(identity: Identity = Depends(require_agent)) -> AgentMeResponse:
    """Return the authenticated agent's record and usage highlights."""

    if identity.agent_id is None:
        raise HTTPException(status_code=403, detail="Agent identity missing")

    agent = get_agent_record(identity.agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    with with_mysql_cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) AS total FROM local_users WHERE owner_id=%s",
            (identity.agent_id,),
        )
        count_row = cur.fetchone() or {}
        cur.execute(
            """
            SELECT username, used_bytes, plan_limit_bytes, expire_at
            FROM local_users
            WHERE owner_id=%s
            ORDER BY used_bytes DESC
            LIMIT 5
            """,
            (identity.agent_id,),
        )
        usage_rows = cur.fetchall()

    snapshots = [
        AgentUsageSnapshot(
            username=str(row.get("username")),
            used_bytes=int(row.get("used_bytes") or 0),
            plan_limit_bytes=int(row.get("plan_limit_bytes") or 0),
            expire_at=row.get("expire_at"),
        )
        for row in usage_rows or []
    ]

    return AgentMeResponse(
        id=int(agent.get("id")),
        telegram_user_id=int(agent.get("telegram_user_id")),
        name=str(agent.get("name")),
        plan_limit_bytes=int(agent.get("plan_limit_bytes") or 0),
        total_used_bytes=int(agent.get("total_used_bytes") or 0),
        expire_at=agent.get("expire_at"),
        active=bool(agent.get("active")),
        user_limit=int(agent.get("user_limit") or 0),
        max_user_bytes=int(agent.get("max_user_bytes") or 0),
        total_users=int(count_row.get("total") or 0),
        created_at=agent.get("created_at"),
        usage_snapshots=snapshots,
    )


__all__ = ["router"]
