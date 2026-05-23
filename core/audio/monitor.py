"""
音频监控模块
检测静音间隔
"""
import time
from collections import deque

import numpy as np


class SilenceDetector:
    """静音检测器：基于连续静音时长触发"""

    def __init__(
        self,
        config,
        silence_duration: float = None,
        *,
        relative_detection: bool = False,
    ):
        self.threshold = float(config.get("audio.silence_threshold", 0.01))
        self.silence_duration = float(
            silence_duration
            if silence_duration is not None
            else config.get("audio.silence_duration", 1.0)
        )
        self.sample_rate = int(config.get("audio.sample_rate", 44100))
        self.chunk_size = int(config.get("audio.chunk_size", 1024))
        self.frame_duration = self.chunk_size / self.sample_rate

        self.dynamic_threshold_factor = float(
            config.get("audio.dynamic_threshold_factor", 0.35)
        )
        self.peak_hold_ratio = float(config.get("audio.peak_hold_ratio", 0.15))

        self.relative_detection = relative_detection
        self._playback_ratio = float(config.get("dyclicker.playback_ratio", 2.5))
        self._silence_ratio = float(config.get("dyclicker.silence_ratio", 1.4))
        self._noise_floor: float | None = None

        self.volume_history = deque(maxlen=50)
        self.silent_frames = 0
        self.is_silent = False
        self._silence_started_at: float | None = None
        self._peak_volume = 0.0
        self._heard_meaningful_audio = False

    def calculate_volume(self, audio_chunk: np.ndarray) -> float:
        if len(audio_chunk) == 0:
            return 0.0
        data = audio_chunk.astype(np.float64)
        rms = float(np.sqrt(np.mean(data ** 2)))
        peak = float(np.max(np.abs(data)))
        # 环回电平很小时，峰值比 RMS 更敏感
        return max(rms, peak * 0.35)

    def _update_noise_floor(self, volume: float) -> None:
        if not self.relative_detection:
            return
        floor = max(volume, 1e-8)
        if self._noise_floor is None:
            self._noise_floor = floor
            return
        if volume < self._noise_floor * self._playback_ratio:
            self._noise_floor = 0.992 * self._noise_floor + 0.008 * floor

    def get_noise_floor(self) -> float:
        if self._noise_floor is None:
            return self.threshold * 0.1
        return self._noise_floor

    def get_silence_cutoff(self) -> float:
        return self._silence_cutoff()

    def get_dynamic_threshold(self) -> float:
        if len(self.volume_history) == 0:
            return self.threshold
        avg_volume = float(np.mean(self.volume_history))
        dynamic = avg_volume * self.dynamic_threshold_factor
        return max(dynamic, self.threshold)

    def _playback_level(self) -> float:
        """视为「有播放」的最低电平。"""
        if self.relative_detection:
            return max(self.get_noise_floor() * self._playback_ratio, self.threshold * 0.05)
        return self.threshold * 2

    def _silence_cutoff(self) -> float:
        """低于该音量视为停顿；有播放峰值时相对峰值判断，避免动态阈值过高漏检。"""
        if self.relative_detection and self._peak_volume > self._playback_level():
            return max(
                self.get_noise_floor() * self._silence_ratio,
                self._peak_volume * self.peak_hold_ratio,
                self.threshold * 0.05,
            )
        if self._peak_volume > self.threshold * 2:
            return max(self._peak_volume * self.peak_hold_ratio, self.threshold)
        if self.relative_detection:
            return max(self.get_noise_floor() * self._silence_ratio, self.threshold * 0.05)
        return self.get_dynamic_threshold()

    def is_audible(self, volume: float) -> bool:
        """当前块是否视为有声音（与停顿判定使用同一阈值）。"""
        return volume >= self._silence_cutoff()

    def note_heard_audio(self, volume: float) -> bool:
        """是否已检测到有效播放（用于避免启动后误触）。"""
        self._update_noise_floor(volume)
        if volume >= self._playback_level():
            self._heard_meaningful_audio = True
            return True
        if self.is_audible(volume):
            self._heard_meaningful_audio = True
            return True
        if volume >= self.threshold * 2:
            self._heard_meaningful_audio = True
            return True
        if len(self.volume_history) >= 5:
            baseline = float(np.mean(self.volume_history))
            if baseline > 0 and volume >= baseline * 1.8:
                self._heard_meaningful_audio = True
                return True
        return self._heard_meaningful_audio

    def has_heard_meaningful_audio(self) -> bool:
        return self._heard_meaningful_audio

    def process_chunk(self, audio_chunk: np.ndarray) -> bool:
        volume = self.calculate_volume(audio_chunk)
        self._update_noise_floor(volume)
        self.volume_history.append(volume)

        if volume > self._peak_volume:
            self._peak_volume = volume
        elif self._peak_volume > 0:
            self._peak_volume *= 0.998

        cutoff = self._silence_cutoff()
        is_current_silent = volume < cutoff

        if not is_current_silent:
            self.silent_frames = 0
            self._silence_started_at = None
            if self.is_silent:
                self.is_silent = False
            return False

        self.silent_frames += 1
        now = time.time()
        if self._silence_started_at is None:
            self._silence_started_at = now

        elapsed = now - self._silence_started_at
        if not self.is_silent and elapsed >= self.silence_duration:
            self.is_silent = True
            return True
        return False

    def pending_silence_elapsed(self, now: float | None = None) -> bool:
        """墙钟判定：静音已持续够久且本轮尚未触发（用于采集停滞时的兜底）。"""
        if self.is_silent or self._silence_started_at is None:
            return False
        now = time.time() if now is None else now
        return (now - self._silence_started_at) >= self.silence_duration

    def dismiss_silence_skip(self) -> None:
        """跳过点击后解除触发锁，避免长期无新音频块时无法再次检测。"""
        self.is_silent = False
        self._silence_started_at = time.time()

    def reset(self):
        self.silent_frames = 0
        self.is_silent = False
        self._silence_started_at = None
        self._peak_volume = 0.0
        self._heard_meaningful_audio = False
        self._noise_floor = None
        self.volume_history.clear()
