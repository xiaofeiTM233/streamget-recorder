"""loguru 配置 + 内存环形缓冲（供前端查看/WS 推送）。"""

import sys
from collections import deque
from typing import Callable

from loguru import logger

from .config import config


class LogBuffer:
    def __init__(self, maxlen: int = 800):
        self._lines: deque[str] = deque(maxlen=maxlen)
        self._broadcaster: Callable[[str], None] | None = None

    def attach(self, broadcaster: Callable[[str], None]) -> None:
        self._broadcaster = broadcaster

    def sink(self, message) -> None:
        line = message.rstrip("\n")
        self._lines.append(line)
        if self._broadcaster is not None:
            try:
                self._broadcaster(line)
            except Exception:  # 广播失败不影响主流程
                pass

    def recent(self, limit: int = 200) -> list[str]:
        return list(self._lines)[-limit:]


log_buffer = LogBuffer()


def setup_logging() -> None:
    logger.remove()
    logger.add(sys.stderr, level=config.log_level.upper())
    logs_dir = config.data_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    logger.add(
        logs_dir / "recorder_{time:YYYYMMDD}.log",
        rotation="20 MB",
        retention="14 days",
        level="INFO",
        encoding="utf-8",
    )
    logger.add(log_buffer.sink, level="INFO")
