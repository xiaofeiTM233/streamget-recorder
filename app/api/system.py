"""系统级 API：概览统计、平台列表、日志。"""

import os
import time

from fastapi import APIRouter, Query, Request

from ..__version__ import __version__
from ..log import log_buffer
from ..platforms import list_platforms
from ..store import store
from .deps import get_state

router = APIRouter()

_disk_stats_cache: dict = {"ts": 0.0, "size": 0, "count": 0}
_DISK_STATS_TTL = 60.0  # 秒：磁盘扫描结果缓存时长


def _disk_stats(root) -> tuple[int, int]:
    """扫描录制根目录统计总大小与文件数（带 TTL 缓存）。"""
    now = time.time()
    if now - _disk_stats_cache["ts"] < _DISK_STATS_TTL:
        return _disk_stats_cache["size"], _disk_stats_cache["count"]
    total_size = 0
    total_count = 0
    if root.is_dir():
        for dirpath, _dirnames, filenames in os.walk(root):
            for name in filenames:
                try:
                    total_size += os.stat(os.path.join(dirpath, name)).st_size
                    total_count += 1
                except OSError:
                    continue
    _disk_stats_cache.update(ts=now, size=total_size, count=total_count)
    return total_size, total_count


@router.get("/summary")
async def summary(request: Request):
    state = get_state(request)
    rooms = await store.list_rooms()
    recording = len(state.manager.active_room_ids())
    storage_size, file_count = _disk_stats(state.settings_svc.record_root())
    return {
        "rooms_total": len(rooms),
        "rooms_enabled": sum(1 for r in rooms if r.enabled),
        "rooms_error": sum(1 for r in rooms if r.status == "error"),
        "recording": recording,
        "storage_size": storage_size,
        "file_count": file_count,
        "version": __version__,
    }


@router.get("/platforms")
async def platforms():
    return list_platforms()


@router.get("/logs")
async def logs(limit: int = Query(200, ge=1, le=800)):
    return {"lines": log_buffer.recent(limit)}
