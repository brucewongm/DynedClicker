"""目标窗口焦点监测：失焦即停止"""
from __future__ import annotations

import threading
from typing import Callable, Optional

import win32gui

from core.mouse.window_tools import WindowManager


class FocusMonitor:
    def __init__(
        self,
        config,
        window_manager: WindowManager,
        logger,
        on_focus_lost: Optional[Callable[[], None]] = None,
        pause_on_focus_loss: bool = False,
    ):
        self.config = config
        self.window_manager = window_manager
        self.logger = logger
        self.on_focus_lost = on_focus_lost
        self.interval = float(config.get("focus.check_interval", 0.5))
        self.enabled = bool(config.get("focus.stop_on_focus_loss", True))
        self.pause_on_focus_loss = pause_on_focus_loss
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lost = False

    def start(self) -> None:
        if not self.enabled:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="focus-monitor")
        self._thread.start()
        self.logger.info("焦点监测已启动 (失焦停止)")

    def stop(self) -> None:
        self._running = False

    def _loop(self) -> None:
        while self._running:
            if not self.window_manager.ensure_target_window(self.config):
                self.logger.warning("目标窗口不可用")
            elif self.window_manager.target_hwnd:
                fg = win32gui.GetForegroundWindow()
                has_focus = fg == self.window_manager.target_hwnd
                if not has_focus and not self._lost:
                    self._lost = True
                    self.logger.error("目标窗口已失焦，停止运行")
                    self._running = False
                    if self.on_focus_lost:
                        self.on_focus_lost()
                    return
                elif has_focus and self._lost:
                    self._lost = False
                    self.logger.info("目标窗口已恢复焦点（须手动 F9 重新启动）")
            threading.Event().wait(self.interval)
