"""数据模型：房间（持久化到 store.json）、录制会话/分段文件（仅内存跟踪）。"""

from dataclasses import dataclass, field
from datetime import datetime


def _iso_to_dt(value: object) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


@dataclass
class Room:
    id: int = 0
    platform: str = ""
    room_url: str = ""
    anchor_name: str = ""
    remark: str = ""
    quality: str = "OD"
    check_interval: int | None = None  # None=用全局
    cookie: str = ""
    # 房间级设置覆盖（dict），键见 schemas.OVERRIDE_KEYS；空 dict = 全部跟随全局
    overrides: dict = field(default_factory=dict)
    enabled: bool = True
    # idle=监控中未开播 | recording=录制中 | error=异常 | disabled=已停用
    status: str = "idle"
    status_msg: str = ""
    last_check_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "platform": self.platform,
            "room_url": self.room_url,
            "anchor_name": self.anchor_name,
            "remark": self.remark,
            "quality": self.quality,
            "check_interval": self.check_interval,
            "cookie": self.cookie,
            "overrides": self.overrides,
            "enabled": self.enabled,
            "status": self.status,
            "status_msg": self.status_msg,
            "last_check_at": self.last_check_at.isoformat() if self.last_check_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Room":
        return cls(
            id=int(data.get("id") or 0),
            platform=str(data.get("platform") or ""),
            room_url=str(data.get("room_url") or ""),
            anchor_name=str(data.get("anchor_name") or ""),
            remark=str(data.get("remark") or ""),
            quality=str(data.get("quality") or "OD"),
            check_interval=data.get("check_interval"),
            cookie=str(data.get("cookie") or ""),
            overrides=dict(data.get("overrides") or {}),
            enabled=bool(data.get("enabled", True)),
            status=str(data.get("status") or "idle"),
            status_msg=str(data.get("status_msg") or ""),
            last_check_at=_iso_to_dt(data.get("last_check_at")),
            created_at=_iso_to_dt(data.get("created_at")),
            updated_at=_iso_to_dt(data.get("updated_at")),
        )


@dataclass
class RecordingFile:
    """一个分段文件（仅内存跟踪，用于录制流程与录制状态判断）。"""

    id: int = 0
    session_id: int = 0
    room_id: int = 0
    file_path: str = ""  # 相对录制根目录
    size: int = 0
    duration: float = 0.0  # 秒
    start_time: datetime | None = None
    end_time: datetime | None = None
    status: str = "recording"  # recording|finished|error


@dataclass
class RecordingSession:
    """一次连续的录制会话（可能因断流分成多个文件），仅内存跟踪。"""

    id: int = 0
    room_id: int = 0
    platform: str = ""
    anchor_name: str = ""
    title: str = ""
    quality: str = ""
    start_time: datetime | None = None
    end_time: datetime | None = None
    status: str = "recording"  # recording|finished|error
    files: list[RecordingFile] = field(default_factory=list)
