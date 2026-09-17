"""录制文件 API：把录制目录当普通文件夹提供浏览/搜索/删除/下载。

录制记录不落库：文件列表即磁盘目录内容。
"""

import os
import shutil
from contextlib import suppress
from datetime import datetime, timezone
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse
from loguru import logger
from send2trash import send2trash

from ..store import store
from ..utils import iso_utc
from .deps import get_state

router = APIRouter()


def _safe_rel_path(path: str) -> str:
    """校验并规范化相对路径（拒绝 .. / 绝对路径 / 空路径）。"""
    parts = [p for p in path.replace("\\", "/").split("/") if p and p not in (".", "..")]
    if not parts:
        raise HTTPException(status_code=400, detail="路径不能为空")
    return "/".join(parts)


def _resolve_full(request_root, rel: str):
    full = (request_root / rel).resolve()
    if request_root.resolve() not in full.parents and full != request_root.resolve():
        raise HTTPException(status_code=400, detail="路径越界")
    return full


def _file_entry(rel: str, size: int, mtime: float) -> dict:
    dt = datetime.fromtimestamp(mtime, tz=timezone.utc).replace(tzinfo=None, microsecond=0)
    return {
        "file_path": rel,
        "filename": rel.rsplit("/", 1)[-1],
        "size": size,
        "modified_time": iso_utc(dt),
        "download_url": f"/api/recordings/files/download?path={quote(rel)}",
    }


def _walk_files(root):
    """遍历录制根目录，产出 (rel_path, size, mtime)。"""
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            full = os.path.join(dirpath, name)
            try:
                st = os.stat(full)
            except OSError:
                continue
            rel = os.path.relpath(full, root).replace("\\", "/")
            yield rel, st.st_size, st.st_mtime


@router.get("/browse")
async def browse_recordings(
    request: Request,
    path: str = Query("", description="文件夹路径（相对录制根目录，/ 分隔）"),
    search: str = Query("", description="按文件/文件夹名跨目录搜索"),
):
    """资源管理器式浏览：返回当前层级的子文件夹（含文件数/总大小）与文件。"""
    state = get_state(request)
    root = state.settings_svc.record_root()
    if search.strip():
        key = search.strip().lower()
        rows = [
            _file_entry(rel, size, mtime)
            for rel, size, mtime in _walk_files(root)
            if key in rel.lower()  # 匹配完整相对路径 = 文件名 + 所在文件夹名
        ]
        rows.sort(key=lambda x: x["modified_time"] or "", reverse=True)
        return {
            "path": "",
            "search": search.strip(),
            "folders": [],
            "files": rows[:500],
        }

    rel_dir = _safe_rel_path(path) if path.strip() else ""
    full_dir = root / rel_dir if rel_dir else root
    if not full_dir.is_dir():
        raise HTTPException(status_code=404, detail="文件夹不存在")

    folders: list[dict] = []
    files: list[dict] = []
    for entry in os.scandir(full_dir):
        rel = f"{rel_dir}/{entry.name}" if rel_dir else entry.name
        if entry.is_dir(follow_symlinks=False):
            file_count = 0
            size = 0
            for _sub_rel, sub_size, _mtime in _walk_files(entry.path):
                file_count += 1
                size += sub_size
            folders.append({"name": entry.name, "file_count": file_count, "size": size})
        elif entry.is_file(follow_symlinks=False):
            st = entry.stat()
            files.append(_file_entry(rel.replace("\\", "/"), st.st_size, st.st_mtime))
    return {
        "path": rel_dir,
        "search": "",
        "folders": sorted(folders, key=lambda d: d["name"]),
        "files": sorted(files, key=lambda x: x["modified_time"] or "", reverse=True),
    }


@router.delete("/files")
async def delete_recording_entry(
    request: Request,
    path: str = Query(..., description="文件或文件夹相对路径（/ 分隔）"),
):
    """删除文件或整个文件夹（移动到系统回收站；回收站不可用时退回直接删除）。"""
    state = get_state(request)
    root = state.settings_svc.record_root()
    rel = _safe_rel_path(path)
    full = _resolve_full(root, rel)
    if full.is_file():
        tracked = await store.get_file_by_path(rel)
        if tracked is not None and tracked.status == "recording":
            raise HTTPException(status_code=409, detail="文件正在录制中，无法删除")
    elif full.is_dir():
        # 文件夹内包含正在录制的文件时拒绝删除
        for sub_rel, _size, _mtime in _walk_files(full):
            tracked = await store.get_file_by_path(sub_rel)
            if tracked is not None and tracked.status == "recording":
                raise HTTPException(status_code=409, detail="文件夹内包含正在录制的文件，无法删除")
    else:
        raise HTTPException(status_code=404, detail="文件或文件夹不存在")
    try:
        send2trash(str(full))
    except Exception as exc:
        logger.warning("移动到回收站失败（{}），退回直接删除: {}", exc, full)
        if full.is_dir():
            shutil.rmtree(full, ignore_errors=True)
        else:
            with suppress(OSError):
                full.unlink()
    await store.delete_file_by_path(rel)
    return {"deleted": True}


@router.get("/files/download")
async def download_recording_file(
    request: Request,
    path: str = Query(..., description="文件相对路径（/ 分隔）"),
):
    state = get_state(request)
    root = state.settings_svc.record_root()
    rel = _safe_rel_path(path)
    full = _resolve_full(root, rel)
    if not full.is_file():
        raise HTTPException(status_code=404, detail="文件已不在磁盘上")
    return FileResponse(full, filename=full.name)
