"""
音频处理器 - 音色/音调修改
"""
import numpy as np
import librosa
import soundfile as sf
import io
import time

class AudioProcessor:
    """音频处理器"""
    
    def __init__(self, config):
        self.sample_rate = config.get("audio.sample_rate", 44100)
        self.pitch_shift_semitones = config.get("audio.pitch_shift_semitones", 4)
        self.processing_timeout = config.get("audio.processing_timeout", 0.8)
    
    def pitch_shift(self, audio_data: np.ndarray, semitones: int) -> np.ndarray:
        """
        改变音调（半音数）
        正数升高，负数降低
        """
        # librosa的pitch_shift需要一定长度的音频
        if len(audio_data) < 1024:
            return audio_data
        
        # 使用librosa进行变调
        shifted = librosa.effects.pitch_shift(
            audio_data, 
            sr=self.sample_rate,
            n_steps=semitones
        )
        return shifted
    
    def change_tempo(self, audio_data: np.ndarray, rate: float) -> np.ndarray:
        """改变速度（不影响音调）"""
        if rate <= 0:
            return audio_data
        
        # 使用librosa改变速度
        return librosa.effects.time_stretch(audio_data, rate=rate)
    
    def add_echo(self, audio_data: np.ndarray, delay: float = 0.2, decay: float = 0.5) -> np.ndarray:
        """添加回声效果（简化版）"""
        delay_samples = int(delay * self.sample_rate)
        
        if len(audio_data) <= delay_samples:
            return audio_data
        
        # 创建回声
        echo = np.zeros(len(audio_data) + delay_samples)
        echo[:len(audio_data)] = audio_data
        echo[delay_samples:delay_samples + len(audio_data)] += audio_data * decay
        
        # 归一化
        max_val = np.max(np.abs(echo))
        if max_val > 0:
            echo = echo / max_val
        
        return echo[:len(audio_data)]
    
    def quick_process(self, audio_data: np.ndarray) -> np.ndarray:
        """快速处理（优先保证速度，延迟<0.5秒）"""
        start_time = time.time()
        
        # 简单变调
        processed = self.pitch_shift(audio_data, self.pitch_shift_semitones)
        
        # 如果处理时间过长，降级为简单处理
        elapsed = time.time() - start_time
        if elapsed > self.processing_timeout:
            print(f"警告: 变调处理超时 ({elapsed:.2f}s)，使用原音频")
            return audio_data
        
        print(f"音频处理完成，耗时 {elapsed:.2f}s")
        return processed
    
    def process_for_human_voice(self, audio_data: np.ndarray, effect_type: str = 'robot') -> np.ndarray:
        """
        针对人声的处理预设
        
        effect_type:
            - 'robot': 机器人声（升高音调+回声）
            - 'chipmunk': 花栗鼠声（大幅升高）
            - 'deep': 低沉声（降低音调）
            - 'fast': 快速处理（默认）
        """
        if effect_type == 'robot':
            shifted = self.pitch_shift(audio_data, 3)
            return self.add_echo(shifted, 0.15, 0.4)
        elif effect_type == 'chipmunk':
            return self.pitch_shift(audio_data, 7)
        elif effect_type == 'deep':
            return self.pitch_shift(audio_data, -5)
        else:  # fast
            return self.quick_process(audio_data)
    
    def save_to_wav_bytes(self, audio_data: np.ndarray) -> bytes:
        """将音频保存为WAV格式的字节流"""
        buffer = io.BytesIO()
        sf.write(buffer, audio_data, self.sample_rate, format='wav')
        return buffer.getvalue()