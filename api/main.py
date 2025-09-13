from fastapi import FastAPI, APIRouter, HTTPException, Depends
from starlette.middleware.wsgi import WSGIMiddleware
from dotenv import load_dotenv

from app import app as flask_app
from bot import init_mysql_pool, ensure_schema
from models.agents import rotate_api_token
from api.auth import require_admin
from api.admin import router as admin_router
from api.users import router as users_router
from api.sub import router as sub_router

# FastAPI application that will also host the existing Flask app
api_app = FastAPI()

router = APIRouter()
router.include_router(admin_router)
router.include_router(users_router)
router.include_router(sub_router)


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


@api_app.on_event("startup")
async def startup_event():
    """Initialize resources on application startup."""
    load_dotenv()
    init_mysql_pool()
    ensure_schema()

# Preserve existing FastAPI routes under /api/v1
api_app.include_router(router, prefix="/api/v1")

# Mount the Flask app at the root path
api_app.mount("/", WSGIMiddleware(flask_app))

# Expose the combined ASGI application
app = api_app

__all__ = ("app",)
