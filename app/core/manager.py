"""RecorderManager：维护 room_id → Recorder 的注册表，负责并发去重与全局停止。"""

import asyncio

from loguru import logger

from ..models import Room
from ..settings_service import SettingsService
from .events import bus
from .monitor import CheckResult
from .recorder import Recorder


class RecorderManager:
    def __init__(self, settings: SettingsService):
        self._settings = settings
        self._recorders: dict[int, Recorder] = {}

    def is_recording(self, room_id: int) -> bool:
        return room_id in self._recorders

    def get(self, room_id: int) -> Recorder | None:
        return self._recorders.get(room_id)

    def active_room_ids(self) -> list[int]:
        return list(self._recorders)

    async def start(self, room: Room, check: CheckResult) -> Recorder | None:
        """开始录制；已在录制中则直接返回现有实例（并发去重）。

        并发上限（全局/单平台，0 = 不限制）已满时返回 None，由调用方等待空位。
        """
        existing = self._recorders.get(room.id)
        if existing is not None:
            return existing
        if not self._slot_available(room.platform):
            return None
        recorder = Recorder(room=room, check=check, settings=self._settings)
        self._recorders[room.id] = recorder
        recorder.start()
        task = recorder.task
        if task is not None:
            task.add_done_callback(lambda t, r=recorder: self._cleanup(r, t))
        return recorder

    def _slot_available(self, platform: str) -> bool:
        max_all = int(self._settings.get("max_concurrent") or 0)
        if max_all > 0 and len(self._recorders) >= max_all:
            return False
        max_pf = int(self._settings.get("max_concurrent_per_platform") or 0)
        if max_pf > 0:
            active = sum(1 for r in self._recorders.values() if r.platform == platform)
            if active >= max_pf:
                return False
        return True

    def _cleanup(self, recorder: Recorder, task: asyncio.Task) -> None:
        self._recorders.pop(recorder.room_id, None)
        if not task.cancelled() and task.exception() is not None:
            logger.error("房间 #{} 录制任务异常: {}", recorder.room_id, task.exception())

    async def stop(self, room_id: int, reason: str = "手动停止") -> bool:
        recorder = self._recorders.get(room_id)
        if recorder is None:
            return False
        await recorder.stop(reason)
        return True

    async def stop_all(self, reason: str = "服务关闭") -> None:
        recorders = list(self._recorders.values())
        if not recorders:
            return
        logger.info("正在停止 {} 路录制…", len(recorders))
        await asyncio.gather(*(r.stop(reason) for r in recorders), return_exceptions=True)
        await asyncio.gather(*(r.wait() for r in recorders), return_exceptions=True)
        bus.publish("service_status", status="stopped")

    def progress_snapshot(self) -> dict[int, dict]:
        return {rid: dict(r.progress) for rid, r in self._recorders.items() if r.progress}
