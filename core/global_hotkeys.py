"""Windows 全局热键"""
from __future__ import annotations

import ctypes
import logging
import threading
from ctypes import wintypes
from typing import Callable, List, Optional, Tuple

log = logging.getLogger(__name__)
user32 = ctypes.windll.user32
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000
VK_F1 = 0x70
VK_NAMES = {
    **{f"f{i}": VK_F1 + i - 1 for i in range(1, 13)},
    **{str(i): 0x30 + i for i in range(0, 10)},
    **{chr(c): ord(chr(c).upper()) for c in range(ord("a"), ord("z") + 1)},
}


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", wintypes.POINT),
    ]


def parse_hotkey(spec: str) -> Tuple[int, int]:
    parts = [p.strip().lower() for p in (spec or "").replace(" ", "").split("+") if p.strip()]
    mods = 0
    key_part: Optional[str] = None
    for p in parts:
        if p in ("ctrl", "control", "ctl"):
            mods |= MOD_CONTROL
        elif p == "alt":
            mods |= MOD_ALT
        elif p == "shift":
            mods |= MOD_SHIFT
        elif p in ("win", "windows", "super"):
            mods |= MOD_WIN
        else:
            if key_part is not None:
                raise ValueError(f"multiple keys: {spec}")
            key_part = p
    if not key_part:
        raise ValueError(f"no key: {spec}")
    vk = VK_NAMES.get(key_part)
    if vk is None:
        raise ValueError(f"unknown key: {key_part}")
    return mods, vk


def format_hotkey_label(spec: str) -> str:
    return (spec or "").strip().replace("ctrl", "Ctrl").replace("Control", "Ctrl")


class WinGlobalHotkeys:
    def __init__(self):
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._hwnd: Optional[int] = None
        self._handlers: dict[int, Callable[[], None]] = {}
        self._specs: List[Tuple[int, str, int, int]] = []

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def apply(self, bindings: List[Tuple[int, str, Callable[[], None]]]) -> List[str]:
        self.stop(wait=True)
        self._handlers.clear()
        self._specs.clear()
        errors: List[str] = []
        for hid, spec, cb in bindings:
            spec = (spec or "").strip()
            if not spec:
                continue
            try:
                mod, vk = parse_hotkey(spec)
            except ValueError as e:
                errors.append(f"{spec}: {e}")
                continue
            self._handlers[hid] = cb
            self._specs.append((hid, spec, mod, vk))
        if self._specs:
            self._stop.clear()
            self._thread = threading.Thread(target=self._message_loop, daemon=True)
            self._thread.start()
        return errors

    def stop(self, wait: bool = False) -> None:
        self._stop.set()
        if self._hwnd:
            try:
                user32.PostMessageW(self._hwnd, WM_QUIT, 0, 0)
            except Exception:
                pass
        if wait and self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        self._thread = None
        self._hwnd = None

    def _message_loop(self) -> None:
        hwnd = user32.CreateWindowExW(0, "Static", None, 0, 0, 0, 0, 0, None, None, None, None)
        if not hwnd:
            return
        self._hwnd = hwnd
        for hid, spec, mod, vk in self._specs:
            if not user32.RegisterHotKey(hwnd, hid, mod | MOD_NOREPEAT, vk):
                self._handlers.pop(hid, None)
                log.warning("RegisterHotKey failed: %s", spec)
        msg = MSG()
        while not self._stop.is_set():
            ret = user32.GetMessageW(ctypes.byref(msg), hwnd, 0, 0)
            if ret <= 0:
                break
            if msg.message == WM_HOTKEY:
                cb = self._handlers.get(int(msg.wParam))
                if cb:
                    try:
                        cb()
                    except Exception:
                        log.exception("hotkey callback")
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        for hid, _, _, _ in self._specs:
            try:
                user32.UnregisterHotKey(hwnd, hid)
            except Exception:
                pass
        try:
            user32.DestroyWindow(hwnd)
        except Exception:
            pass
        self._hwnd = None
