"""开发验证脚本：用 custom 平台录制公开测试流，端到端验证录制引擎。

用法（在 recorder/ 目录下）：
    uv run python scripts/dev_record_test.py [stream_url]

不传 URL 时使用内置 HLS 测试流，录制 15 秒后优雅停止，
可在 data/test_recordings/ 下检查产物，并观察事件流输出。
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loguru import logger  # noqa: E402

from app.config import config  # noqa: E402
from app.core.events import bus  # noqa: E402
from app.core.monitor import CheckResult  # noqa: E402
from app.core.recorder import Recorder  # noqa: E402
from app.log import setup_logging  # noqa: E402
from app.models import Room  # noqa: E402
from app.settings_service import SettingsService  # noqa: E402
from app.store import store  # noqa: E402

DEFAULT_TEST_STREAM = "https://test-streams.mux.dev/x36xhzz/x36xhzz.m3u8"


async def consume_events() -> None:
    queue = bus.subscribe()
    while True:
        event = await queue.get()
        logger.info("[事件] {}", {k: v for k, v in event.items() if k != "ts"})


async def main() -> None:
    setup_logging()
    await store.load()
    settings = SettingsService()
    await settings.load()
    # 测试产物单独目录（相对路径会锚定到 data_dir，不污染正式录制目录）
    settings._cache["record_dir"] = "test_recordings"

    url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_TEST_STREAM

    room = await store.create_room(
        platform="custom", room_url=url, quality="OD", enabled=True, anchor_name="dev测试"
    )
    room_id = room.id
    check = CheckResult(is_live=True, anchor_name="dev测试", title="直链录制测试", raw={})

    consumer = asyncio.create_task(consume_events())
    recorder = Recorder(room=room, check=check, settings=settings)
    # 测试流多为点播 m3u8（含 ENDLIST 会被探测判定离线），固定返回开播以覆盖录制路径
    async def _fake_check(room_url: str) -> CheckResult:
        return check

    recorder._monitor.check = _fake_check
    recorder._monitor._room_url = url
    recorder.start()

    await asyncio.sleep(15)
    await recorder.stop("测试时间到")
    await recorder.wait()

    consumer.cancel()
    # 清理测试数据（级联删除会话与分段记录，磁盘文件保留供检查）
    await store.delete_room(room_id)
    logger.info("测试完成，请检查 {}", settings.record_root())


if __name__ == "__main__":
    asyncio.run(main())
