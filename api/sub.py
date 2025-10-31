from __future__ import annotations

from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.auth import get_identity, Identity
from api.subscription_aggregator.flask_app import (
    get_local_user,
    list_mapped_links,
    list_all_panels,
    collect_links,
    filter_dedupe,
    get_setting,
    get_agent,
    get_agent_total_used,
    list_all_agent_links,
    mark_agent_disabled,
    mark_user_disabled,
    disable_remote,
)

router = APIRouter(prefix="/sub", tags=["Subscription"], dependencies=[Depends(get_identity)])


class LinksOut(BaseModel):
    """List of subscription links."""
    links: List[str] = Field(..., description="Subscription config links")

    model_config = {
        "json_schema_extra": {
            "example": {
                "links": [
                    "vless://example@host:443?encryption=none#Example",
                    "vmess://YmFzZTY0ZW5jb2RlZA=="
                ]
            }
        }
    }


class LinksRequest(BaseModel):
    owner_id: int | None = Field(None, description="Target agent ID (admin only)")


# POST is used because the endpoint requires a JSON body. GET requests
# with required bodies are non-standard and may be dropped by proxies.
@router.post("/{username}/links", response_model=LinksOut)
def get_links(
    username: str,
    data: LinksRequest,
    identity: Identity = Depends(get_identity),
) -> LinksOut:
    """Return active subscription links for a user.

    Checks agent and user quotas/expiry before returning links. Returns an
    empty list if the limits are exceeded.
    """
    real_owner = identity.agent_id if identity.role == "agent" else data.owner_id
    if real_owner is None:
        raise HTTPException(status_code=400, detail="owner_id required")

    lu = get_local_user(real_owner, username)
    if not lu:
        return LinksOut(links=[])

    ag = get_agent(real_owner)
    if ag:
        limit_b = int(ag.get("plan_limit_bytes") or 0)
        exp = ag.get("expire_at")
        pushed_a = int(ag.get("disabled_pushed") or 0)
        expired = bool(exp and exp <= datetime.utcnow())
        exceeded = False
        if limit_b > 0:
            used_total = get_agent_total_used(real_owner)
            exceeded = used_total >= limit_b
        if expired or exceeded:
            if not pushed_a:
                for l in list_all_agent_links(real_owner):
                    disable_remote(
                        l["panel_type"],
                        l["panel_url"],
                        l["access_token"],
                        l["remote_username"],
                    )
                mark_agent_disabled(real_owner)
            return LinksOut(links=[])

    limit = int(lu["plan_limit_bytes"])
    used = int(lu["used_bytes"])
    pushed = int(lu.get("disabled_pushed") or 0)
    if limit > 0 and used >= limit:
        if not pushed:
            links = list_mapped_links(real_owner, username)
            if not links:
                panels = list_all_panels(real_owner)
                links = [
                    {
                        "panel_id": p["id"],
                        "remote_username": username,
                        "panel_url": p["panel_url"],
                        "access_token": p["access_token"],
                        "panel_type": p["panel_type"],
                    }
                    for p in panels
                ]
            for l in links:
                disable_remote(
                    l["panel_type"],
                    l["panel_url"],
                    l["access_token"],
                    l["remote_username"],
                )
            mark_user_disabled(real_owner, username)
        return LinksOut(links=[])

    mapped = list_mapped_links(real_owner, username)
    all_links: List[str] = []
    if mapped:
        all_links, _, _ = collect_links(mapped, username, False)
    else:
        panels = list_all_panels(real_owner)
        mappings = [
            {
                "panel_id": p["id"],
                "remote_username": username,
                "panel_url": p["panel_url"],
                "access_token": p["access_token"],
                "panel_type": p["panel_type"],
            }
            for p in panels
        ]
        all_links, _, _ = collect_links(mappings, username, False)

    uniq = filter_dedupe(all_links)
    sid = lu.get("service_id") if lu else None
    emerg = None
    if sid:
        emerg = get_setting(real_owner, f"emergency_config_service_{sid}")
    if not emerg:
        emerg = get_setting(real_owner, "emergency_config")
    if emerg:
        uniq.append(emerg.strip())
        uniq = filter_dedupe(uniq)

    return LinksOut(links=uniq)


__all__ = ("router",)
