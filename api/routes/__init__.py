"""Collection of FastAPI routers."""
from fastapi import APIRouter

from api.activation import router as activation_router
from api.admin import router as admin_router
from api.sub import router as sub_router
from api.users import router as users_router

from .agent_tokens import router as agent_token_router
from .health import router as health_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(agent_token_router)
api_router.include_router(admin_router)
api_router.include_router(users_router)
api_router.include_router(sub_router)
api_router.include_router(activation_router)

__all__ = ["api_router"]
