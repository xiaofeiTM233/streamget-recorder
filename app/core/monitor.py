"""streamget 封装：房间开播检测 + 流地址解析。

streamget 的网络层在出错时不抛异常而是把异常文本当响应返回，因此这里对
返回值做严格校验，统一包装成 MonitorError 抛出，避免异常文本污染上层逻辑。
"""

import httpx
from dataclasses import dataclass, field
from typing import Any
from loguru import logger

from ..platforms import CUSTOM_KEY, get_platform


class MonitorError(Exception):
    """开播检测/地址解析失败。"""


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

    async def check(self, room_url: str) -> CheckResult:
        self._room_url = room_url
        if self.platform == CUSTOM_KEY:
            return CheckResult(is_live=await _probe_stream_url(room_url), anchor_name="直链", title=room_url)

        try:
            data = await self._live.fetch_web_stream_data(room_url, process_data=True)
        except Exception as exc:
            raise MonitorError(f"{type(exc).__name__}: {exc}") from exc
        # 部分平台多线路时返回列表
        if isinstance(data, list):
            data = data[0] if data else None
        if not isinstance(data, dict):
            snippet = str(data)[:120] if data is not None else "None"
            raise MonitorError(f"接口返回异常: {snippet}")
        # 库内键名不统一：B 站用 live_status，其余平台用 is_live
        raw_is_live = data.get("is_live", data.get("live_status"))
        if raw_is_live is None:
            raise MonitorError(f"接口缺少开播状态字段: {str(data)[:120]}")
        return CheckResult(
            is_live=bool(raw_is_live),
            anchor_name=str(data.get("anchor_name") or ""),
            title=str(data.get("title") or ""),
            raw=data,
        )

    async def resolve_stream(self, check: CheckResult, quality: str):
        """把开播数据解析为可录制的流对象（StreamData）。"""
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
            raise MonitorError(f"{type(exc).__name__}: {exc}") from exc
        if isinstance(stream, dict):
            from streamget import wrap_stream

            stream = wrap_stream(stream)
        if not getattr(stream, "record_url", None):
            stream.record_url = getattr(stream, "m3u8_url", None) or getattr(stream, "flv_url", None)
        if not getattr(stream, "record_url", None):
            raise MonitorError("未解析到可用的流地址")
        return stream


async def _probe_stream_url(url: str) -> bool:
    """直链平台探测：m3u8 含 ENDLIST 视为点播（未开播），可达即视为在线。"""
    try:
        async with httpx.AsyncClient(timeout=8, verify=False, follow_redirects=True) as client:
            async with client.stream("GET", url) as resp:
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
