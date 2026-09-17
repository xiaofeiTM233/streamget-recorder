"""数据存储：房间持久化到 data/store.json；录制会话/分段仅内存跟踪（重启即清，
录制历史直接从磁盘读取，不做记录）。

房间写入：内存缓存 + asyncio 锁串行化 + 原子替换写盘。
"""

import asyncio
import json
import os
import time
from pathlib import Path

from loguru import logger

from .config import config
from .models import RecordingFile, RecordingSession, Room
from .utils import utcnow


class DataStore:
    def __init__(self) -> None:
        self._path: Path = config.data_dir / "store.json"
        self._lock = asyncio.Lock()
        self._rooms: dict[int, Room] = {}
        # 会话/分段仅内存跟踪，供录制器与接口在运行期使用
        self._sessions: dict[int, RecordingSession] = {}
        self._seq = {"room": 0, "session": 0, "file": 0}

    # ---------- 初始化与持久化 ----------

    async def load(self) -> None:
        config.data_dir.mkdir(parents=True, exist_ok=True)
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                self._rooms = {
                    int(r["id"]): Room.from_dict(r)
                    for r in data.get("rooms", [])
                    if isinstance(r, dict)
                }
                self._seq["room"] = int(
                    (data.get("seq") or {}).get("room") or max(self._rooms, default=0)
                )
                return
            except (json.JSONDecodeError, OSError, ValueError, TypeError, KeyError) as exc:
                logger.warning("数据文件损坏，将重建：{}", exc)
        self._persist()

    def _persist(self) -> None:
        """写 JSON（临时文件 + 原子替换，避免写一半损坏）。"""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "rooms": [r.to_dict() for r in self._rooms.values()],
            "seq": self._seq,
        }
        tmp = self._path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        # Windows 下杀毒/索引器可能短暂锁定新文件，重试替换
        for attempt in range(5):
            try:
                os.replace(tmp, self._path)
                return
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.05 * (attempt + 1))

    # ---------- 房间 ----------

    async def list_rooms(self) -> list[Room]:
        async with self._lock:
            return sorted(self._rooms.values(), key=lambda r: r.id)

    async def get_room(self, room_id: int) -> Room | None:
        async with self._lock:
            return self._rooms.get(room_id)

    async def get_room_by_url(self, room_url: str) -> Room | None:
        async with self._lock:
            for room in self._rooms.values():
                if room.room_url == room_url:
                    return room
            return None

    async def create_room(self, **fields) -> Room:
        async with self._lock:
            self._seq["room"] += 1
            now = utcnow()
            room = Room(id=self._seq["room"], created_at=now, updated_at=now, **fields)
            self._rooms[room.id] = room
            self._persist()
            return room

    async def update_room(self, room_id: int, **fields) -> Room | None:
        async with self._lock:
            room = self._rooms.get(room_id)
            if room is None:
                return None
            for key, value in fields.items():
                setattr(room, key, value)
            room.updated_at = utcnow()
            self._persist()
            return room

    async def update_rooms(self, room_ids: list[int], **fields) -> int:
        async with self._lock:
            updated = 0
            for room_id in room_ids:
                room = self._rooms.get(room_id)
                if room is None:
                    continue
                for key, value in fields.items():
                    setattr(room, key, value)
                room.updated_at = utcnow()
                updated += 1
            if updated:
                self._persist()
            return updated

    async def delete_room(self, room_id: int) -> bool:
        async with self._lock:
            if room_id not in self._rooms:
                return False
            del self._rooms[room_id]
            # 顺带清理该房间的内存会话跟踪
            for sid in [sid for sid, s in self._sessions.items() if s.room_id == room_id]:
                del self._sessions[sid]
            self._persist()
            return True

    async def recover_rooms(self) -> int:
        """服务重启后清理房间遗留的"录制中/异常"状态，返回处理数量。"""
        async with self._lock:
            n = 0
            for room in self._rooms.values():
                if room.status in ("recording", "error"):
                    room.status = "idle"
                    room.status_msg = "服务重启，已恢复监控"
                    n += 1
            if n:
                self._persist()
            return n

    # ---------- 录制会话与分段（仅内存，重启即清） ----------

    async def create_session(self, **fields) -> RecordingSession:
        async with self._lock:
            self._seq["session"] += 1
            session = RecordingSession(id=self._seq["session"], start_time=utcnow(), **fields)
            self._sessions[session.id] = session
            return session

    async def get_session(self, session_id: int) -> RecordingSession | None:
        async with self._lock:
            return self._sessions.get(session_id)

    async def update_session(self, session_id: int, **fields) -> RecordingSession | None:
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            for key, value in fields.items():
                setattr(session, key, value)
            return session

    async def create_file(self, session_id: int, **fields) -> RecordingFile:
        async with self._lock:
            session = self._sessions[session_id]
            self._seq["file"] += 1
            f = RecordingFile(id=self._seq["file"], session_id=session_id,
                              start_time=utcnow(), **fields)
            session.files.append(f)
            return f

    async def get_file(self, file_id: int) -> RecordingFile | None:
        async with self._lock:
            for session in self._sessions.values():
                for f in session.files:
                    if f.id == file_id:
                        return f
            return None

    async def update_file(self, file_id: int, **fields) -> RecordingFile | None:
        async with self._lock:
            f = self._find_file(file_id)
            if f is None:
                return None
            for key, value in fields.items():
                setattr(f, key, value)
            return f

    async def get_file_by_path(self, rel_path: str) -> RecordingFile | None:
        """按相对路径查找内存跟踪的分段（用于浏览/删除时判断录制状态）。"""
        async with self._lock:
            return self._find_file_by_path(rel_path)

    def _find_file(self, file_id: int) -> RecordingFile | None:
        for session in self._sessions.values():
            for f in session.files:
                if f.id == file_id:
                    return f
        return None

    def _find_file_by_path(self, rel_path: str) -> RecordingFile | None:
        for session in self._sessions.values():
            for f in session.files:
                if f.file_path == rel_path:
                    return f
        return None

    async def delete_file(self, file_id: int) -> RecordingFile | None:
        """删除内存分段跟踪记录，返回被删对象（磁盘文件由调用方处理）。"""
        async with self._lock:
            for session in self._sessions.values():
                for f in session.files:
                    if f.id == file_id:
                        session.files.remove(f)
                        return f
            return None

    async def delete_file_by_path(self, rel_path: str) -> RecordingFile | None:
        async with self._lock:
            for session in self._sessions.values():
                for f in session.files:
                    if f.file_path == rel_path:
                        session.files.remove(f)
                        return f
            return None


store = DataStore()
