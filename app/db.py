"""异步 SQLAlchemy + aiosqlite。单文件库足够单机场景，WAL 提升并发读。"""

from pathlib import Path

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from .config import config

_engine: AsyncEngine | None = None
SessionLocal: async_sessionmaker[AsyncSession] | None = None


async def init_db() -> None:
    global _engine, SessionLocal
    from .models import Base  # noqa: F401  确保模型已注册到 metadata

    config.data_dir.mkdir(parents=True, exist_ok=True)
    db_path = config.data_dir / "recorder.db"
    _engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path.as_posix()}",
        connect_args={"timeout": 15},
    )

    @event.listens_for(_engine.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, _record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=15000")
        cursor.close()

    SessionLocal = async_sessionmaker(_engine, expire_on_commit=False)
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def dispose_db() -> None:
    global _engine, SessionLocal
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    SessionLocal = None


def session_factory() -> async_sessionmaker[AsyncSession]:
    if SessionLocal is None:
        raise RuntimeError("数据库尚未初始化")
    return SessionLocal
