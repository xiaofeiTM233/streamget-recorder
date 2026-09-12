"""单路录制会话。

生命周期：开播检测 → 解析新地址 → FFmpeg 录一段（一个分段文件）→
再检测（地址会过期，绝不复用）→ 循环，直到下播 / 手动停止 / 连续失败超限。
"""

import asyncio
import contextlib
import re
import time
import urllib.parse
from pathlib import Path

from loguru import logger
from sqlalchemy import select

from ..db import session_factory
from ..models import RecordingFile, RecordingSession, Room
from ..settings_service import SettingsService
from ..utils import sanitize_component, utcnow
from .events import bus
from .monitor import CheckResult, MonitorError, RoomMonitor

FFMPEG_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
)
_TIME_RE = re.compile(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)")
_BITRATE_RE = re.compile(r"bitrate=\s*([\d.]+)\s*([kmg]?)bits/s")
_MAX_CONSECUTIVE_FAILURES = 10  # 连续失败上限：结束后交还轮询调度器处理
_GRACEFUL_STOP_TIMEOUT = 10.0  # 等 ffmpeg 收到 'q' 后自行收尾的秒数


class Recorder:
    def __init__(self, room: Room, check: CheckResult, settings: SettingsService):
        self.room_id = room.id
        self._room_url = room.room_url
        self._room_quality = room.quality
        self._platform = room.platform
        self._check = check
        self._settings = settings
        proxy = str(settings.get("proxy_addr") or "") or None
        self._monitor = RoomMonitor(room.platform, cookies=room.cookie or None, proxy_addr=proxy)
        self._stop_requested = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._proc: asyncio.subprocess.Process | None = None
        self.session_id: int | None = None
        # 供 API/WS 快照的最新进度
        self.progress: dict = {}

    # ---------- 生命周期 ----------

    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name=f"recorder-{self.room_id}")

    @property
    def task(self) -> asyncio.Task | None:
        return self._task

    async def wait(self) -> None:
        if self._task is not None:
            await asyncio.gather(self._task, return_exceptions=True)

    async def stop(self, reason: str = "手动停止") -> None:
        self._stop_requested.set()
        logger.info("房间 #{} 收到停止指令（{}）", self.room_id, reason)
        await self._terminate_ffmpeg()

    @property
    def platform_is_custom(self) -> bool:
        return self._platform == "custom"

    # ---------- 主循环 ----------

    async def _run(self) -> None:
        try:
            await self._open_session()
            consecutive_failures = 0
            while not self._stop_requested.is_set():
                # 每轮重新检测开播状态并解析新地址（旧地址会过期，绝不复用）
                try:
                    check = await self._monitor.check(self._room_url)
                except MonitorError as exc:
                    if self.platform_is_custom:
                        logger.info("房间 #{} 直链不可达，结束录制（{}）", self.room_id, exc)
                        break
                    consecutive_failures += 1
                    await self._mark_error(f"开播检测失败：{exc}")
                    if consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
                        logger.error("房间 #{} 连续失败 {} 次，结束本次会话", self.room_id, consecutive_failures)
                        break
                    if not await self._sleep_backoff(consecutive_failures):
                        break
                    continue
                if not check.is_live:
                    logger.info("房间 #{} 已下播，结束录制", self.room_id)
                    break
                self._check = check

                quality = self._room_quality or str(self._settings.get("quality"))
                try:
                    stream = await self._monitor.resolve_stream(check, quality)
                except MonitorError as exc:
                    if self.platform_is_custom:
                        logger.info("房间 #{} 直链解析失败，结束录制（{}）", self.room_id, exc)
                        break
                    consecutive_failures += 1
                    await self._mark_error(f"解析流地址失败：{exc}")
                    if consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
                        logger.error("房间 #{} 连续失败 {} 次，结束本次会话", self.room_id, consecutive_failures)
                        break
                    if not await self._sleep_backoff(consecutive_failures):
                        break
                    continue

                consecutive_failures = 0
                await self._mark_recording()
                exit_code = await self._record_segment(stream)
                if self._stop_requested.is_set():
                    break
                if exit_code != 0:
                    # 本段录制失败（流断开/地址失效等）：计入失败并退避，避免高频重试
                    consecutive_failures += 1
                    await self._mark_error(f"录制中断（FFmpeg 退出码 {exit_code}），准备重连")
                    if consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
                        logger.error("房间 #{} 连续失败 {} 次，结束本次会话", self.room_id, consecutive_failures)
                        break
                    if not await self._sleep_backoff(consecutive_failures):
                        break
                    continue
                await asyncio.sleep(2)  # 段间小停顿，降低重新解析的频率
        except asyncio.CancelledError:
            proc = self._proc
            if proc is not None and proc.returncode is None:
                proc.kill()
        except Exception:
            logger.exception("房间 #{} 录制任务异常退出", self.room_id)
        finally:
            with contextlib.suppress(Exception):
                await asyncio.shield(self._close_session())

    async def _sleep_backoff(self, failures: int) -> bool:
        """指数退避等待。返回 False 表示已请求停止。"""
        max_backoff = int(self._settings.get("reconnect_backoff_max"))
        seconds = min(max_backoff, 5 * 2 ** max(failures - 1, 0))
        logger.warning("房间 #{} 第 {} 次失败，{}s 后重试", self.room_id, failures, seconds)
        try:
            await asyncio.wait_for(self._stop_requested.wait(), timeout=seconds)
            return False
        except asyncio.TimeoutError:
            return True

    # ---------- FFmpeg 分段录制 ----------

    async def _record_segment(self, stream) -> int:
        """录制一个分段，返回 FFmpeg 退出码（0=正常，其他=异常）。"""
        out_path, rel_path = self._build_output_path(stream)
        factory = session_factory()
        async with factory() as s:
            row = RecordingFile(
                session_id=self.session_id,
                room_id=self.room_id,
                file_path=rel_path.as_posix(),
                start_time=utcnow(),
                status="recording",
            )
            s.add(row)
            await s.commit()
            file_id = row.id

        cmd = self._build_ffmpeg_cmd(stream.record_url, out_path)
        logger.info("房间 #{} 开始分段: {}", self.room_id, out_path.name)
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError:
            logger.error("未找到 FFmpeg（路径: {}），请在设置中配置正确路径", self._settings.get("ffmpeg_path"))
            await self._finalize_file(file_id, out_path, 0.0, "error")
            await self._set_room("error", "未找到 FFmpeg，请在设置中配置正确路径")
            self._stop_requested.set()
            return -1
        self._proc = proc
        stats = {"duration": 0.0, "bitrate": ""}
        reader = asyncio.create_task(self._read_stderr(proc, rel_path, out_path, stats))
        try:
            await proc.wait()
        finally:
            self._proc = None
            reader.cancel()
            await asyncio.gather(reader, return_exceptions=True)

        duration = stats["duration"]
        status = "finished" if proc.returncode == 0 else "error"
        await self._finalize_file(file_id, out_path, duration, status)
        self.progress = {
            "session_id": self.session_id,
            "file": rel_path.as_posix(),
            "duration": round(duration, 1),
            "size": self._file_size(out_path),
            "bitrate": stats["bitrate"],
        }
        logger.info(
            "房间 #{} 分段结束: {}（退出码 {}，时长 {:.0f}s，大小 {:.1f} MB）",
            self.room_id, out_path.name, proc.returncode, duration, self._file_size(out_path) / 1048576,
        )
        return proc.returncode or 0

    def _build_ffmpeg_cmd(self, url: str, out_path: Path) -> list[str]:
        parsed = urllib.parse.urlparse(url)
        referer = f"{parsed.scheme}://{parsed.netloc}/" if parsed.netloc else ""
        headers = f"User-Agent: {FFMPEG_UA}\r\n"
        if referer:
            headers += f"Referer: {referer}\r\n"
        output_format = str(self._settings.get("output_format"))
        if output_format not in ("mp4", "flv"):
            output_format = "mp4"
        cmd = [
            str(self._settings.get("ffmpeg_path")),
            "-hide_banner",
            "-loglevel", "info",
            "-stats",
            "-y",
            "-rw_timeout", "30000000",  # 30s 网络读写超时（微秒），防止卡死
            "-reconnect", "1",
            "-reconnect_streamed", "1",
            "-reconnect_delay_max", "10",
        ]
        if url.lower().startswith("https"):
            # 跳过 TLS 证书校验：国内网络环境下代理/劫持很常见，streamget 自身同样不做校验
            cmd += ["-verify", "0"]
        cmd += [
            "-headers", headers,
            "-i", url,
            "-c", "copy",
            "-f", output_format,
            str(out_path),
        ]
        return cmd

    async def _read_stderr(self, proc: asyncio.subprocess.Process, rel_path: Path,
                           out_path: Path, stats: dict) -> None:
        """解析 FFmpeg 的 stats 输出，节流发布录制进度。"""
        last_publish = 0.0
        buffer = ""
        assert proc.stderr is not None
        while True:
            chunk = await proc.stderr.read(4096)
            if not chunk:
                break
            buffer += chunk.decode("utf-8", "replace")
            if len(buffer) > 65536:
                buffer = buffer[-8192:]
            for piece in re.split(r"[\r\n]+", buffer):
                m = _TIME_RE.search(piece)
                if m:
                    stats["duration"] = int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])
                m = _BITRATE_RE.search(piece)
                if m:
                    factor = {"k": 1, "m": 1000, "g": 1e6}.get(m[2].lower(), 1)
                    stats["bitrate"] = f"{float(m[1]) * factor:.0f} kbps"
            now = time.monotonic()
            if stats["duration"] > 0 and now - last_publish >= 2.0:
                last_publish = now
                self.progress = {
                    "session_id": self.session_id,
                    "file": rel_path.as_posix(),
                    "duration": round(stats["duration"], 1),
                    "size": self._file_size(out_path),
                    "bitrate": stats["bitrate"],
                }
                bus.publish("recording_progress", room_id=self.room_id, **self.progress)

    @staticmethod
    def _file_size(path: Path) -> int:
        try:
            return path.stat().st_size
        except OSError:
            return 0

    # ---------- 文件路径 ----------

    def _build_output_path(self, stream) -> tuple[Path, Path]:
        ext = str(self._settings.get("output_format"))
        if ext not in ("mp4", "flv"):
            ext = "mp4"
        start = utcnow()
        mapping = {
            "platform": sanitize_component(self._platform, 40),
            "anchor": sanitize_component(self._check.anchor_name or getattr(stream, "anchor_name", ""), 60),
            "title": sanitize_component(self._check.title or getattr(stream, "title", ""), 80),
            "datetime": start.strftime("%Y%m%d_%H%M%S"),
            "quality": sanitize_component(getattr(stream, "quality", "") or "", 8),
        }
        rendered = str(self._settings.get("file_template"))
        for key, value in mapping.items():
            rendered = rendered.replace("{" + key + "}", value)
        parts = [sanitize_component(p) for p in rendered.split("/") if p.strip()]
        if not parts:
            parts = [mapping["platform"], mapping["anchor"], f"{mapping['datetime']}_{mapping['title']}"]
        # 模板最后一段是文件名主干（可含占位符），其余为目录层级
        *dirs, name_stem = parts
        root: Path = self._settings.record_root()
        out_dir = root.joinpath(*dirs) if dirs else root
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{name_stem}.{ext}"
        counter = 1
        while out_path.exists():
            out_path = out_dir / f"{name_stem}-{counter}.{ext}"
            counter += 1
        return out_path, out_path.relative_to(root)

    # ---------- DB 状态与事件 ----------

    async def _open_session(self) -> None:
        factory = session_factory()
        async with factory() as s:
            row = RecordingSession(
                room_id=self.room_id,
                platform=self._platform,
                anchor_name=self._check.anchor_name,
                title=self._check.title,
                quality=self._room_quality or str(self._settings.get("quality")),
                start_time=utcnow(),
                status="recording",
            )
            s.add(row)
            await s.commit()
            self.session_id = row.id
        logger.info(
            "房间 #{} 录制会话 #{} 开始：{}（{}）",
            self.room_id, self.session_id, self._check.title, self._check.anchor_name,
        )
        bus.publish(
            "recording_started",
            room_id=self.room_id,
            session_id=self.session_id,
            anchor_name=self._check.anchor_name,
            title=self._check.title,
            quality=self._room_quality,
        )

    async def _close_session(self) -> None:
        if self.session_id is None:
            return
        factory = session_factory()
        async with factory() as s:
            row = await s.get(RecordingSession, self.session_id)
            if row is not None and row.status == "recording":
                row.end_time = utcnow()
                row.status = "finished"
            # 收尾可能没来得及更新的分段
            files = (
                await s.execute(
                    select(RecordingFile).where(
                        RecordingFile.session_id == self.session_id,
                        RecordingFile.status == "recording",
                    )
                )
            ).scalars().all()
            for f in files:
                f.status = "finished"
                f.end_time = utcnow()
                f.size = self._file_size(self._settings.record_root() / f.file_path)
            room = await s.get(Room, self.room_id)
            if room is not None and room.status == "recording":
                room.status = "idle"
                room.status_msg = ""
            await s.commit()
        bus.publish("recording_ended", room_id=self.room_id, session_id=self.session_id)
        logger.info("房间 #{} 录制会话 #{} 结束", self.room_id, self.session_id)
        self.progress = {}

    async def _set_room(self, status: str, msg: str = "") -> None:
        factory = session_factory()
        async with factory() as s:
            room = await s.get(Room, self.room_id)
            if room is None:
                return
            room.status = status
            room.status_msg = msg[:250]
            await s.commit()
        bus.publish("room_status", room_id=self.room_id, status=status, status_msg=msg[:250])

    async def _mark_recording(self) -> None:
        await self._set_room("recording", "")

    async def _mark_error(self, msg: str) -> None:
        logger.warning("房间 #{} {}", self.room_id, msg)
        await self._set_room("recording", msg)  # 会话仍在，保持 recording 状态并携带错误信息

    async def _finalize_file(self, file_id: int, out_path: Path, duration: float, status: str) -> None:
        factory = session_factory()
        async with factory() as s:
            row = await s.get(RecordingFile, file_id)
            if row is None:
                return
            row.size = self._file_size(out_path)
            row.duration = round(duration, 1)
            row.end_time = utcnow()
            row.status = status
            await s.commit()

    # ---------- 停止 ----------

    async def _terminate_ffmpeg(self) -> None:
        proc = self._proc
        if proc is None or proc.returncode is not None:
            return
        # 优先向 stdin 发 'q'，FFmpeg 会优雅收尾（补全 mp4 moov box）
        try:
            assert proc.stdin is not None
            proc.stdin.write(b"q")
            await proc.stdin.drain()
        except Exception:
            pass
        try:
            await asyncio.wait_for(proc.wait(), timeout=_GRACEFUL_STOP_TIMEOUT)
        except asyncio.TimeoutError:
            logger.warning("房间 #{} FFmpeg 未响应优雅停止，强制终止", self.room_id)
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                proc.kill()
