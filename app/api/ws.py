"""WebSocket 实时推送。

连接后先发一次 snapshot（房间列表 + 录制进度），后续推送事件总线上的
room_status / recording_* / log 等事件。鉴权：access_token 设置非空时要求
查询参数 ?token=xxx。
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..core.events import bus
from ..store import store
from .rooms import room_out

router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    token = str(websocket.app.state.settings_svc.get("access_token") or "")
    if token and websocket.query_params.get("token") != token:
        await websocket.close(code=4401)
        return
    await websocket.accept()
    queue = bus.subscribe()
    try:
        snapshot = await _build_snapshot(websocket)
        await websocket.send_json({"type": "snapshot", **snapshot})
        while True:
            event = await queue.get()
            await websocket.send_json(event)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        bus.unsubscribe(queue)


async def _build_snapshot(websocket: WebSocket) -> dict:
    state = websocket.app.state
    rooms = await store.list_rooms()
    return {
        "rooms": [room_out(r, state.manager) for r in rooms],
        "progress": state.manager.progress_snapshot(),
    }
