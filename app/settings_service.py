"""运行时可变设置（数据库 KV 存储，前端可改，引擎实时读取）。

默认值同时定义了键与类型，get() 按默认值类型做转换。
"""

from pathlib import Path

from loguru import logger
from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from .config import config
from .db import session_factory
from .models import SettingKV

DEFAULTS: dict[str, object] = {
    "check_interval": 60,        # 开播检测间隔（秒）
    "quality": "OD",             # 默认清晰度
    "output_format": "mp4",      # mp4 | flv
    "record_dir": "",            # 录制保存目录，空 = data/recordings
    "ffmpeg_path": "ffmpeg",     # FFmpeg 可执行文件路径
    "proxy_addr": "",            # 全局代理（国际平台用），空 = 不使用
    "reconnect_backoff_max": 300,  # 断流/失败重试的最大退避（秒）
    "file_template": "{platform}/{anchor}/{datetime}_{title}",
}


class SettingsService:
    def __init__(self) -> None:
        self._cache: dict[str, str] = {}

    async def load(self) -> None:
        factory = session_factory()
        async with factory() as s:
            rows = (await s.execute(select(SettingKV))).scalars().all()
        self._cache = {row.key: row.value for row in rows}

    def get(self, key: str):
        if key not in DEFAULTS:
            raise KeyError(f"未知设置项: {key}")
        raw = self._cache.get(key)
        if raw is None or raw == "":
            # 空字符串按类型回退默认值（int/bool 无法解析空串）
            return DEFAULTS[key]
        default = DEFAULTS[key]
        try:
            if isinstance(default, bool):
                return raw.lower() in ("1", "true", "yes")
            if isinstance(default, int):
                return int(float(raw))
            return raw
        except (ValueError, TypeError):
            logger.warning("设置项 {} 值非法: {!r}，回退默认值", key, raw)
            return default

    def all(self) -> dict[str, object]:
        return {key: self.get(key) for key in DEFAULTS}

    async def set_many(self, updates: dict[str, object]) -> None:
        unknown = set(updates) - set(DEFAULTS)
        if unknown:
            raise ValueError(f"未知设置项: {', '.join(sorted(unknown))}")
        factory = session_factory()
        async with factory() as s:
            for key, value in updates.items():
                if value is None:
                    continue
                str_value = str(value)
                stmt = sqlite_insert(SettingKV).values(key=key, value=str_value)
                stmt = stmt.on_conflict_do_update(index_elements=["key"], set_={"value": str_value})
                await s.execute(stmt)
            await s.commit()
        self._cache.update({k: str(v) for k, v in updates.items() if v is not None})

    def record_root(self) -> Path:
        """录制文件根目录：设置了绝对路径用之，否则相对 data_dir。"""
        custom = str(self.get("record_dir") or "")
        if custom:
            path = Path(custom)
            return path if path.is_absolute() else config.data_dir / path
        return config.data_dir / "recordings"
