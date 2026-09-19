"""共享 httpx 连接池：复用 TCP/TLS 连接，避免每请求新建 AsyncClient。

此前各处（streamget 的 async_req、直链探测、webhook、下载器直连）每次请求都
`async with httpx.AsyncClient(...)` 新建客户端，连接即建即断：旧连接进入
TIME_WAIT 堆积、新连接反复握手，系统连接数持续偏高。改为按
(proxy, verify, http2) 分组的长驻客户端后，同目标主机的请求复用 keepalive
连接，空闲连接 30 秒由连接池自动回收。

约定：
- 客户端不设默认超时（timeout=None），调用方必须逐请求传 timeout，与原行为一致；
- 请求级参数（headers/timeout/follow_redirects/cookies）逐请求传入，互不影响；
- 应用退出时由 lifespan 调用 aclose_all() 统一关闭。
"""

import asyncio

import httpx

# 每个客户端最多保留 20 条空闲 keepalive 连接，空闲 30 秒后自动关闭
_LIMITS = httpx.Limits(max_connections=100, max_keepalive_connections=20, keepalive_expiry=30.0)

_clients: dict[tuple, httpx.AsyncClient] = {}
_lock = asyncio.Lock()


async def get_client(
    proxy: str | None = None, *, verify: bool = False, http2: bool = True
) -> httpx.AsyncClient:
    """取（或创建）与 proxy/verify/http2 匹配的共享客户端。"""
    key = (proxy or "", verify, http2)
    client = _clients.get(key)
    if client is not None:
        return client
    async with _lock:
        client = _clients.get(key)
        if client is None:
            client = httpx.AsyncClient(
                proxy=proxy or None, verify=verify, http2=http2, limits=_LIMITS, timeout=None
            )
            _clients[key] = client
        return client


async def aclose_all() -> None:
    """关闭并清空全部共享客户端（应用退出时调用）。"""
    async with _lock:
        clients = list(_clients.values())
        _clients.clear()
    for client in clients:
        try:
            await client.aclose()
        except Exception:
            pass
