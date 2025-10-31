from __future__ import annotations

import os
from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from services import with_mysql_cursor
from bot import get_app_key

router = APIRouter(prefix="/activation", tags=["Activation"])


class ActivationResponse(BaseModel):
    """Activation lookup response payload."""

    username: str = Field(..., description="Local username associated with the key")
    plan_limit_bytes: int = Field(..., description="Configured traffic limit in bytes")
    used_bytes: int = Field(..., description="Used traffic in bytes")
    expire_at: datetime | None = Field(
        None, description="When the subscription expires (UTC)")
    disabled: bool = Field(..., description="Whether the user is currently disabled")
    subscription_url: str = Field(..., description="Subscription link for the user")
    key_expires_at: datetime | None = Field(
        None, description="When this activation key expires (UTC)")

    model_config = {
        "json_schema_extra": {
            "example": {
                "username": "alice",
                "plan_limit_bytes": 107374182400,
                "used_bytes": 53687091200,
                "expire_at": "2024-12-31T23:59:59",
                "disabled": False,
                "subscription_url": "https://example.com/sub/alice/abcd1234/links",
                "key_expires_at": "2024-12-01T00:00:00",
            }
        }
    }


@router.get("/{access_key}", response_model=ActivationResponse)
def get_activation(access_key: str) -> ActivationResponse:
    """Resolve a subscription activation key to user details."""

    with with_mysql_cursor() as cur:
        cur.execute(
            """
            SELECT
                luk.expires_at,
                lu.username,
                lu.plan_limit_bytes,
                lu.used_bytes,
                lu.expire_at,
                lu.disabled_pushed,
                lu.owner_id
            FROM local_user_keys AS luk
            JOIN local_users AS lu ON lu.id = luk.local_user_id
            WHERE luk.access_key=%s
            LIMIT 1
            """,
            (access_key,),
        )
        row = cur.fetchone()

    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Activation key not found",
        )

    expires_at = row.get("expires_at")
    if expires_at and expires_at <= datetime.utcnow():
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Activation key expired",
        )

    username = row["username"]
    owner_id = int(row["owner_id"])
    app_key = get_app_key(owner_id, username)
    public_base = os.getenv("PUBLIC_BASE_URL", "http://localhost:5000").rstrip("/")
    subscription_url = f"{public_base}/sub/{username}/{app_key}/links"

    return ActivationResponse(
        username=username,
        plan_limit_bytes=int(row.get("plan_limit_bytes") or 0),
        used_bytes=int(row.get("used_bytes") or 0),
        expire_at=row.get("expire_at"),
        disabled=bool(row.get("disabled_pushed")),
        subscription_url=subscription_url,
        key_expires_at=expires_at,
    )


__all__ = ("router",)
