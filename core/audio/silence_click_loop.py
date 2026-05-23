"""
单次音频监测内完成多次「停顿 → 点击」循环（C/D 模式 step3 共用逻辑）。
"""
from __future__ import annotations

import queue
import threading
import time
from typing import Callable, Optional

from core.audio.chunk_source import AudioChunkSource
from core.audio.loopback_device import CaptureDeviceInfo, resolve_capture_device
from core.audio.monitor import SilenceDetector


class SilenceClickLoop:
    """
    持续采集音频，在确认已听到播放且满足最短播放时间后，
    每次停顿触发一次点击，直到完成 target_clicks 次或超时/停止。
    """

    def __init__(
        self,
        config,
        logger,
        stop_event: threading.Event,
        *,
        target_clicks: int,
        silence_duration: float,
        click_cooldown: float,
        relative_detection: bool,
        on_click: Callable[[int], None],
        capture_device: Optional[CaptureDeviceInfo] = None,
        chunk_size: int = 1024,
        read_timeout: float = 3.0,
        min_playback_before_silence: float = 0.0,
        playback_already_started: bool = False,
        wait_final_silence: bool = False,
        phase_timeout: Optional[float] = None,
        log_prefix: str = "【监测】",
    ):
        self.config = config
        self.logger = logger
        self.stop_event = stop_event
        self.target_clicks = max(0, int(target_clicks))
        self.wait_final_silence = bool(wait_final_silence)
        self.on_click = on_click
        self._capture_device = capture_device
        self._chunk_size = chunk_size
        self._read_timeout = read_timeout
        self._min_playback = max(0.0, float(min_playback_before_silence))
        self._log_prefix = log_prefix

        self._detector = SilenceDetector(
            config,
            silence_duration=silence_duration,
            relative_detection=relative_detection,
        )
        self._click_cooldown = click_cooldown
        if phase_timeout is None:
            rounds = max(target_clicks, 1) + (1 if self.wait_final_silence else 0)
            per = max(silence_duration + click_cooldown, 4.0) * rounds
            phase_timeout = per + 120.0
        self._phase_timeout = phase_timeout

        self._source: Optional[AudioChunkSource] = None
        self._silence_queue: queue.Queue = queue.Queue(maxsize=8)
        self._lock = threading.Lock()
        self._clicks_done = 0
        self._playback_confirmed = False
        self._first_audible_at: Optional[float] = None
        self._cooldown_until = 0.0
        self._monitor_started_at = 0.0
        self._last_chunk_at = 0.0
        self._final_silence_done = False
        if playback_already_started:
            now = time.time()
            self._playback_confirmed = True
            self._first_audible_at = now

    @property
    def clicks_done(self) -> int:
        return self._clicks_done

    @property
    def capture_device(self) -> Optional[CaptureDeviceInfo]:
        return self._capture_device

    def _silence_armed(self, now: float) -> bool:
        if not self._playback_confirmed:
            return False
        if self._min_playback <= 0:
            return True
        if self._first_audible_at is None:
            return False
        return (now - self._first_audible_at) >= self._min_playback

    def _handle_silence(self) -> None:
        now = time.time()
        with self._lock:
            if now - self._monitor_started_at < self._detector.silence_duration:
                return
            if now < self._cooldown_until:
                return
            if not self._silence_armed(now):
                self._detector.dismiss_silence_skip()
                return
            if not self._playback_confirmed and not self._detector.has_heard_meaningful_audio():
                self.logger.warning(
                    "%s 停顿但未采到播放声，跳过点击", self._log_prefix
                )
                self._detector.dismiss_silence_skip()
                return

            if self._clicks_done >= self.target_clicks:
                if self.wait_final_silence and not self._final_silence_done:
                    self._final_silence_done = True
                    self.logger.info(
                        "%s 最后一轮播放已结束（停顿达到 %.1fs），结束监测",
                        self._log_prefix,
                        self._detector.silence_duration,
                    )
                return

        idx = self._clicks_done + 1
        self.logger.info(
            "%s 停顿达到 %.1fs，静音点击 %d/%d",
            self._log_prefix,
            self._detector.silence_duration,
            idx,
            self.target_clicks,
        )
        self.on_click(idx)
        with self._lock:
            self._clicks_done += 1
            self._cooldown_until = time.time() + self._click_cooldown
        self._detector.reset()
        # 与 C 模式一致：点击后须重新听到播放，再对下一段停顿计数
        self._playback_confirmed = False
        self._first_audible_at = None

    def _on_chunk(self, chunk) -> None:
        self._last_chunk_at = time.time()
        volume = self._detector.calculate_volume(chunk)
        self._detector.note_heard_audio(volume)
        if self._detector.is_audible(volume):
            if self._first_audible_at is None:
                self._first_audible_at = time.time()
            self._playback_confirmed = True
        elif self._detector.note_heard_audio(volume):
            self._playback_confirmed = True

        if self._detector.process_chunk(chunk):
            try:
                self._silence_queue.put_nowait(True)
            except queue.Full:
                pass

    def _phase_complete(self) -> bool:
        if self.wait_final_silence:
            return self._final_silence_done
        return self._clicks_done >= self.target_clicks

    def _silence_worker(self) -> None:
        while not self.stop_event.is_set() and not self._phase_complete():
            try:
                self._silence_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self._handle_silence()
            except Exception as e:
                self.logger.exception("%s 处理停顿失败: %s", self._log_prefix, e)

    def run(self) -> int:
        if self.target_clicks <= 0 and not self.wait_final_silence:
            return 0

        self._detector.reset()
        self._monitor_started_at = time.time()
        self._last_chunk_at = self._monitor_started_at

        device = resolve_capture_device(self._capture_device, self.logger)
        if device:
            self._capture_device = device

        self._source = AudioChunkSource(
            on_chunk=self._on_chunk,
            logger=self.logger,
            device=device,
            chunk_size=self._chunk_size,
            read_timeout=self._read_timeout,
        )
        if not self._source.start():
            self.logger.error("%s 音频采集启动失败", self._log_prefix)
            return 0

        worker = threading.Thread(target=self._silence_worker, daemon=True, name="silence-click")
        worker.start()

        deadline = time.time() + self._phase_timeout
        try:
            while (
                not self.stop_event.is_set()
                and time.time() < deadline
                and not self._phase_complete()
            ):
                if self._detector.pending_silence_elapsed():
                    self._detector.is_silent = True
                    self._handle_silence()
                time.sleep(0.15)
        finally:
            self.stop()
            worker.join(timeout=2.0)

        if not self._phase_complete():
            if self.wait_final_silence and self._clicks_done < self.target_clicks:
                self.logger.warning(
                    "%s 仅完成 %d/%d 次静音点击（超时或已停止）",
                    self._log_prefix,
                    self._clicks_done,
                    self.target_clicks,
                )
            elif self.wait_final_silence and not self._final_silence_done:
                self.logger.warning(
                    "%s 未完成最后一轮播放结束监测（超时或已停止）",
                    self._log_prefix,
                )
            elif not self.wait_final_silence and self._clicks_done < self.target_clicks:
                self.logger.warning(
                    "%s 仅完成 %d/%d 次静音点击（超时或已停止）",
                    self._log_prefix,
                    self._clicks_done,
                    self.target_clicks,
                )
        return self._clicks_done

    def stop(self) -> None:
        if self._source:
            self._source.stop()
            self._source = None
