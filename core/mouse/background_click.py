"""
后台鼠标点击：PostMessage，不抢夺焦点
"""
import time

import win32api
import win32con
import win32gui


class BackgroundClicker:
    """向目标窗口客户区发送点击消息"""

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

    def click_screen(self, screen_x: int, screen_y: int, button: str = "left") -> bool:
        hwnd = win32gui.WindowFromPoint((screen_x, screen_y))
        if not hwnd:
            return False
        return self.send_click_message(hwnd, screen_x, screen_y, button)

    def click_region(self, region_name: str, config) -> bool:
        if not self.window_manager.ensure_target_window(config):
            self._log("error", "未找到目标窗口")
            return False
        region = config.get_mouse_region(region_name)
        x, y = region["x"], region["y"]
        if x == 0 and y == 0:
            self._log("error", "区域 %s 未配置", region_name)
            return False
        self._log("info", "点击 %s @ (%s, %s)", region_name, x, y)
        return self.send_click_message(self.window_manager.target_hwnd, x, y)
