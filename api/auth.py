import os
import hashlib
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, Request, status

from bot import with_mysql_cursor


ADMIN_API_TOKEN = os.getenv("ADMIN_API_TOKEN", "")


@dataclass
class Identity:
    role: str
    agent_id: int | None = None
    agent_name: str | None = None


async def get_identity(request: Request, authorization: str | None = Header(None)) -> Identity:
    """Resolve the requesting identity from an Authorization header.

    Validates the provided bearer token against known admin or agent tokens and
    attaches the resulting identity to the request state.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")

    token = authorization.split()[1]

    if ADMIN_API_TOKEN and token == ADMIN_API_TOKEN:
        identity = Identity(role="admin")
        request.state.identity = identity
        return identity

    token_hash = hashlib.sha256(token.encode()).hexdigest()
    with with_mysql_cursor() as cur:
        cur.execute("SELECT telegram_user_id, name FROM agents WHERE api_token=%s", (token_hash,))
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")

    identity = Identity(role="agent", agent_id=row["telegram_user_id"], agent_name=row["name"])
    request.state.identity = identity
    return identity


async def require_admin(identity: Identity = Depends(get_identity)) -> Identity:
    """Ensure the requester is an admin."""
    if identity.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    return identity


async def require_agent(identity: Identity = Depends(get_identity)) -> Identity:
    """Ensure the requester is an agent."""
    if identity.role != "agent":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    return identity
