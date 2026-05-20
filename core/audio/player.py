"""
音频播放：按块输出 float32
"""
import threading
import time
from typing import Callable, Optional

import numpy as np
import pyaudio


class AudioPlayer:
    """分块播放 numpy float32 单声道音频"""

    def __init__(self, config, logger=None):
        self.config = config
        self.logger = logger
        self.audio = pyaudio.PyAudio()
        self.stream: Optional[pyaudio.Stream] = None
        self.sample_rate = config.get("audio.sample_rate", 44100)
        self.chunk_size = config.get("audio.chunk_size", 1024)
        self._abort = threading.Event()

    def _log(self, level: str, msg: str, *args):
        if self.logger:
            getattr(self.logger, level)(msg, *args)

    def stop_playback(self):
        self._abort.set()
        self._stop_stream()

    def play_audio(self, audio_data: np.ndarray, on_finish: Optional[Callable] = None):
        self._abort.clear()
        if audio_data is None or len(audio_data) == 0:
            self._log("warning", "无音频可播放")
            if on_finish:
                on_finish()
            return

        audio = np.asarray(audio_data, dtype=np.float32).flatten()
        position = {"index": 0}
        done = threading.Event()

        def callback(in_data, frame_count, time_info, status):
            if self._abort.is_set():
                done.set()
                return (np.zeros(frame_count, dtype=np.float32).tobytes(), pyaudio.paComplete)
            start = position["index"]
            end = start + frame_count
            chunk = audio[start:end]
            if len(chunk) < frame_count:
                padding = np.zeros(frame_count - len(chunk), dtype=np.float32)
                chunk = np.concatenate([chunk, padding])
                done.set()
                flag = pyaudio.paComplete
            else:
                flag = pyaudio.paContinue
            position["index"] = end
            return (chunk.astype(np.float32).tobytes(), flag)

        self.stream = self.audio.open(
            format=pyaudio.paFloat32,
            channels=1,
            rate=self.sample_rate,
            output=True,
            frames_per_buffer=self.chunk_size,
            stream_callback=callback,
        )
        self.stream.start_stream()

        while self.stream.is_active() and not done.is_set() and not self._abort.is_set():
            time.sleep(0.01)

        self._stop_stream()
        if on_finish:
            on_finish()

    def _stop_stream(self):
        if self.stream:
            try:
                self.stream.stop_stream()
                self.stream.close()
            except Exception:
                pass
            self.stream = None

    def __del__(self):
        try:
            self._stop_stream()
            self.audio.terminate()
        except Exception:
            pass
