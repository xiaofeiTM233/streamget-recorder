"""房间管理 API。"""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select

from ..core.monitor import MonitorError, check_once
from ..db import session_factory
from ..models import Room
from ..platforms import detect_platform, get_platform
from ..schemas import BatchRoomToggle, RoomCreate, RoomUpdate, validate_quality
from ..utils import iso_utc, utcnow
from .deps import get_state

router = APIRouter()


def room_out(room: Room, manager) -> dict:
    info = get_platform(room.platform)
    return {
        "id": room.id,
        "platform": room.platform,
        "platform_name": info.name if info else room.platform,
        "room_url": room.room_url,
        "anchor_name": room.anchor_name,
        "remark": room.remark,
        "quality": room.quality,
        "check_interval": room.check_interval,
        "has_cookie": bool(room.cookie),
        "enabled": room.enabled,
        "status": room.status if room.enabled else "disabled",
        "status_msg": room.status_msg,
        "last_check_at": iso_utc(room.last_check_at),
        "recording": manager.is_recording(room.id),
    }


async def _get_room_or_404(room_id: int) -> Room:
    factory = session_factory()
    async with factory() as s:
        room = await s.get(Room, room_id)
        if room is None:
            raise HTTPException(status_code=404, detail="房间不存在")
        return room


@router.get("")
async def list_rooms(request: Request):
    state = get_state(request)
    factory = session_factory()
    async with factory() as s:
        rooms = (await s.execute(select(Room).order_by(Room.id))).scalars().all()
    return [room_out(r, state.manager) for r in rooms]


@router.post("")
async def create_room(payload: RoomCreate, request: Request):
    state = get_state(request)
    quality = validate_quality(payload.quality)
    platform = payload.platform or detect_platform(payload.room_url)
    if not platform:
        raise HTTPException(status_code=400, detail="无法从 URL 识别平台，请手动选择平台")
    if get_platform(platform) is None:
        raise HTTPException(status_code=400, detail=f"不支持的平台: {platform}")

    factory = session_factory()
    async with factory() as s:
        exists = (
            (await s.execute(select(Room).where(Room.room_url == payload.room_url.strip())))
            .scalars()
            .first()
        )
        if exists is not None:
            raise HTTPException(status_code=400, detail="该房间已存在")
        room = Room(
            platform=platform,
            room_url=payload.room_url.strip(),
            quality=quality or str(state.settings_svc.get("quality")),
            check_interval=payload.check_interval,
            cookie=payload.cookie or "",
            remark=payload.remark or "",
            enabled=payload.enabled,
        )
        s.add(room)
        await s.commit()
        await s.refresh(room)
        snapshot = room_out(room, state.manager)
    await state.scheduler.reload()
    return snapshot


@router.put("/{room_id}")
async def update_room(room_id: int, payload: RoomUpdate, request: Request):
    state = get_state(request)
    # 用"字段是否显式提交"区分 未提供（不修改）与 提交 null（清空，恢复跟随全局）
    provided = payload.model_fields_set
    factory = session_factory()
    async with factory() as s:
        room = await s.get(Room, room_id)
        if room is None:
            raise HTTPException(status_code=404, detail="房间不存在")
        if payload.room_url is not None:
            room.room_url = payload.room_url.strip()
        if "quality" in provided:
            # 显式提交：null/非法清空 = 跟随全局（存储空串，录制时回退全局设置）
            room.quality = validate_quality(payload.quality) if payload.quality else ""
        if "check_interval" in provided:
            room.check_interval = payload.check_interval  # 显式 null = 跟随全局
        if payload.cookie is not None:
            room.cookie = payload.cookie  # 空串 = 删除 Cookie
        if "remark" in provided:
            room.remark = payload.remark or ""
        if payload.enabled is not None:
            room.enabled = payload.enabled
        await s.commit()
        await s.refresh(room)
        snapshot = room_out(room, state.manager)
    await state.scheduler.reload()
    if payload.enabled is False:
        await state.manager.stop(room_id, reason="房间已停用")
    return snapshot


@router.delete("/{room_id}")
async def delete_room(room_id: int, request: Request):
    state = get_state(request)
    recorder = state.manager.get(room_id)
    if recorder is not None:
        # 先优雅停掉录制（≤10s），避免删除后录制任务继续写库
        await recorder.stop("房间已删除")
        await recorder.wait()
    factory = session_factory()
    async with factory() as s:
        room = await s.get(Room, room_id)
        if room is None:
            raise HTTPException(status_code=404, detail="房间不存在")
        await s.delete(room)
        await s.commit()
    await state.scheduler.reload()
    return {"deleted": True}


@router.post("/batch-toggle")
async def batch_toggle(payload: BatchRoomToggle, request: Request):
    state = get_state(request)
    factory = session_factory()
    async with factory() as s:
        rooms = ((await s.execute(select(Room).where(Room.id.in_(payload.ids)))).scalars().all())
        for room in rooms:
            room.enabled = payload.enabled
        await s.commit()
        updated = len(rooms)
    if not payload.enabled:
        for room_id in payload.ids:
            await state.manager.stop(room_id, reason="房间已停用")
    await state.scheduler.reload()
    return {"updated": updated}


@router.post("/check-all")
async def check_all_rooms(request: Request):
    """全部刷新：唤醒所有房间的轮询任务立即重新检测。"""
    state = get_state(request)
    triggered = state.scheduler.trigger_check_all()
    return {"triggered": triggered}


@router.post("/{room_id}/check")
async def check_room_now(room_id: int, request: Request):
    """立即检测一次：开播则直接开始录制。"""
    state = get_state(request)
    room = await _get_room_or_404(room_id)
    if state.manager.is_recording(room_id):
        recorder = state.manager.get(room_id)
        return {"recording": True, "progress": recorder.progress if recorder else {}}
    proxy = str(state.settings_svc.get("proxy_addr") or "") or None
    try:
        check = await check_once(room.platform, room.room_url, room.cookie or None, proxy)
    except MonitorError as exc:
        raise HTTPException(status_code=502, detail=f"检测失败：{exc}")
    factory = session_factory()
    async with factory() as s:
        db_room = await s.get(Room, room_id)
        if db_room is not None:
            if check.anchor_name and check.anchor_name != db_room.anchor_name:
                db_room.anchor_name = check.anchor_name
            db_room.last_check_at = utcnow()
            await s.commit()
    started = False
    if check.is_live and room.enabled:
        recorder = await state.manager.start(room, check)
        started = recorder is not None  # 并发上限已满时为 False，调度器稍后会自动重试
    return {
        "is_live": check.is_live,
        "started": started,
        "anchor_name": check.anchor_name,
        "title": check.title,
    }


@router.post("/{room_id}/stop")
async def stop_room(room_id: int, request: Request):
    state = get_state(request)
    stopped = await state.manager.stop(room_id)
    return {"stopped": stopped}
