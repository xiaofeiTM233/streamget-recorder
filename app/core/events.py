"""进程内事件总线：引擎各处发布事件，WS 层订阅后推送给前端。

发布为非阻塞：订阅者各自持有有界队列，队列满时丢弃最旧事件（实时状态类
消息允许丢弃，只保证最新）。
"""

import asyncio
from datetime import datetime, timezone
from loguru import logger


class EventBus:
    def __init__(self, queue_size: int = 500):
        self._subs: set[asyncio.Queue] = set()
        self._queue_size = queue_size

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=self._queue_size)
        self._subs.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subs.discard(queue)

    def publish(self, type_: str, **payload) -> None:
        if not self._subs:
            return
        event = {
            "type": type_,
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            **payload,
        }
        for queue in list(self._subs):
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            try:
                queue.put_nowait(event)
            except Exception as exc:  # pragma: no cover
                logger.debug("事件投递失败: {}", exc)

    def subscriber_count(self) -> int:
        return len(self._subs)


bus = EventBus()
