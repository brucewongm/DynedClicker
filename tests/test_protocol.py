"""协议编解码单元测试"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.protocol import MessageType, decode_messages, encode_message


def test_encode_decode_roundtrip():
    packet = encode_message(MessageType.START, {"round": 1})
    buf = bytearray(packet)
    messages, remaining = decode_messages(buf)
    assert len(messages) == 1
    assert messages[0]["type"] == "START"
    assert messages[0]["data"]["round"] == 1
    assert len(remaining) == 0


def test_partial_buffer():
    packet = encode_message(MessageType.ACK)
    buf = bytearray(packet[:3])
    messages, buf = decode_messages(buf)
    assert messages == []
    buf.extend(packet[3:])
    messages, buf = decode_messages(buf)
    assert len(messages) == 1
    assert messages[0]["type"] == "ACK"


def test_multiple_messages_in_one_buffer():
    combined = encode_message(MessageType.PING) + encode_message(MessageType.PONG)
    messages, _ = decode_messages(bytearray(combined))
    assert [m["type"] for m in messages] == ["PING", "PONG"]
