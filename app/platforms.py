"""平台注册表：从 streamget 动态收集全部平台类，附加显示名与 URL 识别规则。

额外提供一个内置的 `custom` 伪平台：room_url 直接填流地址（m3u8/flv 直链），
不经过 streamget，用于录制任意实时流。
"""

import re
from dataclasses import dataclass

import streamget

QUALITIES = ["OD", "UHD", "HD", "SD", "LD"]


@dataclass(frozen=True)
class PlatformInfo:
    key: str
    name: str
    cls: type | None  # None 表示内置伪平台
    needs_cookie: bool = False
    deprecated: bool = False


DISPLAY_NAMES = {
    "douyin": "抖音", "tiktok": "TikTok", "kwai": "快手", "huya": "虎牙", "douyu": "斗鱼",
    "yy": "YY直播", "bilibili": "B站", "rednote": "小红书", "bigo": "Bigo", "blued": "Blued",
    "soop": "SOOP", "netease": "网易CC", "qiandurebo": "千度热播", "panda": "PandaTV",
    "maoer": "猫耳FM", "look": "Look", "winktv": "WinkTV", "flextv": "FlexTV",
    "popkontv": "PopkonTV", "twitcasting": "TwitCasting", "baidu": "百度直播",
    "weibo": "微博直播", "kugou": "酷狗直播", "twitch": "Twitch", "liveme": "LiveMe",
    "huajiao": "花椒直播", "showroom": "ShowRoom", "acfun": "Acfun", "inke": "映客直播",
    "yinbo": "音播直播", "zhihu": "知乎直播", "chzzk": "CHZZK", "haixiu": "嗨秀直播",
    "vvxq": "VV星球", "yiqilive": "17Live", "langlive": "浪Live", "piaopiao": "飘飘直播",
    "sixroom": "六间房", "lehai": "乐嗨直播", "huamao": "花猫直播", "shopee": "Shopee",
    "youtube": "YouTube", "taobao": "淘宝直播", "jd": "京东直播", "faceit": "Faceit",
    "changliao": "畅聊直播", "lianjie": "连接直播", "laixiu": "来秀直播", "picarto": "Picarto",
    "xindongrebo": "心动热播", "migu": "咪咕直播",
}

# 官方已声明不再维护的平台
DEPRECATED = {"qiandurebo", "winktv", "yinbo", "vvxq", "piaopiao", "migu"}
NEEDS_COOKIE = {"youtube", "taobao"}

# 内置伪平台：直链录制
CUSTOM_KEY = "custom"


def _build() -> dict[str, PlatformInfo]:
    platforms: dict[str, PlatformInfo] = {
        CUSTOM_KEY: PlatformInfo(
            key=CUSTOM_KEY, name="自定义流（直链）", cls=None,
        )
    }
    for name in streamget.__all__:
        if not name.endswith("LiveStream"):
            continue
        cls = getattr(streamget, name)
        key = name[: -len("LiveStream")].lower()
        platforms[key] = PlatformInfo(
            key=key,
            name=DISPLAY_NAMES.get(key, key),
            cls=cls,
            needs_cookie=key in NEEDS_COOKIE,
            deprecated=key in DEPRECATED,
        )
    return platforms


PLATFORMS = _build()

# 常见直播间的 URL 特征（用于添加房间时自动识别平台）
_URL_PATTERNS: list[tuple[str, str]] = [
    ("douyin", r"douyin\.com"),
    ("tiktok", r"tiktok\.com"),
    ("kwai", r"kuaishou\.com"),
    ("huya", r"huya\.com"),
    ("douyu", r"douyu\.com"),
    ("bilibili", r"live\.bilibili\.com|b23\.tv"),
    ("yy", r"(?<![\w.])yy\.com"),
    ("rednote", r"xiaohongshu\.com"),
    ("bigo", r"bigo\.tv"),
    ("soop", r"sooplive\.co\.kr|afreecatv\.com"),
    ("netease", r"cc\.163\.com"),
    ("twitch", r"twitch\.tv"),
    ("youtube", r"youtube\.com|youtu\.be"),
    ("chzzk", r"chzzk\.naver\.com"),
    ("maoer", r"maoer\.fm"),
    ("baidu", r"live\.baidu\.com"),
    ("weibo", r"weibo\.com"),
    ("kugou", r"kugou\.com"),
    ("huajiao", r"huajiao\.com"),
    ("acfun", r"acfun\.cn"),
    ("zhihu", r"zhihu\.com"),
    ("taobao", r"taobao\.com"),
    ("jd", r"jd\.com"),
    ("showroom", r"showroom-live\.com"),
    ("twitcasting", r"twitcasting\.tv"),
    ("yiqilive", r"17live\.co"),
    ("sixroom", r"(?<![\w.])6\.cn"),
    ("inke", r"inke\.cn"),
    ("shopee", r"shopee\."),
    ("panda", r"pandalive\.co"),
    ("flextv", r"flextv\.co\.kr"),
    ("popkontv", r"popkontv\.com"),
    ("winktv", r"winktv\.co\.kr"),
    ("picarto", r"picarto\.tv"),
    ("liveme", r"liveme\.com"),
    ("blued", r"blued\.cn"),
]


def detect_platform(url: str) -> str | None:
    for key, pattern in _URL_PATTERNS:
        if re.search(pattern, url, re.IGNORECASE):
            return key
    return None


def get_platform(key: str) -> PlatformInfo | None:
    return PLATFORMS.get(key)


def list_platforms() -> list[dict]:
    return [
        {
            "key": p.key,
            "name": p.name,
            "needs_cookie": p.needs_cookie,
            "deprecated": p.deprecated,
        }
        for p in sorted(PLATFORMS.values(), key=lambda x: (x.deprecated, x.key == CUSTOM_KEY, x.key))
    ]
