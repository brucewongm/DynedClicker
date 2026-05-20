"""
C 模式：监测本机无音频播放（静音持续）后执行一次点击，与 A/B 无关
"""
import threading
import time
from typing import Optional

import numpy as np
import sounddevice as sd

from core.audio.monitor import SilenceDetector
from core.mouse.background_click import BackgroundClicker
from core.mouse.window_tools import WindowManager


class CModeRunner:
    """本机环回音频监测 → 曾播放后静音持续 → 点击一次"""

    def __init__(self, config, logger, stop_event: threading.Event):
        self.config = config
        self.logger = logger
        self.stop_event = stop_event
        self._stream: Optional[sd.InputStream] = None
        self._wm = WindowManager()
        self._clicker = BackgroundClicker(self._wm, logger)
        self._detector = SilenceDetector(config)
        self._lock = threading.Lock()
        self._heard_audio = False
        self._clicked_this_cycle = False
        self._cooldown_until = 0.0
        self._silence_duration = config.get("c_mode.silence_duration", 1.0)
        self._click_cooldown = config.get("c_mode.click_cooldown", 2.0)
        self._sample_rate = config.get("audio.sample_rate", 44100)
        self._chunk_size = config.get("audio.chunk_size", 1024)
        self._device = self._find_loopback_device()

    def _find_loopback_device(self) -> Optional[int]:
        try:
            devices = sd.query_devices()
            for i, dev in enumerate(devices):
                name = str(dev.get("name", "")).lower()
                if dev.get("max_input_channels", 0) > 0 and (
                    "loopback" in name or "stereo mix" in name or "立体声混音" in name
                ):
                    self.logger.info("C 模式使用环回设备: %s", dev["name"])
                    return i
        except Exception as e:
            self.logger.warning("查找环回设备失败: %s", e)
        return None

    def _get_click_point(self):
        return self.config.get("c_mode.click", {"x": 0, "y": 0})

    def is_click_configured(self) -> bool:
        c = self._get_click_point()
        return bool(c.get("x", 0) or c.get("y", 0))

    def run(self):
        if not self.is_click_configured():
            self.logger.error("C 模式未配置点击区域，请先矫正")
            return
        self._wm.load_from_config(self.config)
        self.logger.info(
            "C 模式启动：播放结束后静音 %.1fs 触发点击，冷却 %.1fs",
            self._silence_duration,
            self._click_cooldown,
        )
        self._detector.reset()
        try:
            self._start_monitor()
            while not self.stop_event.is_set():
                time.sleep(0.2)
        except Exception as e:
            self.logger.exception("C 模式异常: %s", e)
        finally:
            self.stop()

    def _start_monitor(self):
        def callback(indata, frames, time_info, status):
            chunk = indata[:, 0].astype(np.float32) if indata.ndim > 1 else indata.flatten()
            volume = float(np.sqrt(np.mean(chunk ** 2))) if len(chunk) else 0.0
            threshold = self._detector.get_dynamic_threshold()
            if volume >= threshold:
                with self._lock:
                    self._heard_audio = True
                    self._clicked_this_cycle = False
            if self._detector.process_chunk(chunk):
                self._handle_silence()

        kwargs = dict(
            samplerate=self._sample_rate,
            channels=1,
            dtype="float32",
            blocksize=self._chunk_size,
            callback=callback,
        )
        if self._device is not None:
            kwargs["device"] = self._device
        self._stream = sd.InputStream(**kwargs)
        self._stream.start()
        self.logger.info("C 模式音频监测已启动")

    def _handle_silence(self):
        now = time.time()
        with self._lock:
            if now < self._cooldown_until:
                return
            if not self._heard_audio or self._clicked_this_cycle:
                return
            self._clicked_this_cycle = True
            self._heard_audio = False

        self._perform_click()
        with self._lock:
            self._cooldown_until = time.time() + self._click_cooldown
        self._detector.reset()

    def _perform_click(self):
        c = self._get_click_point()
        x, y = int(c.get("x", 0)), int(c.get("y", 0))
        self._wm.ensure_target_window(self.config)
        if self._clicker.click_screen(x, y):
            self.logger.info("C 模式：无播放，已点击 (%s, %s)", x, y)
        else:
            self.logger.error("C 模式：点击失败 (%s, %s)", x, y)

    def stop(self):
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        self._detector.reset()
        self.logger.info("C 模式已停止")
