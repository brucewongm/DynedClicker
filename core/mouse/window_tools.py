"""
Windows 窗口管理：查找 Dy 窗口、矫正、全屏检测
"""
from typing import Optional, Tuple

import psutil
import win32api
import win32con
import win32gui
import win32process


class WindowManager:
    """Windows 窗口管理器"""

    def __init__(self):
        self.target_hwnd: Optional[int] = None
        self.window_title: Optional[str] = None
        self.window_class: Optional[str] = None

    def find_window_by_title(self, title_part: str) -> Optional[int]:
        matches = []

        def enum_callback(hwnd, _):
            if win32gui.IsWindowVisible(hwnd) and win32gui.IsWindowEnabled(hwnd):
                title = win32gui.GetWindowText(hwnd)
                if title_part.lower() in title.lower():
                    matches.append(hwnd)
            return True

        win32gui.EnumWindows(enum_callback, None)
        return matches[0] if matches else None

    def find_window_by_class(self, class_name: str) -> Optional[int]:
        return win32gui.FindWindow(class_name, None)

    def get_foreground_window(self) -> Optional[int]:
        return win32gui.GetForegroundWindow()

    def get_window_rect(self, hwnd: int) -> Tuple[int, int, int, int]:
        return win32gui.GetWindowRect(hwnd)

    def is_fullscreen(self, hwnd: int) -> bool:
        rect = self.get_window_rect(hwnd)
        sw = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
        sh = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)
        return rect[0] <= 0 and rect[1] <= 0 and rect[2] >= sw and rect[3] >= sh

    def get_process_name(self, hwnd: int) -> str:
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            return psutil.Process(pid).name()
        except Exception:
            return "Unknown"

    def calibrate_from_user_click(self):
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        if not messagebox.askyesno(
            "窗口矫正",
            "请先将 Dy 窗口置于前台，再点击「是」记录该窗口。",
        ):
            return None

        hwnd = self.get_foreground_window()
        if hwnd:
            self.target_hwnd = hwnd
            self.window_title = win32gui.GetWindowText(hwnd)
            self.window_class = win32gui.GetClassName(hwnd)
            print(f"已捕获窗口: {self.window_title} ({self.window_class})")
            return hwnd
        return None

    def load_from_config(self, config) -> bool:
        """启动时从配置恢复窗口句柄"""
        if self.target_hwnd and win32gui.IsWindow(self.target_hwnd):
            return True
        return self.ensure_target_window(config)

    def ensure_target_window(self, config) -> bool:
        if self.target_hwnd and win32gui.IsWindow(self.target_hwnd):
            return True

        wc = config.get("target_window", {}) or {}
        title = wc.get("window_title") or ""
        class_name = wc.get("window_class") or ""

        if title:
            hwnd = self.find_window_by_title(title)
            if hwnd:
                self.target_hwnd = hwnd
                return True
        if class_name:
            hwnd = self.find_window_by_class(class_name)
            if hwnd:
                self.target_hwnd = hwnd
                return True
        return False
