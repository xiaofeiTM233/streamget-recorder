"""streamget 封装：房间开播检测 + 流地址解析。

streamget 的网络层（async_req）在出错时不抛异常而是把异常文本/空串当响应返回，
平台代码随后 json.loads 必然报 JSONDecodeError，真实原因（URL、实际返回内容）
在库内被丢弃。因此这里做了两件事：
1. _instrument_streamget_requests：用 http_pool 共享连接池整体替换各平台的
   async_req（库内原实现每次请求新建 AsyncClient，连接即建即断导致系统连接数
   偏高），并在源头把可疑返回记入日志、额外探测一次 HTTP 状态码；
2. MonitorError 直接附上原始响应内容与状态码，方便定位。
"""

import re
import sys
import urllib.parse
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from loguru import logger

from ..platforms import CUSTOM_KEY, get_platform
from . import http_pool


class MonitorError(Exception):
    """开播检测/地址解析失败。"""


# 本次检测（task 上下文）内捕获的原始响应：{url, text}，JSONDecodeError 时直接附进错误消息
_bad_responses: ContextVar[list[dict]] = ContextVar("recorder_bad_responses", default=None)


# ---------- 自建反代端点改写 ----------
# 部分平台接口可以走用户自建的反代（绕开公共端点的风控）。命中下表 host 的请求整体替换为
# 设置里配的完整端点 URL；代理照常按全局 proxy_addr 走，如何路由由用户自己决定。
_ENDPOINT_REWRITES: dict[str, str] = {"gql.twitch.tv": "gql_endpoint"}
_settings_ref: object | None = None


def bind_settings(settings) -> None:
    """注入设置服务，供出站请求改写读取最新配置。仅启动时调用一次。"""
    global _settings_ref
    _settings_ref = settings


def _apply_endpoint_rewrite(url: str) -> str:
    """把命中改写表的请求换成自建反代端点；未配置或不命中则原样返回。"""
    if _settings_ref is None:
        return url
    key = _ENDPOINT_REWRITES.get(urllib.parse.urlsplit(url).netloc.lower())
    if key is None:
        return url
    target = str(_settings_ref.get(key) or "").strip()  # type: ignore[attr-defined]
    return target or url


@dataclass
class CheckResult:
    is_live: bool
    anchor_name: str = ""
    title: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


class RoomMonitor:
    """单个房间的检测器。每次检测/解析独立发起请求，无跨请求状态。"""

    def __init__(self, platform: str, cookies: str | None = None, proxy_addr: str | None = None):
        self.platform = platform
        self._cookies = cookies or None
        self._proxy_addr = proxy_addr or None
        self._room_url: str | None = None
        if platform != CUSTOM_KEY:
            info = get_platform(platform)
            if info is None or info.cls is None:
                raise MonitorError(f"不支持的平台: {platform}")
            self._live = info.cls(proxy_addr=self._proxy_addr, cookies=self._cookies)

    def _explain_error(self, exc: Exception) -> str:
        """生成失败原因：只展示接口原始响应内容与状态码。"""
        name = type(exc).__name__
        detail = str(exc).strip() or repr(exc)
        msg = f"[{self.platform}] {name}: {detail}"
        # JSON 解析失败 = 接口返回了空串/错误文本/风控页，把原始内容与状态码附上
        if "JSONDecodeError" in name or "Expecting value" in detail:
            bad = _bad_responses.get() or []
            if bad:
                parts = []
                for b in bad[:3]:
                    status = b.get("status")
                    sc = f"，状态码 {status}" if status is not None else ""
                    parts.append(f"原始响应[{b['url'].split('?')[0]}] → {b['text']!r}{sc}")
                msg += " —— " + "；".join(parts)
            else:
                msg += " —— 平台接口返回了空内容或错误页（未捕获到原始内容，详见服务日志）"
        return msg

    async def check(self, room_url: str) -> CheckResult:
        self._room_url = room_url
        _bad_responses.set([])  # 每次检测独立收集原始响应，避免串到其他房间
        if self.platform == CUSTOM_KEY:
            return CheckResult(is_live=await _probe_stream_url(room_url), anchor_name="直链", title=room_url)

        try:
            data = await self._live.fetch_web_stream_data(room_url, process_data=True)
        except Exception as exc:
            raise MonitorError(self._explain_error(exc)) from exc
        # 部分平台多线路时返回列表
        if isinstance(data, list):
            data = data[0] if data else None
        if not isinstance(data, dict):
            snippet = str(data)[:120] if data is not None else "None"
            raise MonitorError(f"接口返回异常: {snippet}")
        # 库内键名不统一：B 站用 live_status，其余平台用 is_live
        raw_is_live = data.get("is_live", data.get("live_status"))
        if raw_is_live is None:
            # 抖音/TikTok 等平台返回的是原始接口数据，不含 is_live/live_status
            # （抖音用 status：2=直播中，4=未开播）。与 StreamCap 一致：交给
            # fetch_stream_url 按平台自身逻辑判定开播状态。
            try:
                stream = await self._live.fetch_stream_url(data, video_quality="OD")
            except Exception as exc:
                raise MonitorError(self._explain_error(exc)) from exc
            if isinstance(stream, dict):
                raw_is_live = bool(stream.get("is_live"))
            else:
                raw_is_live = bool(getattr(stream, "is_live", False))
        return CheckResult(
            is_live=bool(raw_is_live),
            anchor_name=str(data.get("anchor_name") or ""),
            title=str(data.get("title") or ""),
            raw=data,
        )

    async def resolve_stream(self, check: CheckResult, quality: str):
        """把开播数据解析为可录制的流对象（StreamData）。"""
        _bad_responses.set([])  # 解析阶段独立收集，只归属本次解析的失败
        # “仅音频”不是清晰度：拉流仍按默认清晰度，录制端丢弃视频轨
        if quality == "audio":
            quality = "OD"
        if self.platform == CUSTOM_KEY:
            from streamget import StreamData

            url = self._room_url or check.title
            return StreamData(
                platform="custom",
                anchor_name=check.anchor_name,
                is_live=True,
                title=check.title,
                quality=quality,
                record_url=url,
            )
        try:
            stream = await self._live.fetch_stream_url(check.raw, video_quality=quality)
        except Exception as exc:
            raise MonitorError(self._explain_error(exc)) from exc
        if isinstance(stream, dict):
            from streamget.data import wrap_stream

            stream = wrap_stream(stream)
        if not getattr(stream, "record_url", None):
            stream.record_url = getattr(stream, "m3u8_url", None) or getattr(stream, "flv_url", None)
        if not getattr(stream, "record_url", None):
            raise MonitorError("未解析到可用的流地址")
        return stream


async def _probe_stream_url(url: str) -> bool:
    """直链平台探测：m3u8 含 ENDLIST 视为点播（未开播），可达即视为在线。"""
    try:
        client = await http_pool.get_client(http2=False)
        async with client.stream("GET", url, follow_redirects=True, timeout=8) as resp:
            if resp.status_code != 200:
                return False
            if ".m3u8" in url.split("?")[0]:
                text = (await resp.aread())[:65536].decode("utf-8", "replace")
                return "#EXT-X-ENDLIST" not in text
            await resp.aread()
            return True
    except Exception as exc:
        logger.debug("直链探测失败 {}: {}", url, exc)
        return False


async def check_once(platform: str, room_url: str, cookies: str | None = None,
                     proxy_addr: str | None = None) -> CheckResult:
    """一次性检测（API 立即检测用）。"""
    monitor = RoomMonitor(platform, cookies=cookies, proxy_addr=proxy_addr)
    return await monitor.check(room_url)


# ---------- streamget 网络层诊断 ----------


def _is_suspicious(result: object) -> bool:
    """非 JSON 形态（{、"[/[ 开头非系统错误）或空内容，json.loads 必然失败。"""
    if not isinstance(result, str):
        return False
    text = result.strip()
    if not text:
        return True  # 空响应
    first = text[0]
    # JSON 形态（{ " 以及普通数组）视为正常内容，交由平台自身解析
    if first in '{"' or (first == "[" and not re.match(r"\[\s*(Errno|WinError)", text)):
        return False
    return True  # 错误文本 / 风控页 / 系统错误


def _suspicious_snippet(result: str) -> str:
    text = result.strip()
    return text[:200] or "（空响应，0 字节）"


async def _probe_status(url: str, proxy_addr: str | None) -> int | None:
    """轻量探测一次 HTTP 状态码（HEAD，不下载 body）。空响应/错误页也能拿到状态码。"""
    try:
        client = await http_pool.get_client(proxy_addr, http2=False)
        response = await client.head(url, follow_redirects=True, timeout=6)
        return response.status_code
    except Exception:
        return None  # 网络不通/超时，无状态码


def _instrument_streamget_requests() -> int:
    """用共享连接池整体替换 streamget 各平台引用的 async_req，并装上诊断日志。

    库内原实现每次请求都新建 httpx.AsyncClient（连接即建即断，TLS 握手频繁，
    TIME_WAIT 堆积导致系统连接数升高）。替换为 http_pool 共享客户端实现，
    语义与原实现保持一致：
    - 网络异常不抛出，把异常文本当响应返回（平台代码的 json.loads 失败路径依赖此行为）；
    - 不持久化 Cookie（原实现每次新建客户端，Cookie 逐请求隔离）；
    - 可疑响应（空串/错误页）记入日志并探测一次状态码，暂存进本次检测上下文。
    """
    import streamget.requests.async_http as http_mod
    from streamget.utils import handle_proxy_addr

    if getattr(http_mod.async_req, "_recorder_pooled", False):
        return 0  # 已替换，防重复

    original = http_mod.async_req

    async def pooled_async_req(
        url: str,
        proxy_addr: str | None = None,
        headers: dict | None = None,
        data: dict | bytes | None = None,
        json_data: dict | list | None = None,
        timeout: int = 20,
        redirect_url: bool = False,
        return_cookies: bool = False,
        include_cookies: bool = False,
        verify: bool = False,
        http2: bool = True,
    ):
        if headers is None:
            headers = {}
        url = _apply_endpoint_rewrite(url)
        client = None
        try:
            proxy = handle_proxy_addr(proxy_addr)
            client = await http_pool.get_client(proxy, verify=verify, http2=http2)
            if data or json_data:
                response = await client.post(url, data=data, json=json_data, headers=headers, timeout=timeout)
            else:
                response = await client.get(url, headers=headers, follow_redirects=True, timeout=timeout)
            if redirect_url:
                result = str(response.url)
            elif return_cookies:
                cookies_dict = dict(response.cookies.items())
                result = (response.text, cookies_dict) if include_cookies else cookies_dict
            else:
                result = response.text
        except Exception as e:
            result = str(e)
        else:
            if client is not None:
                client.cookies.clear()  # 不持久化 Cookie，保持原实现逐请求隔离的语义

        # ---- 诊断：可疑响应记日志 + 探测状态码，暂存进本次检测上下文 ----
        if _is_suspicious(result):
            status = await _probe_status(url, proxy_addr)
            snippet = _suspicious_snippet(result)
            sc = f"{status}" if status is not None else "-"
            logger.warning("平台接口返回异常内容，状态码 {}：{} → {!r}", sc, url, snippet)
            bad = _bad_responses.get()
            if bad is not None:
                bad.append({"url": url, "text": snippet, "status": status})
        return result

    pooled_async_req._recorder_pooled = True  # type: ignore[attr-defined]

    # get_response_status 同样每次新建客户端，一并池化（语义一致：失败返回 False）
    original_grs = getattr(http_mod, "get_response_status", None)

    async def pooled_get_response_status(
        url: str,
        proxy_addr: str | None = None,
        headers: dict | None = None,
        timeout: int = 10,
        verify: bool = False,
        http2: bool = True,
    ) -> int:
        try:
            proxy = handle_proxy_addr(proxy_addr)
            client = await http_pool.get_client(proxy, verify=verify, http2=http2)
            response = await client.head(url, headers=headers, follow_redirects=True, timeout=timeout)
            return response.status_code
        except Exception as exc:
            logger.debug("HEAD 探测失败 {}: {}", url, exc)
        return False

    pooled_get_response_status._recorder_pooled = True  # type: ignore[attr-defined]
    http_mod.async_req = pooled_async_req
    if original_grs is not None:
        http_mod.get_response_status = pooled_get_response_status
    patched = 0
    for name, mod in list(sys.modules.items()):
        # 平台模块以 from-import 方式持有引用的，逐个替换
        if not name.startswith("streamget.platforms"):
            continue
        if getattr(mod, "async_req", None) is original:
            mod.async_req = pooled_async_req
            patched += 1
        if original_grs is not None and getattr(mod, "get_response_status", None) is original_grs:
            mod.get_response_status = pooled_get_response_status
            patched += 1
    return patched


_instrument_streamget_requests()
