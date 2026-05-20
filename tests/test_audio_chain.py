"""
音频链路测试（manual：需麦克风/扬声器，默认 pytest 不执行）
"""
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.config_manager import ConfigManager
from core.audio.monitor import SilenceDetector
from core.audio.player import AudioPlayer
from core.audio.processor import AudioProcessor
from core.audio.recorder import AudioRecorder


pytestmark = pytest.mark.manual


def test_recording():
    config = ConfigManager()
    recorder = AudioRecorder(config)
    recorder.start_recording()
    import time
    time.sleep(3)
    audio = recorder.stop_recording()
    assert audio is not None


@pytest.mark.manual
def test_silence_detection():
    import time
    config = ConfigManager()
    recorder = AudioRecorder(config)
    detector = SilenceDetector(config)
    recorder.start_recording(callback=detector.process_chunk)
    time.sleep(10)
    recorder.stop_recording()


def test_audio_processing():
    config = ConfigManager()
    processor = AudioProcessor(config)
    sample_rate = 44100
    duration = 2.0
    t = np.linspace(0, duration, int(sample_rate * duration))
    test_audio = np.sin(2 * np.pi * 440 * t).astype(np.float32)
    processed = processor.quick_process(test_audio)
    assert len(processed) > 0


def test_full_audio_chain():
    """完整链路请直接运行: python tests/test_audio_chain.py"""
    pytest.skip("请使用 python tests/test_audio_chain.py 进行交互测试")


def _run_interactive_chain():
    import time

    print("交互式音频链路测试")
    config = ConfigManager()
    recorder = AudioRecorder(config)
    detector = SilenceDetector(config)
    processor = AudioProcessor(config)
    player = AudioPlayer(config)
    state = {"recorded": None}

    def on_chunk(chunk):
        if detector.process_chunk(chunk):
            state["recorded"] = recorder.stop_recording()
            return True
        return False

    recorder.start_recording(callback=on_chunk)
    print("请说话后停顿 1 秒以上，Ctrl+C 退出")
    try:
        while True:
            if state["recorded"] is not None:
                player.play_audio(processor.quick_process(state["recorded"]))
                state["recorded"] = None
                recorder.start_recording(callback=on_chunk)
            time.sleep(0.1)
    except KeyboardInterrupt:
        recorder.stop_recording()


if __name__ == "__main__":
    _run_interactive_chain()
