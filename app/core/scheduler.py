"""轮询调度器：每个启用的房间一个独立 asyncio 任务。

- 检测开播 → 录制（await 录制会话结束）→ 继续轮询，天然避免并发重复录制
- 间隔 = 房间级配置或全局设置，加 ±15% 抖动防雪崩；检测失败指数退避
- 支持外部唤醒（立即检测）
"""

import asyncio
import random

from loguru import logger
from sqlalchemy import select

from ..db import session_factory
from ..models import Room
from ..settings_service import SettingsService
from ..utils import utcnow
from .events import bus
from .manager import RecorderManager
from .monitor import MonitorError, RoomMonitor


class PollingScheduler:
    def __init__(self, manager: RecorderManager, settings: SettingsService):
        self._manager = manager
        self._settings = settings
        self._tasks: dict[int, asyncio.Task] = {}
        self._wakes: dict[int, asyncio.Event] = {}
        self._closing = False

    # ---------- 任务集管理 ----------

    async def reload(self) -> None:
        """让任务集与数据库中启用房间保持一致（房间增删改后调用）。"""
        factory = session_factory()
        async with factory() as s:
            rooms = (await s.execute(select(Room))).scalars().all()
        wanted = {r.id for r in rooms if r.enabled}
        for room_id in [rid for rid in self._tasks if rid not in wanted]:
            self._cancel_task(room_id)
        for room_id in wanted - set(self._tasks):
            wake = asyncio.Event()
            self._wakes[room_id] = wake
            self._tasks[room_id] = asyncio.create_task(
                self._poll_room(room_id, wake), name=f"poll-{room_id}"
            )

    def trigger_check(self, room_id: int) -> None:
        wake = self._wakes.get(room_id)
        if wake is not None:
            wake.set()

    def trigger_check_all(self) -> int:
        """全部刷新：唤醒所有轮询任务立即检测一遍，返回唤醒数量。"""
        for wake in self._wakes.values():
            wake.set()
        return len(self._wakes)

    async def stop(self) -> None:
        self._closing = True
        for room_id in list(self._tasks):
            self._cancel_task(room_id)
        self._tasks.clear()
        self._wakes.clear()

    def _cancel_task(self, room_id: int) -> None:
        task = self._tasks.pop(room_id, None)
        wake = self._wakes.pop(room_id, None)
        if wake is not None:
            wake.set()
        if task is not None and not task.done():
            task.cancel()

    # ---------- 单房间轮询 ----------

    async def _poll_room(self, room_id: int, wake: asyncio.Event) -> None:
        logger.info("房间 #{} 开始监控", room_id)
        failures = 0
        while not self._closing:
            room = await self._get_room(room_id)
            if room is None or not room.enabled:
                break
            proxy = str(self._settings.get("proxy_addr") or "") or None
            monitor = RoomMonitor(room.platform, cookies=room.cookie or None, proxy_addr=proxy)
            try:
                check = await monitor.check(room.room_url)
                failures = 0
            except Exception as exc:  # 平台解析故障不应杀死轮询任务
                failures += 1
                await self._set_room_status(room_id, "error", f"检测失败：{exc}")
                interval = int(room.check_interval or self._settings.get("check_interval"))
                await self._sleep(wake, min(300, max(interval, 30) * failures))
                continue

            await self._update_after_check(room_id, check)
            if check.is_live:
                recorder = await self._manager.start(room, check)
                if recorder is None:
                    # 并发上限已满：标记状态等待空位，稍后自动重试
                    await self._set_room_status(room_id, "error", "并发录制数已达上限，等待空位后自动重试")
                    await self._sleep(wake, 30)
                    continue
                await recorder.wait()  # 录制会话结束（下播/异常）后再恢复轮询
                await self._sleep(wake, 5)
            else:
                interval = int(room.check_interval or self._settings.get("check_interval"))
                await self._sleep(wake, interval * random.uniform(0.85, 1.15))
        logger.info("房间 #{} 停止监控", room_id)

    async def _get_room(self, room_id: int) -> Room | None:
        factory = session_factory()
        async with factory() as s:
            return await s.get(Room, room_id)

    @staticmethod
    async def _sleep(wake: asyncio.Event, seconds: float) -> None:
        wake.clear()
        try:
            await asyncio.wait_for(wake.wait(), timeout=max(seconds, 0.5))
        except asyncio.TimeoutError:
            pass

    async def _update_after_check(self, room_id: int, check) -> None:
        """回填主播名/检测时间；未开播则状态置 idle。"""
        factory = session_factory()
        async with factory() as s:
            room = await s.get(Room, room_id)
            if room is None:
                return
            if check.anchor_name and check.anchor_name != room.anchor_name:
                room.anchor_name = check.anchor_name
            room.last_check_at = utcnow()
            if not check.is_live:
                room.status = "idle"
                room.status_msg = ""
            await s.commit()
        bus.publish(
            "room_status",
            room_id=room_id,
            status=room.status,
            status_msg=room.status_msg,
            is_live=check.is_live,
            anchor_name=check.anchor_name,
            title=check.title,
        )

    async def _set_room_status(self, room_id: int, status: str, msg: str) -> None:
        factory = session_factory()
        async with factory() as s:
            room = await s.get(Room, room_id)
            if room is None:
                return
            room.status = status
            room.status_msg = msg[:250]
            await s.commit()
        bus.publish("room_status", room_id=room_id, status=status, status_msg=msg[:250])
