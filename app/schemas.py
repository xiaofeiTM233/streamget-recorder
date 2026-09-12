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


class RoomUpdate(BaseModel):
    room_url: str | None = Field(None, min_length=4, max_length=512)
    quality: str | None = None
    check_interval: int | None = Field(None, ge=10, le=3600)
    cookie: str | None = None
    remark: str | None = None
    enabled: bool | None = None


class RoomOut(BaseModel):
    id: int
    platform: str
    platform_name: str
    room_url: str
    anchor_name: str
    remark: str
    quality: str
    check_interval: int | None
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


def iso(dt: datetime | None) -> str | None:
    from .utils import iso_utc

    return iso_utc(dt)
