"""后台鼠标点击"""
from __future__ import annotations

import time

import win32api
import win32con
import win32gui


class BackgroundClicker:
    def __init__(self, window_manager, logger=None):
        self.window_manager = window_manager
        self.logger = logger

    def _log(self, level: str, msg: str, *args):
        if self.logger:
            getattr(self.logger, level)(msg, *args)

    def send_click_message(self, hwnd: int, screen_x: int, screen_y: int, button: str = "left") -> bool:
        client = win32gui.ScreenToClient(hwnd, (screen_x, screen_y))
        if button == "left":
            down_msg, up_msg, wparam = win32con.WM_LBUTTONDOWN, win32con.WM_LBUTTONUP, win32con.MK_LBUTTON
        elif button == "right":
            down_msg, up_msg, wparam = win32con.WM_RBUTTONDOWN, win32con.WM_RBUTTONUP, win32con.MK_RBUTTON
        else:
            return False
        lparam = win32api.MAKELONG(client[0], client[1])
        try:
            win32gui.PostMessage(hwnd, down_msg, wparam, lparam)
            time.sleep(0.02)
            win32gui.PostMessage(hwnd, up_msg, 0, lparam)
            return True
        except Exception as e:
            self._log("error", "后台点击失败: %s", e)
            return False

    def click_at(self, x: int, y: int, config=None) -> bool:
        if config and not self.window_manager.ensure_target_window(config):
            self._log("error", "未找到目标窗口")
            return False
        hwnd = self.window_manager.target_hwnd
        if hwnd:
            ok = self.send_click_message(hwnd, x, y)
            if ok:
                return True
        return self.click_screen(x, y)

    def click_screen(self, screen_x: int, screen_y: int, button: str = "left") -> bool:
        hwnd = win32gui.WindowFromPoint((screen_x, screen_y))
        if not hwnd:
            return False
        return self.send_click_message(hwnd, screen_x, screen_y, button)
