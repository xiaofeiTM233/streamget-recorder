"""FastAPI 入口：生命周期管理 + API 路由 + 前端静态托管。

启动：python main.py 或 uvicorn main:app --port 8000
"""

import asyncio
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from loguru import logger

from app.__version__ import __version__
from app.api import api_router, ws_router
from app.config import config
from app.core.events import bus
from app.core.manager import RecorderManager
from app.core.scheduler import PollingScheduler
from app.db import dispose_db, init_db, session_factory
from app.log import log_buffer, setup_logging
from app.models import RecordingFile, RecordingSession, Room
from app.settings_service import SettingsService
from app.utils import utcnow

BASE_DIR = Path(__file__).resolve().parent


async def recover_interrupted() -> None:
    """状态恢复：清理上次运行遗留的"僵尸录制"状态，保证无人值守可靠性。"""
    from sqlalchemy import select

    factory = session_factory()
    async with factory() as s:
        rows = (await s.execute(
            select(RecordingSession).where(RecordingSession.status == "recording")
        )).scalars().all()
        for row in rows:
            row.status = "error"
            row.end_time = utcnow()
        file_rows = (await s.execute(
            select(RecordingFile).where(RecordingFile.status == "recording")
        )).scalars().all()
        for row in file_rows:
            row.status = "error"
            row.end_time = utcnow()
        room_rows = (await s.execute(
            select(Room).where(Room.status.in_(("recording", "error")))
        )).scalars().all()
        for room in room_rows:
            room.status = "idle"
            room.status_msg = "服务重启，已恢复监控"
        await s.commit()
        if rows or file_rows or room_rows:
            logger.info(
                "状态恢复完成：清理 {} 个会话、{} 个分段、{} 个房间状态",
                len(rows), len(file_rows), len(room_rows),
            )


@asynccontextmanager
async def lifespan(app: FastAPI):
    config.resolve_paths(BASE_DIR)
    setup_logging()
    await init_db()

    settings_svc = SettingsService()
    await settings_svc.load()

    manager = RecorderManager(settings_svc)
    scheduler = PollingScheduler(manager, settings_svc)

    await recover_interrupted()
    await scheduler.reload()

    app.state.settings_svc = settings_svc
    app.state.manager = manager
    app.state.scheduler = scheduler
    log_buffer.attach(lambda line: bus.publish("log", line=line))

    logger.info("录播服务已就绪 v{} → http://{}:{}（数据目录: {}）", __version__, config.host, config.port, config.data_dir)
    yield

    logger.info("正在停止服务…")
    log_buffer.attach(lambda line: None)
    await scheduler.stop()
    await manager.stop_all()
    await dispose_db()
    logger.info("服务已退出")


def create_app() -> FastAPI:
    config.resolve_paths(BASE_DIR)
    app = FastAPI(
        title="StreamGet Recorder",
        version=__version__,
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router, prefix="/api")
    app.include_router(ws_router)  # /ws

    panel_dir: Path = config.panel_dir
    if panel_dir.is_dir():
        app.mount("/", StaticFiles(directory=panel_dir, html=True), name="panel")
    else:
        logger.warning("前端静态产物不存在（{}），仅提供 API。开发期请运行 panel 的 dev server", panel_dir)
    return app


app = create_app()


def run() -> None:
    import uvicorn

    uvicorn.run("main:app", host=config.host, port=config.port, log_config=None)


if __name__ == "__main__":
    run()
