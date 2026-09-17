"""运行时可变设置（JSON 文件存储，前端可改，引擎实时读取）。

默认值同时定义了键与类型，get() 按默认值类型做转换。
"""

import asyncio
import json
import os
from pathlib import Path

from loguru import logger

from .config import config

DEFAULTS: dict[str, object] = {
    "check_interval": 60,        # 循环时间（秒）：开播检测间隔
    "end_confirm_delay": 30,     # 下播确认延迟（秒）：检测到下播后等待再次确认，防瞬时断流误收场，0 = 立即结束
    "max_consecutive_failures": 10,  # 连续检测/录制失败上限：达到后结束本次会话交还轮询
    "retention_days": 0,         # 录制文件保留天数：超期自动清理（文件+记录，每小时检查一次），0 = 永久保留
    "webhook_url": "",           # 事件通知地址（POST JSON）：录制会话开始/结束时回调，留空不启用
    "quality": "OD",             # 录制清晰度：OD | UHD | HD | SD | LD | audio（仅音频）
    "output_format": "mp4",      # 录制格式（容器）：mp4 | flv
    "audio_format": "auto",      # 音频格式：auto 自动 | aac | m4a | mp3；录视频时 auto=跟随源、aac/mp3=转码，仅音频时 auto/m4a=M4A、aac=裸流、mp3=转码
    "stream_type": "auto",       # 拉流协议优先级：auto = 库自动 | flv | hls
    "segment_enabled": False,    # 分段录制是否开启
    "segment_seconds": 1800,     # 视频分段时间（秒）
    "max_session_hours": 0,     # 单场直播最大录制时长（小时），0 = 不限制
    "min_free_disk_gb": 0.0,     # 录制空间剩余阈值（GB），不足则暂停录制，0 = 不检查
    "force_https": False,        # 强制启用 https 录制（http 流地址改写为 https）
    "flv_direct_download": False,  # FLV 源使用下载器直连录制（httpx 流式下载，低延迟；不支持 ffmpeg_extra_args）
    "proxy_record_platforms": "tiktok, soop, panda, winktv, flextv, popkontv, twitch, liveme, showroom, chzzk, shopee, youtube, lang",  # 默认使用代理录制的平台（逗号分隔的 key，FFmpeg 拉流走全局代理）
    "auto_convert_mp4": False,   # 录制完成后转为 mp4（输出格式为 flv 时生效）
    "delete_original_after_convert": False,  # 追加格式后删除原文件
    "write_time_subtitle": False,  # 生成时间字幕文件（每秒一条 SRT，正文为当时时间）
    "run_script_after": False,   # 录制完成后执行自定义脚本
    "script_after_cmd": "",      # 自定义脚本执行命令，占位符 {file} {filename} {title} {anchor} {platform} {session_id}
    "max_concurrent": 0,        # 全局最大并发录制数，0 = 不限制
    "max_concurrent_per_platform": 0,  # 平台最大并发录制数，0 = 不限制
    "record_dir": "",            # 录制保存目录，空 = data/recordings
    "ffmpeg_path": "ffmpeg",     # FFmpeg 可执行文件路径
    "ffmpeg_extra_args": "",     # FFmpeg 额外输出参数（追加在输出选项后），空 = 无
    "proxy_addr": "",            # 全局代理（检测与解析用；配合 proxy_record_platforms 也用于拉流），空 = 不使用
    "platform_credentials": "[]",  # 平台登录凭证 JSON 数组：[{"platform":"x","cookie":""}]，房间未配 Cookie 时的兜底（streamget 仅支持 Cookie 登录）
    "reconnect_backoff_max": 300,  # 断流/失败重试的最大退避（秒）
    "file_template": "{platform}/{anchor}/{datetime}_{title}",
}


class SettingsService:
    """设置存储：data/settings.json。读写走内存缓存，写入原子替换。"""

    def __init__(self) -> None:
        self._cache: dict[str, object] = {}
        self._lock = asyncio.Lock()
        self._path: Path = config.data_dir / "settings.json"

    async def load(self) -> None:
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self._migrate_audio_format(data)
                    self._cache = data
                    return
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("设置文件损坏，将重建：{}", exc)
        # JSON 不存在或损坏：从默认值重建
        self._cache = {}
        self._persist()

    @staticmethod
    def _migrate_audio_format(data: dict) -> None:
        """旧版 audio_format(m4a/aac/mp3/copy) + audio_track_format 合并为统一 audio_format(auto/aac/m4a/mp3)。"""
        fmt = data.get("audio_format")
        track = data.pop("audio_track_format", None)
        if fmt in ("auto", "aac", "m4a", "mp3"):
            # m4a 新旧语义在输出上等价；但旧库附带视频音频轨偏好时以偏好为准
            if fmt == "m4a" and track in ("mp3", "aac"):
                data["audio_format"] = track
            return
        if track in ("mp3", "aac"):  # 以旧视频音频轨设置为准
            data["audio_format"] = track
        elif fmt == "mp3":  # 旧"仅音频转 MP3"→ 统一转 MP3
            data["audio_format"] = "mp3"
        else:  # copy/缺失 → 自动
            data["audio_format"] = "auto"

    def get(self, key: str):
        if key not in DEFAULTS:
            raise KeyError(f"未知设置项: {key}")
        raw = self._cache.get(key)
        if raw is None or raw == "":
            # 空字符串按类型回退默认值（int/bool 无法解析空串）
            return DEFAULTS[key]
        default = DEFAULTS[key]
        try:
            if isinstance(default, bool):
                return raw if isinstance(raw, bool) else str(raw).lower() in ("1", "true", "yes")
            if isinstance(default, int):
                return int(float(raw))
            if isinstance(default, float):
                return float(raw)
            return str(raw)
        except (ValueError, TypeError):
            logger.warning("设置项 {} 值非法: {!r}，回退默认值", key, raw)
            return default

    def all(self) -> dict[str, object]:
        return {key: self.get(key) for key in DEFAULTS}

    async def set_many(self, updates: dict[str, object]) -> None:
        unknown = set(updates) - set(DEFAULTS)
        if unknown:
            raise ValueError(f"未知设置项: {', '.join(sorted(unknown))}")
        async with self._lock:
            self._cache.update({k: v for k, v in updates.items() if v is not None})
            self._persist()

    def _persist(self) -> None:
        """写 JSON（临时文件 + 原子替换，避免写一半损坏）。"""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(self._cache, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(tmp, self._path)

    def record_root(self) -> Path:
        """录制文件根目录：设置了绝对路径用之，否则相对 data_dir。"""
        custom = str(self.get("record_dir") or "")
        if custom:
            path = Path(custom)
            return path if path.is_absolute() else config.data_dir / path
        return config.data_dir / "recordings"
