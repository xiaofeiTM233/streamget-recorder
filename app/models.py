"""ORM 模型：房间、录制会话、分段文件（运行时设置存 data/settings.json）。"""

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from .utils import utcnow


class Base(DeclarativeBase):
    pass


class Room(Base):
    __tablename__ = "rooms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    platform: Mapped[str] = mapped_column(String(32), index=True)
    room_url: Mapped[str] = mapped_column(String(512))
    anchor_name: Mapped[str] = mapped_column(String(128), default="")
    remark: Mapped[str] = mapped_column(String(255), default="")
    quality: Mapped[str] = mapped_column(String(8), default="OD")
    check_interval: Mapped[int | None] = mapped_column(Integer, default=None)  # None=用全局
    cookie: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # idle=监控中未开播 | recording=录制中 | error=异常 | disabled=已停用
    status: Mapped[str] = mapped_column(String(16), default="idle")
    status_msg: Mapped[str] = mapped_column(String(255), default="")
    last_check_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    sessions: Mapped[list["RecordingSession"]] = relationship(
        back_populates="room", cascade="all, delete-orphan", passive_deletes=True
    )


class RecordingSession(Base):
    """一次连续的录制会话（可能因断流分成多个文件）。"""

    __tablename__ = "recording_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    room_id: Mapped[int] = mapped_column(
        ForeignKey("rooms.id", ondelete="CASCADE"), index=True
    )
    platform: Mapped[str] = mapped_column(String(32))
    anchor_name: Mapped[str] = mapped_column(String(128), default="")
    title: Mapped[str] = mapped_column(String(255), default="")
    quality: Mapped[str] = mapped_column(String(8), default="")
    start_time: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    end_time: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    status: Mapped[str] = mapped_column(String(16), default="recording")  # recording|finished|error

    room: Mapped[Room] = relationship(back_populates="sessions")
    files: Mapped[list["RecordingFile"]] = relationship(
        back_populates="session", cascade="all, delete-orphan", passive_deletes=True
    )


class RecordingFile(Base):
    __tablename__ = "recording_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("recording_sessions.id", ondelete="CASCADE"), index=True
    )
    room_id: Mapped[int] = mapped_column(
        ForeignKey("rooms.id", ondelete="CASCADE"), index=True
    )
    file_path: Mapped[str] = mapped_column(String(1024))  # 相对录制根目录
    size: Mapped[int] = mapped_column(BigInteger, default=0)
    duration: Mapped[float] = mapped_column(Float, default=0.0)  # 秒
    start_time: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    end_time: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    status: Mapped[str] = mapped_column(String(16), default="recording")  # recording|finished|error

    session: Mapped["RecordingSession"] = relationship(back_populates="files")
