"""Identity lookup routes."""
from fastapi import APIRouter, Depends

from api.auth import Identity, get_identity

router = APIRouter(prefix="/identity", tags=["Identity"])


@router.get("/whoami")
async def who_am_i(identity: Identity = Depends(get_identity)) -> dict[str, object | None]:
    """Return the authenticated identity details."""
    return {
        "role": identity.role,
        "agent_id": identity.agent_id,
        "agent_name": identity.agent_name,
    }


__all__ = ["router"]
