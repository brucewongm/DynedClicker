"""
查找用于监测系统播放的环回/扬声器采集输入设备
"""
from dataclasses import dataclass
from typing import List, Optional

import sounddevice as sd

CAPTURE_NAME_KEYWORDS = (
    "立体声混音",
    "stereo mix",
    "what u hear",
    "loopback",
    "混音",
    "电脑扬声器",
    "speakers",
    "speaker",
    "扬声器",
    "主声音捕获",
    "primary sound capture",
    "capture",
    "捕获",
)

LOW_PRIORITY_KEYWORDS = ("2nd", "第二", "mic", "麦克风", "microphone", "hands-free")


@dataclass
class CaptureDeviceInfo:
    index: int
    name: str
    samplerate: int
    channels: int


def _score_device(name: str) -> int:
    lower = name.lower()
    if any(k in lower for k in LOW_PRIORITY_KEYWORDS):
        return -100
    score = 0
    for i, kw in enumerate(CAPTURE_NAME_KEYWORDS):
        if kw in name or kw in lower:
            score += 100 - i
    if "output" in lower and "sst" in lower:
        score += 20
    return score


def _build_candidates(devices) -> List[CaptureDeviceInfo]:
    candidates = []
    for i, dev in enumerate(devices):
        in_ch = int(dev.get("max_input_channels", 0) or 0)
        if in_ch < 1:
            continue
        name = str(dev.get("name", ""))
        if _score_device(name) < 0:
            continue
        sr = int(dev.get("default_samplerate", 44100) or 44100)
        ch = min(2, in_ch)
        candidates.append(CaptureDeviceInfo(index=i, name=name, samplerate=sr, channels=ch))
    candidates.sort(key=lambda c: _score_device(c.name), reverse=True)
    return candidates


def is_capture_device_valid(index: Optional[int]) -> bool:
    """检查 PortAudio 设备索引是否仍可作输入采集。"""
    if index is None:
        return True
    try:
        devices = sd.query_devices()
        if index < 0 or index >= len(devices):
            return False
        dev = devices[index]
        return int(dev.get("max_input_channels", 0) or 0) > 0
    except Exception:
        return False


def find_loopback_device(logger=None) -> Optional[CaptureDeviceInfo]:
    def log_info(msg, *args):
        if logger:
            logger.info(msg, *args)

    def log_warning(msg, *args):
        if logger:
            logger.warning(msg, *args)

    try:
        devices = sd.query_devices()
    except Exception as e:
        log_warning("枚举音频设备失败: %s", e)
        return None

    candidates = _build_candidates(devices)
    for best in candidates:
        if not is_capture_device_valid(best.index):
            continue
        log_info(
            "使用音频采集设备 [%s]: %s (%s Hz, %s ch)",
            best.index,
            best.name,
            best.samplerate,
            best.channels,
        )
        return best

    log_warning(
        "未找到合适的环回采集设备，将使用系统默认输入；"
        "若无法检测播放停顿，请在声音设置中启用「立体声混音」或检查扬声器环回"
    )
    return None


def resolve_capture_device(
    preferred: Optional[CaptureDeviceInfo] = None,
    logger=None,
) -> Optional[CaptureDeviceInfo]:
    """优先复用已选设备；无效时重新枚举环回设备。"""
    if preferred and is_capture_device_valid(preferred.index):
        return preferred
    if preferred and logger:
        logger.warning(
            "音频设备 [%s] %s 已失效，重新选择采集设备",
            preferred.index,
            preferred.name,
        )
    return find_loopback_device(logger)
