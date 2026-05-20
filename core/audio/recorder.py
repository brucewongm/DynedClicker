"""
音频录制：麦克风输入，int16 → float32 归一化
"""
import queue
import threading
from typing import Callable, List, Optional

import numpy as np
import pyaudio


class AudioRecorder:
    """持续录音 + 缓冲片段拼接"""

    def __init__(self, config, logger=None):
        self.config = config
        self.logger = logger
        self.audio = pyaudio.PyAudio()
        self.stream: Optional[pyaudio.Stream] = None
        self.is_recording = False
        self._session_chunks: List[np.ndarray] = []
        self._chunk_lock = threading.Lock()
        self.sample_rate = config.get("audio.sample_rate", 44100)
        self.chunk_size = config.get("audio.chunk_size", 1024)
        self.channels = config.get("audio.channels", 1)
        self._chunk_callback: Optional[Callable] = None

    def _log(self, level: str, msg: str, *args):
        if self.logger:
            getattr(self.logger, level)(msg, *args)

    def find_input_device(self) -> int:
        for i in range(self.audio.get_device_count()):
            info = self.audio.get_device_info_by_index(i)
            if info["maxInputChannels"] > 0:
                self._log("info", "输入设备 %s: %s", i, info["name"])
                return i
        return None

    @staticmethod
    def _to_float32(raw: bytes) -> np.ndarray:
        samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
        if samples.size == 0:
            return samples
        return samples / 32768.0

    def start_recording(self, callback: Optional[Callable] = None):
        self.is_recording = True
        self._chunk_callback = callback
        with self._chunk_lock:
            self._session_chunks.clear()

        def audio_callback(in_data, frame_count, time_info, status):
            if not self.is_recording:
                return (None, pyaudio.paContinue)
            chunk = self._to_float32(in_data)
            with self._chunk_lock:
                self._session_chunks.append(chunk)
            if self._chunk_callback:
                self._chunk_callback(chunk)
            return (None, pyaudio.paContinue)

        self.stream = self.audio.open(
            format=pyaudio.paInt16,
            channels=self.channels,
            rate=self.sample_rate,
            input=True,
            input_device_index=self.find_input_device(),
            frames_per_buffer=self.chunk_size,
            stream_callback=audio_callback,
        )
        self.stream.start_stream()
        self._log("info", "开始录音")

    def stop_recording(self) -> np.ndarray:
        self.is_recording = False
        if self.stream:
            self.stream.stop_stream()
            self.stream.close()
            self.stream = None
        with self._chunk_lock:
            if not self._session_chunks:
                return np.array([], dtype=np.float32)
            audio = np.concatenate(self._session_chunks)
            self._session_chunks.clear()
        self._log("info", "停止录音，样本数 %s", len(audio))
        return audio

    def clear_session_buffer(self):
        with self._chunk_lock:
            self._session_chunks.clear()

    def __del__(self):
        try:
            if self.stream:
                self.stop_recording()
            self.audio.terminate()
        except Exception:
            pass
