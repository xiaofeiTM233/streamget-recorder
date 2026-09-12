"""系统级 API：概览统计、平台列表、日志。"""

from fastapi import APIRouter, Query, Request
from sqlalchemy import func, select

from ..__version__ import __version__
from ..db import session_factory
from ..log import log_buffer
from ..models import RecordingFile, Room
from ..platforms import list_platforms
from .deps import get_state

router = APIRouter()


@router.get("/summary")
async def summary(request: Request):
    state = get_state(request)
    factory = session_factory()
    async with factory() as s:
        rooms_total = (await s.execute(select(func.count()).select_from(Room))).scalar() or 0
        rooms_enabled = (
            await s.execute(select(func.count()).select_from(Room).where(Room.enabled == True))  # noqa: E712
        ).scalar() or 0
        rooms_error = (
            await s.execute(select(func.count()).select_from(Room).where(Room.status == "error"))
        ).scalar() or 0
        storage_size = (
            await s.execute(select(func.coalesce(func.sum(RecordingFile.size), 0)))
        ).scalar() or 0
        file_count = (await s.execute(select(func.count()).select_from(RecordingFile))).scalar() or 0
    recording = len(state.manager.active_room_ids())
    return {
        "rooms_total": rooms_total,
        "rooms_enabled": rooms_enabled,
        "rooms_error": rooms_error,
        "recording": recording,
        "storage_size": int(storage_size),
        "file_count": file_count,
        "version": __version__,
    }


@router.get("/platforms")
async def platforms():
    return list_platforms()


@router.get("/logs")
async def logs(limit: int = Query(200, ge=1, le=800)):
    return {"lines": log_buffer.recent(limit)}
