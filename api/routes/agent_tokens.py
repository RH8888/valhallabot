"""Agent token management routes."""
from fastapi import APIRouter, Depends, HTTPException

from api.auth import Identity, require_admin, require_agent
from services import (
    get_agent_record,
    get_agent_token_value,
    rotate_agent_token_value,
)

router = APIRouter(prefix="/agents", tags=["Agent Tokens"])


@router.get("/{agent_id}/token")
async def get_agent_token_endpoint(agent_id: int, _: Identity = Depends(require_admin)) -> dict[str, str]:
    """Return the API token for the requested agent."""
    try:
        token = get_agent_token_value(agent_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Agent not found") from exc
    return {"api_token": token}


@router.post("/{agent_id}/token")
async def rotate_agent_token_endpoint(agent_id: int, _: Identity = Depends(require_admin)) -> dict[str, str]:
    """Rotate and return a new API token for the requested agent."""
    try:
        token = rotate_agent_token_value(agent_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Agent not found") from exc
    return {"api_token": token}


@router.get("/me/token")
async def get_my_token(identity: Identity = Depends(require_agent)) -> dict[str, str]:
    """Return the API token for the authenticated agent."""
    agent = get_agent_record(identity.agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    try:
        token = get_agent_token_value(agent["id"])
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Agent not found") from exc
    return {"api_token": token}


@router.post("/me/token")
async def rotate_my_token(identity: Identity = Depends(require_agent)) -> dict[str, str]:
    """Rotate and return a new token for the authenticated agent."""
    agent = get_agent_record(identity.agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    token = rotate_agent_token_value(agent["id"])
    return {"api_token": token}


__all__ = ["router"]
