"""ASGI application wiring for FastAPI endpoints."""
from fastapi import FastAPI
from starlette.middleware.wsgi import WSGIMiddleware
from dotenv import load_dotenv

from api.routes import api_router
from api.subscription_aggregator import create_flask_app
from services import init_mysql_pool, ensure_schema, start_backup_scheduler

app = FastAPI()


@app.on_event("startup")
async def startup_event() -> None:
    """Initialize resources on application startup."""
    load_dotenv()
    from api.web_auth import get_web_session_secret
    get_web_session_secret()
    init_mysql_pool()
    ensure_schema()
    start_backup_scheduler()


app.include_router(api_router, prefix="/api/v1")
app.mount("/", WSGIMiddleware(create_flask_app()))

__all__ = ("app",)
