"""ASGI application wiring for FastAPI endpoints."""
import logging

from fastapi import FastAPI
from starlette.middleware.wsgi import WSGIMiddleware
from dotenv import load_dotenv

from api.routes import api_router
from api.subscription_aggregator import create_flask_app
from services import init_mysql_pool, ensure_schema, load_database_settings

log = logging.getLogger(__name__)

app = FastAPI()


@app.on_event("startup")
async def startup_event() -> None:
    """Initialize resources on application startup."""
    load_dotenv()
    settings = load_database_settings(force_refresh=True)
    if settings.backend == "mysql":
        init_mysql_pool()
        ensure_schema()
    else:
        mongo = settings.mongo
        if mongo:
            log.info(
                "MongoDB backend selected; using host %s on port %s",
                mongo.host,
                mongo.port,
            )


app.include_router(api_router, prefix="/api/v1")
app.mount("/", WSGIMiddleware(create_flask_app()))

__all__ = ("app",)
