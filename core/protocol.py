"""
网络协议：消息类型与长度前缀帧编解码
"""
import json
import struct
from enum import Enum
from typing import Any, Dict, Optional


class MessageType(Enum):
    """Master-Slave 消息类型"""
    START = "START"                      # Master → Slave：开始会话/新一轮
    ACK = "ACK"                          # Slave → Master：确认
    SILENCE_END = "SILENCE_END"          # Slave → Master：静音结束，录音完成
    PROCESS_RECORD = "PROCESS_RECORD"    # Master → Slave：处理并播放录音
    PLAY_DONE = "PLAY_DONE"              # Slave → Master：变调播放完成
    SYNC = "SYNC"                        # 双向：节点同步
    ROUND_COMPLETE = "ROUND_COMPLETE"    # Master → Slave：本轮结束
    RESET = "RESET"                      # 重置
    PAUSE = "PAUSE"                      # Master → Slave：暂停任务
    RESUME = "RESUME"                    # Master → Slave：继续任务
    PING = "PING"
    PONG = "PONG"
    ERROR = "ERROR"


_HEADER = struct.Struct("!I")  # 4-byte big-endian length prefix


def encode_message(msg_type: MessageType, data: Optional[Dict[str, Any]] = None) -> bytes:
    payload = json.dumps({
        "type": msg_type.value,
        "data": data or {},
    }, ensure_ascii=False).encode("utf-8")
    return _HEADER.pack(len(payload)) + payload


def decode_messages(buffer: bytearray) -> tuple[list[Dict], bytearray]:
    """从缓冲区解析出完整消息，返回 (messages, remaining_buffer)"""
    messages = []
    while True:
        if len(buffer) < _HEADER.size:
            break
        length = _HEADER.unpack_from(buffer)[0]
        if length > 10 * 1024 * 1024:  # 10MB 上限
            raise ValueError(f"消息长度异常: {length}")
        total = _HEADER.size + length
        if len(buffer) < total:
            break
        payload = bytes(buffer[_HEADER.size:total])
        del buffer[:total]
        messages.append(json.loads(payload.decode("utf-8")))
    return messages, buffer
