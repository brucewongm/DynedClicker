"""
Master 端音频监测：优先 WASAPI 环回，否则默认输出设备
"""
from typing import Callable, Optional

import numpy as np
import sounddevice as sd

from core.audio.monitor import SilenceDetector


class MasterAudioMonitor:
    """监测 Dy 扬声器输出，检测播放结束（静音）"""

    def __init__(self, config, logger=None):
        self.config = config
        self.logger = logger
        self.sample_rate = config.get("audio.sample_rate", 44100)
        self.chunk_size = config.get("audio.chunk_size", 1024)
        self.detector = SilenceDetector(config)
        self._stream: Optional[sd.InputStream] = None
        self._on_silence: Optional[Callable] = None
        self._device = self._find_loopback_device()

    def _log(self, level: str, msg: str, *args):
        if self.logger:
            getattr(self.logger, level)(msg, *args)

    def _find_loopback_device(self) -> Optional[int]:
        try:
            devices = sd.query_devices()
            for i, dev in enumerate(devices):
                name = str(dev.get("name", "")).lower()
                if dev.get("max_input_channels", 0) > 0 and (
                    "loopback" in name or "stereo mix" in name or "立体声混音" in name
                ):
                    self._log("info", "使用环回设备: %s", dev["name"])
                    return i
        except Exception as e:
            self._log("warning", "查找环回设备失败: %s", e)
        return None

    def start(self, on_silence: Callable):
        self._on_silence = on_silence
        self.detector.reset()

        def callback(indata, frames, time_info, status):
            chunk = indata[:, 0].astype(np.float32) if indata.ndim > 1 else indata.flatten()
            if self.detector.process_chunk(chunk) and self._on_silence:
                self._on_silence()

        kwargs = dict(
            samplerate=self.sample_rate,
            channels=1,
            dtype="float32",
            blocksize=self.chunk_size,
            callback=callback,
        )
        if self._device is not None:
            kwargs["device"] = self._device

        try:
            self._stream = sd.InputStream(**kwargs)
            self._stream.start()
            self._log("info", "Master 音频监测已启动")
        except Exception as e:
            self._log("error", "无法启动音频监测: %s", e)
            raise

    def stop(self):
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        self.detector.reset()

    def reset_detector(self):
        self.detector.reset()
