"""通用工具：时间、文件名清洗、格式化。"""

import re
from datetime import datetime, timezone

# emoji 及装饰符号（跨平台文件名兼容性差，直接去掉）
_EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\U0001F1E6-\U0001F1FF\U00002600-\U000027BF"
    "\U0001F900-\U0001F9FF\U00002700-\U000027BF\u2b00-\u2bff\ufe0f\u200d]"
)
_ILLEGAL_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def utcnow() -> datetime:
    """统一使用无时区的 UTC 时间入库。"""
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


def iso_utc(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc).isoformat()


def sanitize_component(text: str | None, max_len: int = 80) -> str:
    """清洗用于文件路径的片段（主播名/标题/平台名等）。"""
    cleaned = _EMOJI_RE.sub("", text or "")
    cleaned = _ILLEGAL_RE.sub(" ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip().strip(".")
    cleaned = cleaned.strip()
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len].rstrip()
    return cleaned or "unknown"


def human_size(num: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(num) < 1024:
            return f"{num:.1f} {unit}" if unit != "B" else f"{int(num)} B"
        num /= 1024
    return f"{num:.1f} PB"
