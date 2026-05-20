"""
音频监控模块
检测静音间隔
"""
import numpy as np
from collections import deque
import time

class SilenceDetector:
    """静音检测器"""
    
    def __init__(self, config):
        self.threshold = config.get("audio.silence_threshold", 0.01)
        self.silence_duration = config.get("audio.silence_duration", 1.0)
        self.debounce_frames = config.get("audio.debounce_frames", 10)
        self.sample_rate = config.get("audio.sample_rate", 44100)
        self.chunk_size = config.get("audio.chunk_size", 1024)
        
        # 计算每帧时长（秒）
        self.frame_duration = self.chunk_size / self.sample_rate
        
        # 动态阈值参数
        self.volume_history = deque(maxlen=50)  # 保存最近50帧的音量
        self.dynamic_threshold_factor = 0.5  # 动态阈值为历史平均的50%
        
        # 静音状态
        self.silent_frames = 0
        self.is_silent = False
        self.last_trigger_time = 0
        
    def calculate_volume(self, audio_chunk: np.ndarray) -> float:
        """计算音频块的音量（RMS）"""
        if len(audio_chunk) == 0:
            return 0.0
        return np.sqrt(np.mean(audio_chunk ** 2))
    
    def get_dynamic_threshold(self) -> float:
        """获取动态阈值"""
        if len(self.volume_history) == 0:
            return self.threshold
        
        avg_volume = np.mean(self.volume_history)
        # 动态阈值为历史平均的50%与固定阈值的最大值
        dynamic = avg_volume * self.dynamic_threshold_factor
        return max(dynamic, self.threshold)
    
    def process_chunk(self, audio_chunk: np.ndarray) -> bool:
        """
        处理音频块，检测静音
        返回: 是否触发静音事件
        """
        volume = self.calculate_volume(audio_chunk)
        self.volume_history.append(volume)
        
        current_threshold = self.get_dynamic_threshold()
        is_current_silent = volume < current_threshold
        
        if is_current_silent:
            self.silent_frames += 1
        else:
            self.silent_frames = 0
        
        # 需要连续多个帧检测到静音才触发（防抖）
        if not self.is_silent and self.silent_frames >= self.debounce_frames:
            silent_time = self.silent_frames * self.frame_duration
            if silent_time >= self.silence_duration:
                self.is_silent = True
                self.last_trigger_time = time.time()
                print(f"检测到静音，持续 {silent_time:.2f} 秒")
                return True  # 触发静音事件
        
        # 恢复非静音状态
        elif self.is_silent and not is_current_silent:
            if self.silent_frames < self.debounce_frames:
                self.is_silent = False
                print("检测到声音恢复")
        
        return False
    
    def reset(self):
        """重置检测状态"""
        self.silent_frames = 0
        self.is_silent = False