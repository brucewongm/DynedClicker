"""
TCP 通信：长度前缀 JSON 帧，Master 持续监听 / Slave 持续重连
"""
import socket
import threading
import time
from typing import Any, Callable, Dict, Optional

from core.protocol import MessageType, decode_messages, encode_message


class MessageWaitQueue:
    """按消息类型阻塞等待"""

    def __init__(self):
        self._conditions: Dict[MessageType, threading.Condition] = {}
        self._pending: Dict[MessageType, Dict[str, Any]] = {}

    def _cond(self, msg_type: MessageType) -> threading.Condition:
        if msg_type not in self._conditions:
            self._conditions[msg_type] = threading.Condition()
        return self._conditions[msg_type]

    def offer(self, msg_type: MessageType, data: Dict[str, Any]):
        with self._cond(msg_type):
            self._pending[msg_type] = data
            self._cond(msg_type).notify_all()

    def get(self, msg_type: MessageType, timeout: float) -> Optional[Dict[str, Any]]:
        cond = self._cond(msg_type)
        with cond:
            deadline = time.time() + max(0, timeout)
            while msg_type not in self._pending:
                remaining = deadline - time.time()
                if remaining <= 0:
                    return None
                cond.wait(timeout=remaining)
            return self._pending.pop(msg_type)


class NetworkNode:
    """网络节点基类：业务运行期间保持连接，仅用户停止时 shutdown"""

    def __init__(self, config, logger):
        self.config = config
        self.logger = logger
        self.port = config.get("network.port", 8888)
        self.heartbeat_interval = config.get("network.heartbeat_interval", 3)
        self.reconnect_interval = config.get("network.reconnect_interval", 2.0)

        self.socket: Optional[socket.socket] = None
        self.connected = False
        self.running = False
        self._shutdown = False
        self._send_lock = threading.Lock()
        self._recv_buffer = bytearray()
        self.message_callbacks: Dict[MessageType, Callable] = {}
        self._wait_queue = MessageWaitQueue()
        self._receiver_thread: Optional[threading.Thread] = None
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._connected_event = threading.Event()
        self.on_connected: Optional[Callable[[], None]] = None
        self.on_disconnect: Optional[Callable[[], None]] = None
        self.peer_ip: Optional[str] = None

    def register_callback(self, msg_type: MessageType, callback: Callable):
        self.message_callbacks[msg_type] = callback

    def wait_until_connected(self, stop_event: threading.Event, poll: float = 0.3) -> bool:
        while not stop_event.is_set() and not self._shutdown:
            if self.connected:
                return True
            self._connected_event.wait(poll)
        return self.connected and not self._shutdown

    def send_message(self, msg_type: MessageType, data: Optional[Dict[str, Any]] = None) -> bool:
        if self._shutdown:
            return False
        if not self.connected or not self.socket:
            self.logger.warning("无法发送 %s: 未连接", msg_type.value)
            return False
        packet = encode_message(msg_type, data)
        try:
            with self._send_lock:
                self.socket.sendall(packet)
            self.logger.debug("发送: %s", msg_type.value)
            return True
        except OSError as e:
            self.logger.error("发送失败 %s: %s", msg_type.value, e)
            self._handle_peer_disconnect()
            return False

    def wait_for_message(
        self,
        msg_type: MessageType,
        timeout: float,
        stop_event: Optional[threading.Event] = None,
    ) -> Optional[Dict[str, Any]]:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if stop_event and stop_event.is_set():
                return None
            if not self.connected:
                if stop_event and not self.wait_until_connected(stop_event, poll=0.3):
                    return None
                if not self.connected:
                    time.sleep(0.2)
                    continue
            msg = self._wait_queue.get(msg_type, min(0.3, deadline - time.time()))
            if msg is not None:
                return msg
        return None

    def _dispatch(self, message: Dict):
        try:
            msg_type = MessageType(message["type"])
        except ValueError:
            self.logger.warning("未知消息类型: %s", message.get("type"))
            return

        self.logger.info("收到: %s", msg_type.value)

        if msg_type == MessageType.PING:
            self.send_message(MessageType.PONG)
            return
        if msg_type == MessageType.PONG:
            return

        self._wait_queue.offer(msg_type, message.get("data") or {})

        cb = self.message_callbacks.get(msg_type)
        if cb:
            try:
                cb(message.get("data") or {})
            except Exception as e:
                self.logger.exception("消息回调异常 %s: %s", msg_type.value, e)

    def _recv_loop(self):
        while self.running and self.connected and self.socket:
            try:
                self.socket.settimeout(0.5)
                chunk = self.socket.recv(8192)
                if not chunk:
                    self.logger.warning("对端关闭了连接")
                    self._handle_peer_disconnect()
                    break
                self._recv_buffer.extend(chunk)
                messages, _ = decode_messages(self._recv_buffer)
                for msg in messages:
                    self._dispatch(msg)
            except socket.timeout:
                continue
            except OSError as e:
                if self.running:
                    self.logger.error("接收错误: %s", e)
                self._handle_peer_disconnect()
                break

    def _heartbeat_loop(self):
        while self.running and self.connected and not self._shutdown:
            self.send_message(MessageType.PING)
            time.sleep(self.heartbeat_interval)

    def _start_peer_threads(self):
        self.running = True
        self._receiver_thread = threading.Thread(target=self._recv_loop, daemon=True)
        self._receiver_thread.start()
        self._heartbeat_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self._heartbeat_thread.start()

    def _stop_peer_threads(self):
        self.running = False

    def _handle_peer_disconnect(self):
        if not self.connected and not self.socket:
            return
        self.connected = False
        self.peer_ip = None
        self._connected_event.clear()
        self._stop_peer_threads()
        if self.socket:
            try:
                self.socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                self.socket.close()
            except OSError:
                pass
            self.socket = None
        self.logger.info("连接已断开，将保持运行并等待恢复")
        if self.on_disconnect:
            try:
                self.on_disconnect()
            except Exception as e:
                self.logger.exception("on_disconnect 回调异常: %s", e)

    def _attach_peer(self, sock: socket.socket, peer_desc: str, peer_addr=None):
        self._stop_peer_threads()
        if self.socket:
            try:
                self.socket.close()
            except OSError:
                pass
        self.socket = sock
        self.socket.settimeout(None)
        self.connected = True
        if peer_addr and isinstance(peer_addr, tuple):
            self.peer_ip = str(peer_addr[0])
        elif peer_addr:
            self.peer_ip = str(peer_addr)
        self._recv_buffer.clear()
        self._connected_event.set()
        self._start_peer_threads()
        self.logger.info("已建立连接: %s", peer_desc)
        if self.on_connected:
            try:
                self.on_connected()
            except Exception as e:
                self.logger.exception("on_connected 回调异常: %s", e)

    def shutdown(self):
        """仅用户停止服务时调用，主动关闭连接与监听"""
        self._shutdown = True
        self._handle_peer_disconnect()
        self.logger.info("网络已关闭")


class MasterNode(NetworkNode):
    """Master：持续监听，Slave 断开后继续 accept"""

    def __init__(self, config, logger):
        super().__init__(config, logger)
        self.bind_ip = config.get("network.bind_ip", "0.0.0.0")
        self._server_socket: Optional[socket.socket] = None
        self._accept_thread: Optional[threading.Thread] = None
        self._accept_stop = threading.Event()

    def start_persistent_server(self, stop_event: threading.Event) -> bool:
        if self._accept_thread and self._accept_thread.is_alive():
            return True
        try:
            self._server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._server_socket.bind((self.bind_ip, self.port))
            self._server_socket.listen(1)
            self.logger.info("持续监听 %s:%s，等待 Slave 连接...", self.bind_ip, self.port)
        except OSError as e:
            self.logger.error("绑定监听失败: %s", e)
            return False

        self._accept_stop.clear()
        self._accept_thread = threading.Thread(
            target=self._accept_loop,
            args=(stop_event,),
            daemon=True,
        )
        self._accept_thread.start()
        return True

    def _accept_loop(self, stop_event: threading.Event):
        while not stop_event.is_set() and not self._shutdown:
            if not self._server_socket:
                break
            try:
                self._server_socket.settimeout(1.0)
                client, addr = self._server_socket.accept()
                self._attach_peer(client, f"Slave {addr}", addr)
            except socket.timeout:
                continue
            except OSError as e:
                if not stop_event.is_set() and not self._shutdown:
                    self.logger.error("accept 异常: %s", e)
                    time.sleep(self.reconnect_interval)

    def shutdown(self):
        self._accept_stop.set()
        self._shutdown = True
        if self._server_socket:
            try:
                self._server_socket.close()
            except OSError:
                pass
            self._server_socket = None
        super().shutdown()
        self.logger.info("Master 监听已停止")


class SlaveNode(NetworkNode):
    """Slave：持续重连 Master"""

    def __init__(self, config, logger):
        super().__init__(config, logger)
        self.master_ip = config.get("network.master_ip", "127.0.0.1")
        self._connect_thread: Optional[threading.Thread] = None

    def start_persistent_client(self, stop_event: threading.Event) -> bool:
        if self._connect_thread and self._connect_thread.is_alive():
            return True
        self._connect_thread = threading.Thread(
            target=self._connect_loop,
            args=(stop_event,),
            daemon=True,
        )
        self._connect_thread.start()
        return True

    def _connect_loop(self, stop_event: threading.Event):
        while not stop_event.is_set() and not self._shutdown:
            if self.connected:
                time.sleep(0.3)
                continue
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                timeout = self.config.get("network.connect_timeout", 5)
                sock.settimeout(timeout)
                sock.connect((self.master_ip, self.port))
                self._attach_peer(sock, f"Master {self.master_ip}:{self.port}", self.master_ip)
            except OSError as e:
                self.logger.warning(
                    "连接 Master 失败 (%s:%s): %s，%ss 后重试",
                    self.master_ip,
                    self.port,
                    e,
                    self.reconnect_interval,
                )
                time.sleep(self.reconnect_interval)

    def shutdown(self):
        super().shutdown()
