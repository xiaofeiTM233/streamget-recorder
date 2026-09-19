"""FastAPI 入口：生命周期管理 + API 路由 + 前端静态托管。

启动：python main.py 或 uvicorn main:app --port 8000
"""

import asyncio
import sys
import time
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from loguru import logger

from app.__version__ import __version__
from app.api import api_router, ws_router
from app.config import config
from app.core.events import bus
from app.core.http_pool import aclose_all as close_http_pool
from app.core.manager import RecorderManager
from app.core.scheduler import PollingScheduler
from app.log import log_buffer, setup_logging
from app.settings_service import SettingsService
from app.store import store

BASE_DIR = Path(__file__).resolve().parent


async def retention_cleanup_loop(settings_svc: SettingsService) -> None:
    """按设置的保留天数定期清理过期录制文件（按磁盘 mtime，0 = 永久保留），并清空目录。"""
    import os

    while True:
        await asyncio.sleep(3600)  # 每小时检查一次
        try:
            days = int(settings_svc.get("retention_days") or 0)
            if days <= 0:
                continue
            root = settings_svc.record_root()
            if not root.is_dir():
                continue
            cutoff = time.time() - days * 86400
            removed = 0
            for dirpath, _dirnames, filenames in os.walk(root):
                for name in filenames:
                    full = os.path.join(dirpath, name)
                    try:
                        if os.stat(full).st_mtime < cutoff:
                            os.unlink(full)
                            removed += 1
                    except OSError as exc:
                        logger.warning("清理录制文件失败 {}: {}", full, exc)
            # 自底向上清掉空目录（保留根目录本身）
            for dirpath, dirnames, _filenames in os.walk(root, topdown=False):
                if dirpath == str(root):
                    continue
                for name in dirnames:
                    empty_dir = os.path.join(dirpath, name)
                    with suppress(OSError):
                        os.rmdir(empty_dir)  # 仅成功当目录为空
            if removed:
                logger.info("已按保留期（{} 天）清理 {} 个录制文件", days, removed)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("录制文件保留期清理任务异常")


@asynccontextmanager
async def lifespan(app: FastAPI):
    config.resolve_paths(BASE_DIR)
    setup_logging()
    await store.load()

    # Windows Proactor 循环在对端强断连接（RST）时会在连接关闭回调里抛
    # ConnectionResetError(10054)，属已知无害噪音；降为 debug 日志，其余照常处理
    loop = asyncio.get_running_loop()

    def _quiet_connection_reset(l: asyncio.AbstractEventLoop, context: dict) -> None:
        exc = context.get("exception")
        if isinstance(exc, ConnectionResetError):
            logger.debug("连接被对端重置（已忽略）：{}", exc)
            return
        l.default_exception_handler(context)

    loop.set_exception_handler(_quiet_connection_reset)

    settings_svc = SettingsService()
    await settings_svc.load()

    manager = RecorderManager(settings_svc)
    scheduler = PollingScheduler(manager, settings_svc)

    n_rooms = await store.recover_rooms()
    if n_rooms:
        logger.info("状态恢复完成：清理 {} 个房间状态", n_rooms)
    await scheduler.reload()

    app.state.settings_svc = settings_svc
    app.state.manager = manager
    app.state.scheduler = scheduler
    log_buffer.attach(lambda line: bus.publish("log", line=line))

    retention_task = asyncio.create_task(retention_cleanup_loop(settings_svc))

    logger.info("录播服务已就绪 v{} → http://{}:{}（数据目录: {}）", __version__, config.host, config.port, config.data_dir)
    yield

    logger.info("正在停止服务…")
    retention_task.cancel()
    with suppress(asyncio.CancelledError):
        await retention_task
    log_buffer.attach(lambda line: None)
    await scheduler.stop()
    await manager.stop_all()
    await close_http_pool()  # 关闭共享 HTTP 连接池
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

    # HTML 禁止缓存：避免前端发新版后浏览器仍用旧页面（JS 产物文件名带哈希，可长期缓存）
    @app.middleware("http")
    async def _no_cache_html(request: Request, call_next):
        response = await call_next(request)
        if "text/html" in response.headers.get("content-type", ""):
            response.headers["Cache-Control"] = "no-cache"
        return response

    panel_dir: Path = config.panel_dir
    if panel_dir.is_dir():
        app.mount("/", StaticFiles(directory=panel_dir, html=True), name="panel")
    else:
        logger.warning("前端静态产物不存在（{}），仅提供 API。开发期请运行 panel 的 dev server", panel_dir)
    return app


app = create_app()


def run() -> None:
    import uvicorn

    # 打包(PyInstaller)运行时无法按模块名重新导入，必须直接传 app 对象
    if getattr(sys, "frozen", False):
        uvicorn.run(app, host=config.host, port=config.port, log_config=None)
    else:
        uvicorn.run("main:app", host=config.host, port=config.port, log_config=None)


if __name__ == "__main__":
    run()
