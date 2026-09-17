"""录制记录 API：会话/分段文件查询、删除、下载。"""

from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from ..db import session_factory
from ..models import RecordingFile, RecordingSession
from ..platforms import get_platform
from ..utils import iso_utc
from .deps import get_state

router = APIRouter()


def _file_out(f: RecordingFile) -> dict:
    return {
        "id": f.id,
        "session_id": f.session_id,
        "file_path": f.file_path,
        "filename": f.file_path.rsplit("/", 1)[-1],
        "size": f.size,
        "duration": f.duration,
        "start_time": iso_utc(f.start_time),
        "end_time": iso_utc(f.end_time),
        "status": f.status,
        "download_url": f"/api/recordings/files/{f.id}/download",
    }


def _browse_file(f: RecordingFile, sess: RecordingSession) -> dict:
    """浏览模式的文件条目（带主播/标题，便于跨目录搜索展示）。"""
    out = _file_out(f)
    out["anchor_name"] = sess.anchor_name or ""
    out["title"] = sess.title or ""
    return out


def _session_out(s: RecordingSession) -> dict:
    info = get_platform(s.platform)
    return {
        "id": s.id,
        "room_id": s.room_id,
        "platform": s.platform,
        "platform_name": info.name if info else s.platform,
        "anchor_name": s.anchor_name,
        "title": s.title,
        "quality": s.quality,
        "start_time": iso_utc(s.start_time),
        "end_time": iso_utc(s.end_time),
        "status": s.status,
        "total_size": sum(f.size for f in s.files),
        "total_duration": round(sum(f.duration for f in s.files), 1),
        "files": [_file_out(f) for f in s.files],
    }


@router.get("")
async def list_recordings(
    request: Request,
    room_id: int | None = None,
    anchor: str | None = None,
    start_date: str | None = Query(None, description="YYYY-MM-DD（含）"),
    end_date: str | None = Query(None, description="YYYY-MM-DD（含）"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    factory = session_factory()
    async with factory() as s:
        stmt = (
            select(RecordingSession)
            .options(selectinload(RecordingSession.files))
            .order_by(RecordingSession.start_time.desc())
        )
        count_stmt = select(func.count()).select_from(RecordingSession)
        if room_id is not None:
            stmt = stmt.where(RecordingSession.room_id == room_id)
            count_stmt = count_stmt.where(RecordingSession.room_id == room_id)
        if anchor:
            like = f"%{anchor}%"
            stmt = stmt.where(RecordingSession.anchor_name.like(like))
            count_stmt = count_stmt.where(RecordingSession.anchor_name.like(like))
        try:
            if start_date:
                dt = datetime.fromisoformat(start_date)
                stmt = stmt.where(RecordingSession.start_time >= dt)
                count_stmt = count_stmt.where(RecordingSession.start_time >= dt)
            if end_date:
                dt_end = datetime.fromisoformat(end_date) + timedelta(days=1)
                stmt = stmt.where(RecordingSession.start_time < dt_end)
                count_stmt = count_stmt.where(RecordingSession.start_time < dt_end)
        except ValueError:
            raise HTTPException(status_code=400, detail="日期格式应为 YYYY-MM-DD")

        total = (await s.execute(count_stmt)).scalar() or 0
        rows = (
            (await s.execute(stmt.offset((page - 1) * page_size).limit(page_size)))
            .scalars()
            .unique()
            .all()
        )
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [_session_out(r) for r in rows],
    }


@router.get("/browse")
async def browse_recordings(
    request: Request,
    path: str = Query("", description="文件夹路径（相对录制根目录，/ 分隔）"),
    search: str = Query("", description="按文件名/主播/标题跨目录搜索"),
):
    """资源管理器式浏览：返回当前层级的子文件夹（含文件数/总大小）与文件。"""
    parts = [p for p in path.replace("\\", "/").split("/") if p and p not in (".", "..")]
    norm = "/".join(parts)
    prefix = norm + "/" if norm else ""
    factory = session_factory()
    async with factory() as s:
        if search.strip():
            like = f"%{search.strip()}%"
            rows = (
                await s.execute(
                    select(RecordingFile, RecordingSession)
                    .join(RecordingSession, RecordingFile.session_id == RecordingSession.id)
                    .where(
                        or_(
                            RecordingFile.file_path.like(like),
                            RecordingSession.anchor_name.like(like),
                            RecordingSession.title.like(like),
                        )
                    )
                    .order_by(RecordingFile.start_time.desc())
                    .limit(500)
                )
            ).all()
            return {
                "path": "",
                "search": search.strip(),
                "folders": [],
                "files": [_browse_file(f, sess) for f, sess in rows],
            }
        # 路径需转义 LIKE 通配符（文件夹名可能含 % _ 等字符）
        escaped = norm.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") if norm else ""
        pattern = escaped + "/%" if escaped else "%"
        rows = (
            await s.execute(
                select(RecordingFile, RecordingSession)
                .join(RecordingSession, RecordingFile.session_id == RecordingSession.id)
                .where(RecordingFile.file_path.like(pattern, escape="\\"))
                .order_by(RecordingFile.file_path)
            )
        ).all()
    folders: dict[str, dict] = {}
    files: list[dict] = []
    for f, sess in rows:
        rest = f.file_path[len(prefix):] if prefix else f.file_path
        if "/" in rest:
            name = rest.split("/", 1)[0]
            entry = folders.setdefault(name, {"name": name, "file_count": 0, "size": 0})
            entry["file_count"] += 1
            entry["size"] += f.size or 0
        else:
            files.append(_browse_file(f, sess))
    return {
        "path": norm,
        "search": "",
        "folders": sorted(folders.values(), key=lambda d: d["name"]),
        "files": sorted(files, key=lambda x: x["start_time"] or "", reverse=True),
    }


@router.delete("/files/{file_id}")
async def delete_recording_file(file_id: int, request: Request, delete_disk: bool = True):
    state = get_state(request)
    factory = session_factory()
    async with factory() as s:
        row = await s.get(RecordingFile, file_id)
        if row is None:
            raise HTTPException(status_code=404, detail="文件不存在")
        path = state.settings_svc.record_root() / row.file_path
        await s.delete(row)
        await s.commit()
    if delete_disk:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
    return {"deleted": True}


@router.get("/files/{file_id}/download")
async def download_recording_file(file_id: int, request: Request):
    state = get_state(request)
    factory = session_factory()
    async with factory() as s:
        row = await s.get(RecordingFile, file_id)
    if row is None:
        raise HTTPException(status_code=404, detail="文件不存在")
    path = state.settings_svc.record_root() / row.file_path
    if not path.is_file():
        raise HTTPException(status_code=404, detail="文件已不在磁盘上")
    return FileResponse(path, filename=path.name)
