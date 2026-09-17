"""API 层公共依赖：可选访问令牌鉴权、app.state 访问。"""

from fastapi import Header, HTTPException, Request


async def require_token(
    request: Request, authorization: str | None = Header(default=None)
) -> None:
    """access_token 设置为空时不启用鉴权。支持 Header 或 ?token= 查询参数（文件下载用）。"""
    token = str(request.app.state.settings_svc.get("access_token") or "")
    if not token:
        return
    if authorization == f"Bearer {token}":
        return
    if request.query_params.get("token") == token:
        return
    raise HTTPException(status_code=401, detail="未授权：访问令牌缺失或不正确")


def get_state(request: Request):
    return request.app.state
