"""
音频块采集：优先 PortAudio 回调；部分 WDM 环回设备回调不触发时自动改用阻塞读取。
"""
import threading
import time
from typing import Callable, Optional

import numpy as np
import sounddevice as sd

from core.audio.loopback_device import CaptureDeviceInfo, is_capture_device_valid


class AudioCaptureError(RuntimeError):
    """无法打开任何音频输入设备"""


class AudioChunkSource:
    """向 on_chunk 持续提供单声道 float32 音频块"""

    def __init__(
        self,
        on_chunk: Callable[[np.ndarray], None],
        logger=None,
        device: Optional[CaptureDeviceInfo] = None,
        sample_rate: Optional[int] = None,
        chunk_size: int = 1024,
        read_timeout: float = 3.0,
    ):
        self._on_chunk = on_chunk
        self._logger = logger
        self._chunk_size = chunk_size
        self._read_timeout = float(read_timeout)
        self._device_info = device
        self._device_index = device.index if device else None
        self._channels = device.channels if device else 1
        self._sample_rate = sample_rate or (device.samplerate if device else 44100)
        self._stream: Optional[sd.InputStream] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._use_blocking = False

    def _log(self, level: str, msg: str, *args):
        if self._logger:
            getattr(self._logger, level)(msg, *args)

    def _apply_device(self, device: Optional[CaptureDeviceInfo]) -> None:
        self._device_info = device
        if device is None:
            self._device_index = None
            self._channels = 1
            if not self._sample_rate:
                self._sample_rate = 44100
            return
        self._device_index = device.index
        self._channels = device.channels
        self._sample_rate = device.samplerate

    def _to_mono(self, indata: np.ndarray) -> np.ndarray:
        if indata.ndim > 1:
            return np.max(indata, axis=1).astype(np.float32, copy=False)
        return indata.astype(np.float32, copy=False)

    def _deliver_chunk(self, indata: np.ndarray) -> None:
        try:
            self._on_chunk(self._to_mono(indata))
        except Exception as e:
            self._log("error", "音频块处理失败: %s", e)

    def _input_kwargs(self) -> dict:
        kwargs = dict(
            samplerate=self._sample_rate,
            channels=self._channels,
            dtype="float32",
            blocksize=self._chunk_size,
        )
        if self._device_index is not None:
            kwargs["device"] = self._device_index
        return kwargs

    def _callback_works(self) -> bool:
        count = 0

        def probe_cb(indata, frames, time_info, status):
            nonlocal count
            count += 1

        kwargs = self._input_kwargs()
        kwargs["callback"] = probe_cb
        stream = None
        try:
            stream = sd.InputStream(**kwargs)
            stream.start()
            time.sleep(0.9)
            return count > 0
        except Exception as e:
            self._log("debug", "回调探测失败: %s", e)
            return False
        finally:
            if stream is not None:
                try:
                    stream.stop()
                    stream.close()
                except Exception:
                    pass

    def _blocking_openable(self) -> bool:
        stream = None
        try:
            stream = sd.InputStream(**self._input_kwargs())
            stream.start()
            return True
        except Exception as e:
            self._log("debug", "阻塞模式不可用: %s", e)
            return False
        finally:
            if stream is not None:
                try:
                    stream.stop()
                    stream.close()
                except Exception:
                    pass

    def _start_callback(self) -> None:
        def callback(indata, frames, time_info, status):
            if status:
                self._log("warning", "音频流状态: %s", status)
            self._deliver_chunk(indata)

        kwargs = self._input_kwargs()
        kwargs["callback"] = callback
        self._stream = sd.InputStream(**kwargs)
        self._stream.start()
        self._use_blocking = False
        label = (
            f"设备 {self._device_index}"
            if self._device_index is not None
            else "系统默认输入"
        )
        self._log("info", "音频采集已启动（回调模式, %s Hz, %s）", self._sample_rate, label)

    def _try_start_on_current_device(self) -> bool:
        if self._device_index is not None and not is_capture_device_valid(self._device_index):
            return False
        if self._callback_works():
            self._start_callback()
            return True
        if self._blocking_openable():
            self._use_blocking = True
            self._log(
                "info",
                "当前采集设备不支持 PortAudio 回调，改用阻塞读取（设备 %s）",
                self._device_index,
            )
            self._thread = threading.Thread(target=self._blocking_loop, daemon=True)
            self._thread.start()
            return True
        try:
            self._start_callback()
            return True
        except Exception as e:
            self._log("debug", "回调模式直接打开失败: %s", e)
            return False

    def start(self) -> bool:
        """
        启动采集。依次尝试：指定环回设备 → 系统默认输入。
        失败返回 False，不抛出 PortAudioError。
        """
        self._running = True
        plans: list[Optional[CaptureDeviceInfo]] = []
        if self._device_info is not None:
            plans.append(self._device_info)
        plans.append(None)

        for plan in plans:
            self._apply_device(plan)
            if self._try_start_on_current_device():
                return True
            if plan is not None:
                self._log(
                    "warning",
                    "环回设备 [%s] 无法稳定采集，尝试系统默认输入",
                    plan.index,
                )

        self._running = False
        self._log(
            "error",
            "无法启动音频采集：环回与默认输入均失败，请检查立体声混音或扬声器环回",
        )
        return False

    def _blocking_loop(self):
        self._log("info", "音频采集已启动（阻塞模式, %s Hz）", self._sample_rate)
        stream = None
        try:
            stream = sd.InputStream(**self._input_kwargs())
            stream.start()
            while self._running:
                try:
                    data, overflowed = stream.read(
                        self._chunk_size, timeout=self._read_timeout
                    )
                    if overflowed:
                        self._log("warning", "音频读取溢出")
                    self._deliver_chunk(data)
                except Exception as e:
                    if not self._running:
                        break
                    self._log("error", "读取音频块失败: %s", e)
                    time.sleep(0.2)
        finally:
            if stream is not None:
                try:
                    stream.stop()
                    stream.close()
                except Exception:
                    pass

    def stop(self):
        self._running = False
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None
