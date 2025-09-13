from fastapi import FastAPI, APIRouter
from dotenv import load_dotenv

from bot import init_mysql_pool

app = FastAPI()

router = APIRouter()


@router.get("/health")
async def health_check():
    """Simple health check endpoint."""
    return {"status": "ok"}


@app.on_event("startup")
async def startup_event():
    """Initialize resources on application startup."""
    load_dotenv()
    init_mysql_pool()


app.include_router(router, prefix="/api/v1")

__all__ = ("app",)
