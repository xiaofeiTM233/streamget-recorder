"""API 路由聚合。"""

from fastapi import APIRouter, Depends

from . import recordings, rooms, settings, system
from .deps import require_token
from .ws import router as ws_router

api_router = APIRouter(dependencies=[Depends(require_token)])
api_router.include_router(system.router, tags=["system"])
api_router.include_router(rooms.router, prefix="/rooms", tags=["rooms"])
api_router.include_router(recordings.router, prefix="/recordings", tags=["recordings"])
api_router.include_router(settings.router, prefix="/settings", tags=["settings"])

__all__ = ["api_router", "ws_router"]
