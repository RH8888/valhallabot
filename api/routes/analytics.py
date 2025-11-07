"""Analytics endpoints for agent and admin dashboards."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api.auth import Identity, require_admin, require_agent
from services import with_mysql_cursor

router = APIRouter(prefix="/analytics", tags=["Analytics"])


class AgentUsageSummary(BaseModel):
    """Aggregated usage metrics for an agent."""

    total_users: int = Field(..., description="Total managed users for the agent")
    active_users: int = Field(..., description="Managed users that are not disabled")
    disabled_users: int = Field(..., description="Managed users that are currently disabled")
    total_used_bytes: int = Field(..., description="Sum of consumed quota across users")
    plan_limit_bytes: int = Field(..., description="Quota limit configured for the agent")
    usage_percent: float = Field(..., description="Percentage of the plan consumed")


class TrendPoint(BaseModel):
    """Usage trend bucketed by day."""

    date: datetime = Field(..., description="Day for the aggregated usage sample")
    total_used_bytes: int = Field(..., description="Usage snapshot for the period")


class BreakdownItem(BaseModel):
    """Breakdown of usage by attached service."""

    label: str = Field(..., description="Service name or placeholder when unassigned")
    user_count: int = Field(..., description="Number of users mapped to the service")
    used_bytes: int = Field(..., description="Total usage attributed to the service")


class TopUserItem(BaseModel):
    """Top consumers ordered by quota usage."""

    username: str
    used_bytes: int
    plan_limit_bytes: int
    expire_at: datetime | None = None


class ActivityItem(BaseModel):
    """Recent user activity extracted from local user updates."""

    username: str
    detail: str
    updated_at: datetime


class AgentAnalyticsResponse(BaseModel):
    """Composite response for agent dashboard analytics."""

    summary: AgentUsageSummary
    usage_trend: List[TrendPoint]
    service_breakdown: List[BreakdownItem]
    top_users: List[TopUserItem]
    recent_activity: List[ActivityItem]


@router.get("/agent/summary", response_model=AgentAnalyticsResponse)
def get_agent_analytics(
    identity: Identity = Depends(require_agent),
    trend_days: int = Query(
        7,
        ge=1,
        le=90,
        description="How many days of usage trend data to return",
    ),
    top_limit: int = Query(
        5,
        ge=1,
        le=50,
        description="Maximum number of top users to include",
    ),
    activity_limit: int = Query(
        10,
        ge=1,
        le=100,
        description="Maximum number of recent activity entries",
    ),
) -> AgentAnalyticsResponse:
    """Return analytics for the authenticated agent."""

    if identity.agent_id is None:
        raise HTTPException(status_code=403, detail="Agent identity missing")

    owner_id = identity.agent_id
    trend_cutoff = datetime.utcnow() - timedelta(days=trend_days - 1)

    with with_mysql_cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*) AS total_users,
                   SUM(CASE WHEN disabled_pushed = 0 THEN 1 ELSE 0 END) AS active_users,
                   SUM(CASE WHEN disabled_pushed = 1 THEN 1 ELSE 0 END) AS disabled_users,
                   COALESCE(SUM(used_bytes), 0) AS total_used_bytes
            FROM local_users
            WHERE owner_id = %s
            """,
            (owner_id,),
        )
        summary_row = cur.fetchone() or {}

        cur.execute(
            """
            SELECT DATE(updated_at) AS bucket_date,
                   SUM(used_bytes) AS total_used_bytes
            FROM local_users
            WHERE owner_id = %s AND updated_at >= %s
            GROUP BY bucket_date
            ORDER BY bucket_date ASC
            """,
            (owner_id, trend_cutoff),
        )
        trend_rows = cur.fetchall() or []

        cur.execute(
            """
            SELECT COALESCE(s.name, 'Unassigned') AS service_name,
                   COUNT(*) AS user_count,
                   COALESCE(SUM(lu.used_bytes), 0) AS used_bytes
            FROM local_users lu
            LEFT JOIN services s ON s.id = lu.service_id
            WHERE lu.owner_id = %s
            GROUP BY service_name
            ORDER BY user_count DESC, service_name ASC
            """,
            (owner_id,),
        )
        breakdown_rows = cur.fetchall() or []

        cur.execute(
            """
            SELECT username, used_bytes, plan_limit_bytes, expire_at
            FROM local_users
            WHERE owner_id = %s
            ORDER BY used_bytes DESC
            LIMIT %s
            """,
            (owner_id, top_limit),
        )
        top_user_rows = cur.fetchall() or []

        cur.execute(
            """
            SELECT username, used_bytes, plan_limit_bytes, updated_at
            FROM local_users
            WHERE owner_id = %s
            ORDER BY updated_at DESC
            LIMIT %s
            """,
            (owner_id, activity_limit),
        )
        activity_rows = cur.fetchall() or []

        cur.execute(
            """
            SELECT plan_limit_bytes
            FROM agents
            WHERE telegram_user_id = %s
            LIMIT 1
            """,
            (owner_id,),
        )
        agent_row = cur.fetchone() or {"plan_limit_bytes": 0}

    total_users = int(summary_row.get("total_users") or 0)
    active_users = int(summary_row.get("active_users") or 0)
    disabled_users = int(summary_row.get("disabled_users") or 0)
    total_used_bytes = int(summary_row.get("total_used_bytes") or 0)
    plan_limit_bytes = int(agent_row.get("plan_limit_bytes") or 0)
    usage_percent = (
        (total_used_bytes / plan_limit_bytes) * 100.0
        if plan_limit_bytes > 0
        else 0.0
    )

    summary = AgentUsageSummary(
        total_users=total_users,
        active_users=active_users,
        disabled_users=disabled_users,
        total_used_bytes=total_used_bytes,
        plan_limit_bytes=plan_limit_bytes,
        usage_percent=round(usage_percent, 2),
    )

    trend = [
        TrendPoint(
            date=datetime.combine(row["bucket_date"], datetime.min.time()),
            total_used_bytes=int(row.get("total_used_bytes") or 0),
        )
        for row in trend_rows
    ]

    breakdown = [
        BreakdownItem(
            label=str(row.get("service_name")),
            user_count=int(row.get("user_count") or 0),
            used_bytes=int(row.get("used_bytes") or 0),
        )
        for row in breakdown_rows
    ]

    top_users = [
        TopUserItem(
            username=str(row.get("username")),
            used_bytes=int(row.get("used_bytes") or 0),
            plan_limit_bytes=int(row.get("plan_limit_bytes") or 0),
            expire_at=row.get("expire_at"),
        )
        for row in top_user_rows
    ]

    recent_activity = [
        ActivityItem(
            username=str(row.get("username")),
            detail=f"Usage snapshot: {int(row.get('used_bytes') or 0):,} bytes",
            updated_at=row.get("updated_at"),
        )
        for row in activity_rows
    ]

    return AgentAnalyticsResponse(
        summary=summary,
        usage_trend=trend,
        service_breakdown=breakdown,
        top_users=top_users,
        recent_activity=recent_activity,
    )


class AdminAgentSummary(BaseModel):
    """Aggregated analytics for a managed agent."""

    telegram_user_id: int
    name: str
    total_users: int
    active_users: int
    total_used_bytes: int
    plan_limit_bytes: int
    quota_utilisation: float
    active: bool
    user_limit: int
    max_user_bytes: int
    created_at: datetime


class AdminAgentPage(BaseModel):
    """Paginated list of agent analytics for administrators."""

    total: int
    items: List[AdminAgentSummary]


@router.get("/admin/agents", response_model=AdminAgentPage)
def list_agent_analytics(
    identity: Identity = Depends(require_admin),
    limit: int = Query(25, ge=1, le=100, description="Maximum records to return"),
    offset: int = Query(0, ge=0, description="Records to skip for pagination"),
    search: str | None = Query(
        None,
        description="Optional case-insensitive search on agent name",
    ),
) -> AdminAgentPage:
    """Return aggregated analytics for agents (admin only)."""

    with with_mysql_cursor() as cur:
        filters = []
        params: list[object] = []
        if search:
            filters.append("a.name LIKE %s")
            params.append(f"%{search}%")
        where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""

        cur.execute(
            f"SELECT COUNT(*) AS total FROM agents a {where_clause}",
            tuple(params),
        )
        total_row = cur.fetchone() or {"total": 0}
        total = int(total_row.get("total") or 0)

        cur.execute(
            f"""
            SELECT a.telegram_user_id,
                   a.name,
                   a.plan_limit_bytes,
                   a.total_used_bytes,
                   a.active,
                   a.user_limit,
                   a.max_user_bytes,
                   a.created_at,
                   COALESCE(lu_metrics.total_users, 0) AS total_users,
                   COALESCE(lu_metrics.active_users, 0) AS active_users
            FROM agents a
            LEFT JOIN (
                SELECT owner_id,
                       COUNT(*) AS total_users,
                       SUM(CASE WHEN disabled_pushed = 0 THEN 1 ELSE 0 END) AS active_users
                FROM local_users
                GROUP BY owner_id
            ) AS lu_metrics ON lu_metrics.owner_id = a.telegram_user_id
            {where_clause}
            ORDER BY a.created_at DESC
            LIMIT %s OFFSET %s
            """,
            tuple(params + [limit, offset]),
        )
        rows = cur.fetchall() or []

    items = []
    for row in rows:
        plan_limit_bytes = int(row.get("plan_limit_bytes") or 0)
        total_used_bytes = int(row.get("total_used_bytes") or 0)
        utilisation = (
            (total_used_bytes / plan_limit_bytes) * 100.0
            if plan_limit_bytes > 0
            else 0.0
        )
        items.append(
            AdminAgentSummary(
                telegram_user_id=int(row.get("telegram_user_id") or 0),
                name=str(row.get("name")),
                total_users=int(row.get("total_users") or 0),
                active_users=int(row.get("active_users") or 0),
                total_used_bytes=total_used_bytes,
                plan_limit_bytes=plan_limit_bytes,
                quota_utilisation=round(utilisation, 2),
                active=bool(row.get("active")),
                user_limit=int(row.get("user_limit") or 0),
                max_user_bytes=int(row.get("max_user_bytes") or 0),
                created_at=row.get("created_at"),
            )
        )

    return AdminAgentPage(total=total, items=items)


__all__ = ["router"]
