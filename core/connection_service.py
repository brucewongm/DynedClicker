"""
独立连接服务：与任务执行分离，启动后持续监听/重连
"""
import threading
from typing import Callable, Optional

from core.communication import MasterNode, SlaveNode
from core.logging_setup import setup_logging


class ConnectionService:
    """管理 Master/Slave TCP 连接，不依赖任务状态机"""

    def __init__(
        self,
        config,
        mode: str,
        stop_event: threading.Event,
        on_status: Optional[Callable[[str, str], None]] = None,
    ):
        self.config = config
        self.mode = mode
        self.stop_event = stop_event
        self.on_status = on_status
        self.logger = setup_logging(config, role=mode)
        self.network = None
        self._started = False

    def _notify(self, text: str, level: str = "info"):
        self.logger.info(text)
        if self.on_status:
            try:
                self.on_status(text, level)
            except Exception as e:
                self.logger.exception("状态回调异常: %s", e)

    def _on_connected(self):
        if self.mode == "master":
            ip = getattr(self.network, "peer_ip", None) or "?"
            self._notify(f"已连接 Slave [{ip}]", "connected")
        else:
            ip = getattr(self.network, "master_ip", "?")
            self._notify(f"已连接 Master [{ip}]", "connected")

    def _on_disconnected(self):
        if self.mode == "master":
            self._notify("搜索中…（等待 Slave 连接）", "searching")
        else:
            ip = getattr(self.network, "master_ip", "?")
            self._notify(f"搜索中…（正在连接 Master {ip}）", "searching")

    def start(self) -> bool:
        self.stop()

        if self.mode == "master":
            self.network = MasterNode(self.config, self.logger)
            self._notify("搜索中…（等待 Slave 连接）", "searching")
            ok = self.network.start_persistent_server(self.stop_event)
        else:
            self.network = SlaveNode(self.config, self.logger)
            ip = self.network.master_ip
            self._notify(f"搜索中…（正在连接 Master {ip}）", "searching")
            ok = self.network.start_persistent_client(self.stop_event)

        if not ok:
            self._notify("连接服务启动失败", "error")
            return False

        self.network.on_connected = self._on_connected
        self.network.on_disconnect = self._on_disconnected
        self.network._shutdown = False
        self._started = True
        return True

    def stop(self):
        if self.network:
            self.network.shutdown()
            self.network = None
        self._started = False

    def is_connected(self) -> bool:
        return bool(self.network and self.network.connected)

    def restart(self, mode: str) -> bool:
        self.mode = mode
        return self.start()
