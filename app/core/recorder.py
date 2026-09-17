"""单路录制会话。

生命周期：开播检测 → 解析新地址 → FFmpeg 录一段（一个分段文件）→
再检测（地址会过期，绝不复用）→ 循环，直到下播 / 手动停止 / 连续失败超限。
"""

import asyncio
import contextlib
import os
import re
import shlex
import shutil
import time
import urllib.parse
from datetime import datetime
from pathlib import Path

import httpx
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
        # 分段级错误说明（磁盘不足等），供 _run 的失败提示覆盖默认文案
        self._last_error: str | None = None

    # ---------- 生命周期 ----------

    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name=f"recorder-{self.room_id}")

    @property
    def task(self) -> asyncio.Task | None:
        return self._task

    @property
    def platform(self) -> str:
        return self._platform

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
            session_started = time.monotonic()
            while not self._stop_requested.is_set():
                # 连续失败上限可配置（设置页），默认沿用常量值
                max_failures = int(self._settings.get("max_consecutive_failures") or _MAX_CONSECUTIVE_FAILURES)
                # 单场最大录制时长（0 = 不限制），设置页修改后下轮分段生效
                max_hours = int(self._settings.get("max_session_hours") or 0)
                if max_hours > 0 and (time.monotonic() - session_started) >= max_hours * 3600:
                    logger.info("房间 #{} 达到最大录制时长（{} 小时），结束会话", self.room_id, max_hours)
                    break
                # 每轮重新检测开播状态并解析新地址（旧地址会过期，绝不复用）
                try:
                    check = await self._monitor.check(self._room_url)
                except MonitorError as exc:
                    if self.platform_is_custom:
                        logger.info("房间 #{} 直链不可达，结束录制（{}）", self.room_id, exc)
                        break
                    consecutive_failures += 1
                    await self._mark_error(f"开播检测失败：{exc}")
                    if consecutive_failures >= max_failures:
                        logger.error("房间 #{} 连续失败 {} 次，结束本次会话", self.room_id, consecutive_failures)
                        break
                    if not await self._sleep_backoff(consecutive_failures):
                        break
                    continue
                if not check.is_live:
                    # 下播确认延迟：等待后再确认一次，防止瞬时断流/接口抖动误判下播
                    delay = int(self._settings.get("end_confirm_delay") or 0)
                    if delay > 0 and not self._stop_requested.is_set():
                        logger.info("房间 #{} 检测到下播，{} 秒后再次确认", self.room_id, delay)
                        if not await self._sleep_quiet(delay):
                            break
                        try:
                            check = await self._monitor.check(self._room_url)
                        except MonitorError:
                            pass  # 确认检测也失败：沿用上次的下播结论结束录制
                    if not check.is_live:
                        logger.info("房间 #{} 已下播，结束录制", self.room_id)
                        break
                    logger.info("房间 #{} 下播确认阶段发现已恢复开播，继续录制", self.room_id)
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
                    if consecutive_failures >= max_failures:
                        logger.error("房间 #{} 连续失败 {} 次，结束本次会话", self.room_id, consecutive_failures)
                        break
                    if not await self._sleep_backoff(consecutive_failures):
                        break
                    continue

                consecutive_failures = 0
                self._prefer_stream_type(stream)
                await self._mark_recording()
                exit_code = await self._record_segment(stream)
                if self._stop_requested.is_set():
                    break
                if exit_code != 0:
                    # 本段录制失败（流断开/地址失效/磁盘不足等）：计入失败并退避，避免高频重试
                    consecutive_failures += 1
                    await self._mark_error(
                        self._last_error or f"录制中断（FFmpeg 退出码 {exit_code}），准备重连"
                    )
                    self._last_error = None
                    if consecutive_failures >= max_failures:
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

    async def _sleep_quiet(self, seconds: float) -> bool:
        """可被停止指令打断的静默等待。返回 False 表示已请求停止。"""
        try:
            await asyncio.wait_for(self._stop_requested.wait(), timeout=seconds)
            return False
        except asyncio.TimeoutError:
            return True

    def _fire_webhook(self, event: str, **fields) -> None:
        """向设置的通知地址 POST JSON（fire-and-forget，失败仅记日志）。"""
        url = str(self._settings.get("webhook_url") or "").strip()
        if not url:
            return
        payload = {"event": event, **fields, "time": datetime.now().isoformat(timespec="seconds")}

        async def _post() -> None:
            try:
                async with httpx.AsyncClient(timeout=8, verify=False) as client:
                    await client.post(url, json=payload)
            except Exception as exc:
                logger.warning("房间 #{} webhook 通知失败（{}）: {}", self.room_id, url, exc)

        asyncio.create_task(_post(), name=f"webhook-{self.room_id}-{event}")

    def _prefer_stream_type(self, stream) -> None:
        """按设置的拉流协议优先级改写地址（部分平台同时返回 m3u8 与 flv 两种流地址）。"""
        st = str(self._settings.get("stream_type") or "auto")
        if st == "auto":
            return
        preferred = getattr(stream, "flv_url" if st == "flv" else "m3u8_url", None)
        if preferred:
            stream.record_url = preferred

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

    # ---------- 分段录制（FFmpeg 直拉 / 下载器直连） ----------

    async def _record_segment(self, stream) -> int:
        """录制一个分段，返回退出码（0=正常，其他=异常）。

        FLV 源且开启下载器直连时用 httpx 流式下载，其余走 FFmpeg。
        """
        pre = await self._segment_prologue(stream)
        if pre is None:
            return -1
        out_path, rel_path, file_id = pre
        if self._use_direct_download(stream.record_url):
            code, duration, bitrate = await self._download_core(stream.record_url, out_path, rel_path)
        else:
            code, duration, bitrate = await self._ffmpeg_core(stream, out_path, rel_path, file_id)
        await self._segment_epilogue(file_id, out_path, rel_path, code, duration, bitrate)
        return code

    async def _segment_prologue(self, stream) -> tuple[Path, Path, int] | None:
        """分段前置：生成输出路径、磁盘空间检查、登记录制文件。磁盘不足返回 None。"""
        out_path, rel_path = self._build_output_path(stream)
        # 磁盘剩余空间检查（0 = 不检查）：不足则本段失败，交由退避机制等待空间释放
        min_free_gb = float(self._settings.get("min_free_disk_gb") or 0)
        if min_free_gb > 0:
            free_gb = shutil.disk_usage(out_path).free / (1024 ** 3)
            if free_gb < min_free_gb:
                self._last_error = f"磁盘剩余空间不足（{free_gb:.1f} GB < {min_free_gb} GB），暂停录制等待空间释放"
                logger.warning("房间 #{} {}", self.room_id, self._last_error)
                return None
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
        return out_path, rel_path, file_id

    async def _segment_epilogue(self, file_id: int, out_path: Path, rel_path: Path,
                                code: int, duration: float, bitrate: str) -> None:
        """分段收尾：落库、可选转 MP4 / 执行录后脚本、更新进度快照。"""
        status = "finished" if code == 0 else "error"
        await self._finalize_file(file_id, out_path, duration, status)
        final_path = out_path
        if status == "finished":
            # 录制完成后转为 MP4（仅 FLV 输出时有意义：mp4 拷贝异常的平台先录 FLV 再转）
            if bool(self._settings.get("auto_convert_mp4")) and out_path.suffix.lower() == ".flv":
                converted = await self._convert_to_mp4(file_id, out_path)
                if converted is not None:
                    final_path = converted
            # 录制完成后执行自定义脚本（后台运行，不阻塞下一段）
            if bool(self._settings.get("run_script_after")):
                self._spawn_after_script(final_path)
        try:
            rel_final = final_path.relative_to(self._settings.record_root())
        except ValueError:
            rel_final = rel_path
        self.progress = {
            "session_id": self.session_id,
            "file": rel_final.as_posix(),
            "duration": round(duration, 1),
            "size": self._file_size(final_path),
            "bitrate": bitrate,
        }
        logger.info(
            "房间 #{} 分段结束: {}（退出码 {}，时长 {:.0f}s，大小 {:.1f} MB）",
            self.room_id, out_path.name, code, duration, self._file_size(out_path) / 1048576,
        )

    async def _ffmpeg_core(self, stream, out_path: Path, rel_path: Path, file_id: int) -> tuple[int, float, str]:
        """FFmpeg 直拉录制一个分段。返回 (退出码, 时长, 码率)。"""
        cmd = self._build_ffmpeg_cmd(stream.record_url, out_path)
        logger.info("房间 #{} 开始分段: {}", self.room_id, out_path.name)
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
                env=self._ffmpeg_env(),
            )
        except FileNotFoundError:
            logger.error("未找到 FFmpeg（路径: {}），请在设置中配置正确路径", self._settings.get("ffmpeg_path"))
            await self._finalize_file(file_id, out_path, 0.0, "error")
            await self._set_room("error", "未找到 FFmpeg，请在设置中配置正确路径")
            self._stop_requested.set()
            return -1, 0.0, ""
        self._proc = proc
        stats = {"duration": 0.0, "bitrate": ""}
        reader = asyncio.create_task(self._read_stderr(proc, rel_path, out_path, stats))
        # 时间字幕：与录制进程同生命周期，每秒一条 SRT（仅音频时无画面，不生成）
        subtitle_task = None
        if bool(self._settings.get("write_time_subtitle")) and self._effective_quality() != "audio":
            subtitle_task = asyncio.create_task(
                self._write_time_subtitle(lambda: proc.returncode is None, out_path.with_suffix(".srt"))
            )
        try:
            segment_seconds = 0
            if bool(self._settings.get("segment_enabled")):
                segment_seconds = int(self._settings.get("segment_seconds") or 0)
            if segment_seconds > 0:
                # 按时长切分：到点优雅收尾（补全 mp4 moov box），主循环会开新分段
                try:
                    await asyncio.wait_for(proc.wait(), timeout=segment_seconds)
                except asyncio.TimeoutError:
                    logger.info(
                        "房间 #{} 达到分段时间（{} 秒），切换新分段", self.room_id, segment_seconds
                    )
                    await self._graceful_quit(proc)
            else:
                await proc.wait()
        finally:
            self._proc = None
            reader.cancel()
            pending = [reader]
            if subtitle_task is not None:
                subtitle_task.cancel()
                pending.append(subtitle_task)
            await asyncio.gather(*pending, return_exceptions=True)
        return proc.returncode or 0, stats["duration"], stats["bitrate"]

    async def _download_core(self, url: str, out_path: Path, rel_path: Path) -> tuple[int, float, str]:
        """下载器直连录制一个分段：httpx 流式下载 FLV 写盘（延迟更低，规避 FFmpeg 对部分 FLV 流的兼容问题）。

        返回 (退出码, 时长, 码率)：停止/到分段时间/服务端正常结束 = 0；网络异常/HTTP 错误 = 1（走退避重试）。
        """
        url = self._prepare_url(url)
        parsed = urllib.parse.urlparse(url)
        headers = {"User-Agent": FFMPEG_UA}
        if parsed.netloc:
            headers["Referer"] = f"{parsed.scheme}://{parsed.netloc}/"
        segment_seconds = 0
        if bool(self._settings.get("segment_enabled")):
            segment_seconds = int(self._settings.get("segment_seconds") or 0)
        stop_evt = asyncio.Event()
        subtitle_task = None
        if bool(self._settings.get("write_time_subtitle")) and self._effective_quality() != "audio":
            subtitle_task = asyncio.create_task(
                self._write_time_subtitle(stop_evt.is_set, out_path.with_suffix(".srt"))
            )
        start = time.monotonic()
        size = 0
        last_publish = 0.0
        code = 0
        logger.info("房间 #{} 开始分段（下载器直连）: {}", self.room_id, out_path.name)
        try:
            async with httpx.AsyncClient(
                headers=headers,
                proxy=self._download_proxy(),
                verify=False,
                follow_redirects=True,
                timeout=httpx.Timeout(connect=15.0, read=30.0, write=30.0, pool=30.0),
            ) as client:
                async with client.stream("GET", url) as resp:
                    resp.raise_for_status()
                    with out_path.open("wb") as f:
                        async for chunk in resp.aiter_bytes(65536):
                            if self._stop_requested.is_set():
                                break
                            f.write(chunk)
                            size += len(chunk)
                            elapsed = time.monotonic() - start
                            if elapsed - last_publish >= 2.0:
                                last_publish = elapsed
                                self.progress = {
                                    "session_id": self.session_id,
                                    "file": rel_path.as_posix(),
                                    "duration": round(elapsed, 1),
                                    "size": size,
                                    "bitrate": f"{size * 8 / max(elapsed, 1e-6) / 1000:.0f} kbps",
                                }
                                bus.publish("recording_progress", room_id=self.room_id, **self.progress)
                            if segment_seconds > 0 and elapsed >= segment_seconds:
                                logger.info(
                                    "房间 #{} 达到分段时间（{} 秒），切换新分段", self.room_id, segment_seconds
                                )
                                break
        except httpx.HTTPStatusError as exc:
            self._last_error = f"下载器拉流失败：HTTP {exc.response.status_code}"
            code = 1
        except httpx.HTTPError as exc:
            self._last_error = f"下载器拉流中断：{type(exc).__name__}: {exc}"
            code = 1
        except OSError as exc:
            self._last_error = f"写入录制文件失败：{exc}"
            code = 1
        finally:
            if subtitle_task is not None:
                stop_evt.set()
                subtitle_task.cancel()
                await asyncio.gather(subtitle_task, return_exceptions=True)
        duration = time.monotonic() - start
        bitrate = f"{size * 8 / max(duration, 1e-6) / 1000:.0f} kbps" if code == 0 and duration > 0 else ""
        return code, duration, bitrate

    def _use_direct_download(self, url: str) -> bool:
        """FLV 源且开启下载器直连时改用 httpx 下载（仅音频仍走 FFmpeg 丢视频轨）。"""
        if not bool(self._settings.get("flv_direct_download")):
            return False
        if self._effective_quality() == "audio":
            return False
        return urllib.parse.urlparse(url).path.lower().endswith(".flv")

    def _prepare_url(self, url: str) -> str:
        """强制启用 https 录制：部分平台返回的 http CDN 地址易被劫持/拦截，改写为 https。"""
        if bool(self._settings.get("force_https")) and url.lower().startswith("http://"):
            return "https://" + url[len("http://"):]
        return url

    def _download_proxy(self) -> str | None:
        """对配置了代理录制的平台，下载器拉流走全局代理（其余平台直连）。"""
        proxy = str(self._settings.get("proxy_addr") or "") or None
        if not proxy:
            return None
        platforms = {p.strip() for p in str(self._settings.get("proxy_record_platforms") or "").split(",") if p.strip()}
        return proxy if self._platform in platforms else None

    def _ffmpeg_env(self) -> dict[str, str] | None:
        """对配置了代理录制的平台，让 FFmpeg 通过全局代理拉流（其余平台直连）。"""
        proxy = str(self._settings.get("proxy_addr") or "") or None
        if not proxy:
            return None
        platforms = {p.strip() for p in str(self._settings.get("proxy_record_platforms") or "").split(",") if p.strip()}
        if self._platform not in platforms:
            return None
        return {**os.environ, "http_proxy": proxy, "https_proxy": proxy}

    async def _convert_to_mp4(self, file_id: int, out_path: Path) -> Path | None:
        """FLV 分段转封装为 MP4（流拷贝，速度快）；失败时保留原文件。"""
        mp4_path = out_path.with_suffix(".mp4")
        cmd = [
            str(self._settings.get("ffmpeg_path")),
            "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(out_path),
            "-c", "copy",
            "-movflags", "+faststart",
            str(mp4_path),
        ]
        logger.info("房间 #{} 分段转封装 MP4: {}", self.room_id, mp4_path.name)
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            stderr = (await proc.communicate())[1]
        except FileNotFoundError:
            logger.error("未找到 FFmpeg，无法转封装 MP4")
            return None
        if proc.returncode != 0:
            logger.warning(
                "房间 #{} 转封装 MP4 失败（退出码 {}），保留原文件：{}",
                self.room_id, proc.returncode, stderr.decode("utf-8", "replace")[-300:],
            )
            with contextlib.suppress(OSError):
                mp4_path.unlink()
            return None
        rel = mp4_path.relative_to(self._settings.record_root())
        factory = session_factory()
        async with factory() as s:
            row = await s.get(RecordingFile, file_id)
            if row is not None:
                row.file_path = rel.as_posix()
                row.size = self._file_size(mp4_path)
                await s.commit()
        if bool(self._settings.get("delete_original_after_convert")):
            with contextlib.suppress(OSError):
                out_path.unlink()
        logger.info("房间 #{} 转封装完成: {}", self.room_id, mp4_path.name)
        return mp4_path

    def _spawn_after_script(self, file_path: Path) -> None:
        """录制完成后执行自定义脚本（后台运行，600s 超时保护）。"""
        template = str(self._settings.get("script_after_cmd") or "")
        if not template.strip():
            return
        command = template
        for key, value in {
            "{file}": str(file_path),
            "{filename}": file_path.name,
            "{title}": self._check.title or "",
            "{anchor}": self._check.anchor_name or "",
            "{platform}": self._platform,
            "{session_id}": str(self.session_id or ""),
        }.items():
            command = command.replace(key, value)

        async def _run() -> None:
            try:
                proc = await asyncio.create_subprocess_shell(
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                )
            except Exception:
                logger.exception("房间 #{} 录后脚本启动失败", self.room_id)
                return
            try:
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=600)
            except asyncio.TimeoutError:
                proc.kill()
                logger.warning("房间 #{} 录后脚本超时（600s）被终止", self.room_id)
                return
            if proc.returncode == 0:
                logger.info("房间 #{} 录后脚本执行完成：{}", self.room_id, template)
            else:
                tail = (stdout or b"").decode("utf-8", "replace")[-500:]
                logger.warning("房间 #{} 录后脚本退出码 {}：{}", self.room_id, proc.returncode, tail)

        asyncio.create_task(_run(), name=f"after-script-{self.room_id}")

    @staticmethod
    def _srt_ts(seconds: int) -> str:
        h, rem = divmod(int(seconds), 3600)
        m, s = divmod(rem, 60)
        return f"{h:02d}:{m:02d}:{s:02d},000"

    async def _write_time_subtitle(self, should_continue, srt_path: Path) -> None:
        """生成时间字幕：每秒一条 SRT，正文为对应时刻的本地时间（便于后期对时间轴）。"""
        start_mono = time.monotonic()
        start_wall = time.time()
        index = 0
        last_whole = 0
        with srt_path.open("w", encoding="utf-8") as f:
            while should_continue():
                await asyncio.sleep(0.5)
                whole = int(time.monotonic() - start_mono)
                if whole < 1 or whole == last_whole:
                    continue
                last_whole = whole
                index += 1
                wall = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(start_wall + whole))
                f.write(f"{index}\n{self._srt_ts(whole - 1)} --> {self._srt_ts(whole)}\n{wall}\n\n")
                f.flush()

    # 音频格式对应的 FFmpeg muxer（仅音频时使用；auto/m4a 为 M4A 流拷贝，aac 为裸流拷贝，mp3 需转码）
    _AUDIO_MUXERS = {"auto": "ipod", "m4a": "ipod", "aac": "aac", "mp3": "mp3"}
    # 仅音频时的输出扩展名
    _AUDIO_EXTS = {"auto": "m4a", "m4a": "m4a", "aac": "aac", "mp3": "mp3"}

    def _build_ffmpeg_cmd(self, url: str, out_path: Path) -> list[str]:
        url = self._prepare_url(url)
        parsed = urllib.parse.urlparse(url)
        referer = f"{parsed.scheme}://{parsed.netloc}/" if parsed.netloc else ""
        headers = f"User-Agent: {FFMPEG_UA}\r\n"
        if referer:
            headers += f"Referer: {referer}\r\n"
        # 输出容器二选一；仅音频（清晰度选“仅音频”）时扩展名与封装由 audio_format 决定
        output_format = str(self._settings.get("output_format"))
        if output_format not in ("mp4", "flv"):
            output_format = "mp4"
        audio_only = self._effective_quality() == "audio"
        audio_fmt = str(self._settings.get("audio_format") or "auto")
        if audio_fmt not in self._AUDIO_MUXERS:
            audio_fmt = "auto"
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
        ]
        if audio_only:
            # 仅音频：丢弃视频轨，copy/aac 直接流拷贝，mp3 需转码（直播流音频通常是 AAC）
            cmd += ["-vn"]
            if audio_fmt == "mp3":
                cmd += ["-c:a", "libmp3lame", "-q:a", "2"]
            else:
                cmd += ["-c:a", "copy"]
        else:
            # 视频录制：音频轨跟随源拷贝（默认），或视频拷贝 + 音频转码
            if audio_fmt == "mp3":
                cmd += ["-c:v", "copy", "-c:a", "libmp3lame", "-q:a", "2"]
            elif audio_fmt == "aac":
                cmd += ["-c:v", "copy", "-c:a", "aac"]
            else:
                cmd += ["-c", "copy"]
        extra = str(self._settings.get("ffmpeg_extra_args") or "").strip()
        if extra:
            # 用户自定义输出参数（如 -bsf:a aac_adtstoasc），非法时 FFmpeg 自行报错
            cmd += shlex.split(extra)
        cmd += [
            "-f", self._AUDIO_MUXERS[audio_fmt] if audio_only else output_format,
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

    def _effective_quality(self) -> str:
        """生效清晰度：房间覆盖优先，其次全局；'audio' 表示仅录制音频。"""
        return self._room_quality or str(self._settings.get("quality"))

    def _build_output_path(self, stream) -> tuple[Path, Path]:
        if self._effective_quality() == "audio":
            # 仅音频：扩展名跟随音频格式（auto/m4a 输出 M4A）
            fmt = str(self._settings.get("audio_format") or "auto")
            ext = self._AUDIO_EXTS.get(fmt, "m4a")
        else:
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
        self._fire_webhook(
            "recording_started",
            room_id=self.room_id,
            session_id=self.session_id,
            platform=self._platform,
            anchor_name=self._check.anchor_name,
            title=self._check.title,
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
        self._fire_webhook(
            "recording_ended",
            room_id=self.room_id,
            session_id=self.session_id,
            platform=self._platform,
            duration_seconds=int(self.progress.get("duration") or 0),
        )
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

    async def _graceful_quit(self, proc: asyncio.subprocess.Process) -> None:
        """向 FFmpeg stdin 发 'q' 让其优雅收尾（补全 mp4 moov box），超时则强制终止。"""
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

    async def _terminate_ffmpeg(self) -> None:
        proc = self._proc
        if proc is None or proc.returncode is not None:
            return
        await self._graceful_quit(proc)
