"""Pydantic 请求/响应模型。"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .platforms import QUALITIES


class RoomCreate(BaseModel):
    room_url: str = Field(min_length=4, max_length=512)
    platform: str | None = None          # 不传则根据 URL 自动识别
    quality: str | None = None
    check_interval: int | None = Field(None, ge=10, le=3600)
    cookie: str | None = None
    remark: str | None = None
    enabled: bool = True
    overrides: dict[str, Any] | None = None


class RoomUpdate(BaseModel):
    room_url: str | None = Field(None, min_length=4, max_length=512)
    quality: str | None = None
    check_interval: int | None = Field(None, ge=10, le=3600)
    cookie: str | None = None
    remark: str | None = None
    enabled: bool | None = None
    overrides: dict[str, Any] | None = None


class RoomOut(BaseModel):
    id: int
    platform: str
    platform_name: str
    room_url: str
    anchor_name: str
    remark: str
    quality: str
    check_interval: int | None
    overrides: dict[str, Any]
    has_cookie: bool
    enabled: bool
    status: str
    status_msg: str
    last_check_at: str | None
    recording: bool


class BatchRoomToggle(BaseModel):
    ids: list[int]
    enabled: bool


class RoomSettingsUpdate(BaseModel):
    """允许修改的全局设置（键白名单在服务层校验）。"""

    updates: dict[str, Any]


def validate_quality(quality: str | None) -> str | None:
    if quality is None:
        return None
    quality = quality.upper()
    if quality not in QUALITIES:
        raise ValueError(f"清晰度必须是 {'/'.join(QUALITIES)}")
    return quality


# 房间级可覆盖的设置键及其合法取值（枚举 tuple / 类型 bool/int/str）
OVERRIDE_KEYS: dict[str, tuple | type] = {
    "output_format": ("mp4", "flv"),
    "audio_format": ("auto", "aac", "m4a", "mp3"),
    "stream_type": ("auto", "flv", "hls"),
    "segment_enabled": bool,
    "segment_seconds": int,
    "max_session_hours": int,
    "force_https": bool,
    "flv_direct_download": bool,
    "auto_convert_mp4": bool,
    "delete_original_after_convert": bool,
    "write_time_subtitle": bool,
    "run_script_after": bool,
    "script_after_cmd": str,
}


def validate_overrides(overrides: dict[str, Any] | None) -> dict[str, Any]:
    """过滤并校验房间级设置覆盖：未知键丢弃，类型不符报错。"""
    if not overrides:
        return {}
    result: dict[str, Any] = {}
    for key, value in overrides.items():
        if key not in OVERRIDE_KEYS:
            continue
        allowed = OVERRIDE_KEYS[key]
        if allowed is bool:
            if not isinstance(value, bool):
                raise ValueError(f"覆盖项 {key} 必须是布尔值")
        elif allowed is int:
            try:
                value = int(value)
            except (TypeError, ValueError):
                raise ValueError(f"覆盖项 {key} 必须是整数")
        elif allowed is str:
            value = str(value)
        else:  # 枚举
            if value not in allowed:
                raise ValueError(f"覆盖项 {key} 必须是 {'/'.join(allowed)}")
        result[key] = value
    return result


def iso(dt: datetime | None) -> str | None:
    from .utils import iso_utc

    return iso_utc(dt)
