"""全局设置 API。"""

from fastapi import APIRouter, HTTPException, Request

from .deps import get_state

router = APIRouter()


def _settings_payload(state) -> dict:
    return {
        "settings": state.settings_svc.all(),
        "record_dir": str(state.settings_svc.record_root()),
    }


@router.get("")
async def get_settings(request: Request):
    return _settings_payload(get_state(request))


@router.put("")
async def update_settings(request: Request, payload: dict):
    state = get_state(request)
    try:
        await state.settings_svc.set_many(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"设置值非法: {exc}")
    return _settings_payload(state)
