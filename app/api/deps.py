"""API 层公共依赖：可选访问令牌鉴权、app.state 访问。"""

from fastapi import Header, HTTPException, Request

from ..config import config


async def require_token(
    request: Request, authorization: str | None = Header(default=None)
) -> None:
    """未配置 access_token 时不启用鉴权。支持 Header 或 ?token= 查询参数（文件下载用）。"""
    if not config.access_token:
        return
    if authorization == f"Bearer {config.access_token}":
        return
    if request.query_params.get("token") == config.access_token:
        return
    raise HTTPException(status_code=401, detail="未授权：访问令牌缺失或不正确")


def get_state(request: Request):
    return request.app.state
