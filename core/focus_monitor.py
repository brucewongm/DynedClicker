"""
目标窗口焦点监测：失焦时可暂停等待（Master）或停止（Slave/旧行为）
"""
import threading
from typing import Callable, Optional

import win32gui

from core.mouse.window_tools import WindowManager


class FocusMonitor:
    """周期性检查目标窗口是否为前台"""

    def __init__(
        self,
        config,
        window_manager: WindowManager,
        logger,
        on_focus_lost: Optional[Callable] = None,
        on_focus_regained: Optional[Callable] = None,
        pause_on_focus_loss: bool = False,
    ):
        self.config = config
        self.window_manager = window_manager
        self.logger = logger
        self.on_focus_lost = on_focus_lost
        self.on_focus_regained = on_focus_regained
        self.interval = config.get("focus.check_interval", 0.5)
        self.enabled = config.get("focus.stop_on_focus_loss", True)
        self.pause_on_focus_loss = pause_on_focus_loss or config.get(
            "focus.pause_on_focus_loss", False
        )
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lost = False

    def start(self):
        if not self.enabled:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        mode = "暂停等待" if self.pause_on_focus_loss else "失焦停止"
        self.logger.info("焦点监测已启动 (%s)", mode)

    def stop(self):
        self._running = False

    def _loop(self):
        while self._running:
            if not self.window_manager.ensure_target_window(self.config):
                self.logger.warning("目标窗口不可用")
            elif self.window_manager.target_hwnd:
                fg = win32gui.GetForegroundWindow()
                has_focus = fg == self.window_manager.target_hwnd

                if not has_focus and not self._lost:
                    self._lost = True
                    if self.pause_on_focus_loss:
                        self.logger.warning("Dy 窗口已失焦，暂停并等待恢复焦点")
                        if self.on_focus_lost:
                            self.on_focus_lost()
                    else:
                        self.logger.error("Dy 窗口已失焦，停止运行")
                        self._running = False
                        if self.on_focus_lost:
                            self.on_focus_lost()
                        return

                elif has_focus and self._lost:
                    self._lost = False
                    self.logger.info("Dy 窗口已恢复焦点")
                    if self.on_focus_regained:
                        self.on_focus_regained()

            threading.Event().wait(self.interval)
