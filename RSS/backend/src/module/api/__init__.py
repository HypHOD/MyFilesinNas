from fastapi import APIRouter

from .bangumi import router as bangumi_router
from .config import router as config_router
from .program import router as program_router
from .rss import router as rss_router

__all__ = "v1"

# API v1
v1 = APIRouter(prefix="/v1")
v1.include_router(program_router)
v1.include_router(bangumi_router)
v1.include_router(config_router)
v1.include_router(rss_router)
