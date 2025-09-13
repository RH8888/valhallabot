from fastapi import FastAPI, APIRouter, HTTPException, Depends
from dotenv import load_dotenv

from bot import init_mysql_pool, ensure_schema
from models.agents import rotate_api_token
from api.auth import require_admin

app = FastAPI()

router = APIRouter()


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
