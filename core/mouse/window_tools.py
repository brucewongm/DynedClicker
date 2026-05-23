"""Windows 窗口管理"""
from __future__ import annotations

import time
from typing import Callable, Optional, Set, Tuple

import psutil
import win32api
import win32con
import win32gui
import win32process


class WindowManager:
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

    @staticmethod
    def _is_valid_target_hwnd(hwnd: int, exclude: Optional[Set[int]] = None) -> bool:
        if not hwnd or not win32gui.IsWindow(hwnd):
            return False
        if exclude and hwnd in exclude:
            return False
        if not win32gui.IsWindowVisible(hwnd):
            return False
        cls = win32gui.GetClassName(hwnd) or ""
        if cls in ("Shell_TrayWnd", "Progman", "Button", "Shell_SecondaryTrayWnd"):
            return False
        title = (win32gui.GetWindowText(hwnd) or "").strip()
        for skip in ("dyclicker", "DynedClicker", "音频自动化"):
            if skip.lower() in title.lower():
                return False
        return bool(title) or cls not in ("", "TkChild")

    def _tool_exclude_hwnds(self) -> Set[int]:
        out: Set[int] = set()
        for part in ("dyclicker", "DynedClicker", "绑定目标窗口"):
            h = self.find_window_by_title(part)
            if h:
                out.add(h)
        return out

    def _monitor_foreground_stable(
        self,
        hold_seconds: float,
        poll_interval: float = 0.2,
        exclude: Optional[Set[int]] = None,
        max_wait: float = 60.0,
        on_tick: Optional[Callable[[float, str], None]] = None,
    ) -> Optional[int]:
        stable_hwnd: Optional[int] = None
        stable_since: Optional[float] = None
        deadline = time.time() + max_wait
        while time.time() < deadline:
            hwnd = self.get_foreground_window()
            if hwnd and self._is_valid_target_hwnd(hwnd, exclude):
                now = time.time()
                if hwnd == stable_hwnd:
                    if on_tick:
                        on_tick(now - (stable_since or now), (win32gui.GetWindowText(hwnd) or "")[:40])
                    if stable_since and (now - stable_since) >= hold_seconds:
                        return hwnd
                else:
                    stable_hwnd = hwnd
                    stable_since = now
            else:
                stable_hwnd = None
                stable_since = None
            time.sleep(poll_interval)
        return None

    def calibrate_from_focus_hold(
        self,
        delay_seconds: float = 3.0,
        hold_seconds: float = 3.0,
        on_hide=None,
        on_restore=None,
        on_tick: Optional[Callable[[float, str], None]] = None,
        log=None,
    ) -> Optional[int]:
        if on_hide:
            on_hide()
        delay_seconds = max(0.0, float(delay_seconds))
        hold_seconds = max(0.5, float(hold_seconds))
        if delay_seconds > 0:
            time.sleep(delay_seconds)
        hwnd = self._monitor_foreground_stable(
            hold_seconds,
            exclude=self._tool_exclude_hwnds(),
            on_tick=on_tick,
        )
        if on_restore:
            on_restore()
        if hwnd:
            self.target_hwnd = hwnd
            self.window_title = win32gui.GetWindowText(hwnd)
            self.window_class = win32gui.GetClassName(hwnd)
            if log:
                log.info("已绑定目标窗口: %s (%s)", self.window_title, self.window_class)
            return hwnd
        if log:
            log.warning("未捕获目标窗口")
        return None

    def focus_target_window(self) -> bool:
        if not self.target_hwnd or not win32gui.IsWindow(self.target_hwnd):
            return False
        try:
            win32gui.ShowWindow(self.target_hwnd, win32con.SW_RESTORE)
            win32gui.SetForegroundWindow(self.target_hwnd)
            return True
        except Exception:
            return False

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
                self.window_title = win32gui.GetWindowText(hwnd)
                return True
        if class_name:
            hwnd = self.find_window_by_class(class_name)
            if hwnd:
                self.target_hwnd = hwnd
                self.window_class = class_name
                return True
        return False

    def persist_to_config(self, config) -> None:
        if not self.target_hwnd:
            return
        config.set("target_window.window_title", self.window_title or "")
        config.set("target_window.window_class", self.window_class or "")

    def capture_window_image(self):
        from PIL import ImageGrab

        if not self.target_hwnd or not win32gui.IsWindow(self.target_hwnd):
            return None
        try:
            left, top, right, bottom = win32gui.GetWindowRect(self.target_hwnd)
            return ImageGrab.grab(bbox=(left, top, right, bottom))
        except Exception:
            return None
