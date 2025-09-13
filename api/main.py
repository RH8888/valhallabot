import os

from fastapi import FastAPI, APIRouter, HTTPException, Header, Depends
from dotenv import load_dotenv

from bot import init_mysql_pool, ensure_schema
from models.agents import rotate_api_token

app = FastAPI()

router = APIRouter()


ADMIN_API_TOKEN = os.getenv("ADMIN_API_TOKEN", "")


async def require_admin(x_admin_token: str = Header(...)):
    if not ADMIN_API_TOKEN or x_admin_token != ADMIN_API_TOKEN:
        raise HTTPException(status_code=403, detail="Forbidden")


@router.get("/health")
async def health_check():
    """Simple health check endpoint."""
    return {"status": "ok"}


@router.post("/agents/{agent_id}/token")
async def rotate_agent_token_endpoint(agent_id: int, _: None = Depends(require_admin)):
    try:
        token = rotate_api_token(agent_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Agent not found")
    return {"api_token": token}


@app.on_event("startup")
async def startup_event():
    """Initialize resources on application startup."""
    load_dotenv()
    init_mysql_pool()
    ensure_schema()


app.include_router(router, prefix="/api/v1")

__all__ = ("app",)
