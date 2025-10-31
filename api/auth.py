import hashlib
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, Request, status

from services import with_mysql_cursor


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
    with with_mysql_cursor() as cur:
        cur.execute("SELECT is_super FROM admins WHERE api_token=%s", (token,))
        admin_row = cur.fetchone()
    if admin_row:
        role = "super_admin" if admin_row["is_super"] else "admin"
        identity = Identity(role=role)
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
    if identity.role not in ("admin", "super_admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    return identity


async def require_super_admin(identity: Identity = Depends(require_admin)) -> Identity:
    """Ensure the requester is a super-admin."""
    if identity.role != "super_admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    return identity


async def require_agent(identity: Identity = Depends(get_identity)) -> Identity:
    """Ensure the requester is an agent."""
    if identity.role != "agent":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    return identity
