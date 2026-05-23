"""Ctrl+F8 坐标热键采样"""
from __future__ import annotations

from typing import Callable, Optional

import win32api

from core.global_hotkeys import WinGlobalHotkeys, format_hotkey_label


class CoordHotkeySampler:
    HOTKEY_ID = 10

    def __init__(self, root, config, log_panel):
        self.root = root
        self.config = config
        self.log_panel = log_panel
        self._hotkeys = WinGlobalHotkeys()
        self._pending_label: Optional[str] = None
        self._pending_apply: Optional[Callable[[int, int], None]] = None
        self._hotkey_spec = config.get("dyclicker.coord_sample_hotkey", "Ctrl+F8")

    @property
    def hotkey_label(self) -> str:
        return format_hotkey_label(self._hotkey_spec)

    def start(self) -> None:
        errors = self._hotkeys.apply([(self.HOTKEY_ID, self._hotkey_spec, self._on_hotkey)])
        for e in errors:
            self.log_panel.log_system(f"[坐标热键] 注册失败: {e}")

    def stop(self) -> None:
        self._pending_label = None
        self._pending_apply = None
        self._hotkeys.stop(wait=True)

    def arm(self, label: str, apply_fn: Callable[[int, int], None]) -> None:
        self._pending_label = label
        self._pending_apply = apply_fn
        self.log_panel.log_system(
            f"[坐标] 已选取「{label}」— 移动鼠标到目标位置，按 {self.hotkey_label} 确定"
        )

    def cancel_arm(self) -> None:
        if self._pending_label:
            self.log_panel.log_system(f"[坐标] 已取消选取「{self._pending_label}」")
        self._pending_label = None
        self._pending_apply = None

    @property
    def pending_label(self) -> Optional[str]:
        return self._pending_label

    def _on_hotkey(self) -> None:
        if not self._pending_apply:
            self.root.after(
                0,
                lambda: self.log_panel.log_system(
                    f"[坐标] 请先点击「选取」再按 {self.hotkey_label}"
                ),
            )
            return
        try:
            x, y = win32api.GetCursorPos()
        except Exception as exc:
            self.root.after(0, lambda: self.log_panel.log_system(f"[坐标] 读取鼠标失败: {exc}"))
            return
        label = self._pending_label or ""
        apply_fn = self._pending_apply
        self.root.after(0, lambda: self._apply(label, apply_fn, int(x), int(y)))

    def _apply(self, label: str, apply_fn: Callable[[int, int], None], x: int, y: int) -> None:
        apply_fn(x, y)
        self._pending_label = None
        self._pending_apply = None
        self.log_panel.log_system(f"[坐标] {label} → ({x}, {y})")
