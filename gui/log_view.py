"""
GUI 交互日志：线程安全地显示 logging 与 print 输出
"""
import logging
import queue
import sys
from datetime import datetime
from typing import Callable, Optional


class GuiLogBus:
    """全局日志总线，供 logging Handler 与 stdout 重定向使用"""

    _active = False
    _callback: Optional[Callable[[str, str], None]] = None

    @classmethod
    def set_active(cls, active: bool, callback: Optional[Callable[[str, str], None]] = None):
        cls._active = active
        if callback is not None:
            cls._callback = callback
        if not active:
            cls._callback = None

    @classmethod
    def is_active(cls) -> bool:
        return cls._active and cls._callback is not None

    @classmethod
    def post(cls, level: str, message: str):
        if not cls.is_active() or not message:
            return
        try:
            cls._callback(level, message)
        except Exception:
            pass


class GuiLogHandler(logging.Handler):
    """将 logging 记录转发到 GuiLogBus"""

    def __init__(self):
        super().__init__()
        self.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
        )

    def emit(self, record: logging.LogRecord):
        try:
            msg = self.format(record)
            GuiLogBus.post(record.levelname, msg)
        except Exception:
            self.handleError(record)


class StdoutToGui:
    """把 print 输出重定向到 GUI 日志区"""

    def __init__(self, original):
        self._original = original

    def write(self, text: str):
        if text and text.strip():
            GuiLogBus.post("INFO", text.rstrip("\n"))
        if self._original:
            try:
                self._original.write(text)
            except Exception:
                pass

    def flush(self):
        if self._original:
            try:
                self._original.flush()
            except Exception:
                pass

    def isatty(self):
        return False


class LogPanelController:
    """管理 Tk Text 控件的追加与行数限制"""

    def __init__(self, text_widget, root, max_lines: int = 2000):
        self.text = text_widget
        self.root = root
        self.max_lines = max_lines
        self._queue: queue.Queue = queue.Queue()
        self._poll_interval_ms = 80
        self._level_tags = {
            "DEBUG": "level_debug",
            "INFO": "level_info",
            "WARNING": "level_warning",
            "ERROR": "level_error",
            "CRITICAL": "level_critical",
        }
        self._configure_tags()
        self.root.after(self._poll_interval_ms, self._drain_queue)

    def _configure_tags(self):
        self.text.tag_configure("level_debug", foreground="#666666")
        self.text.tag_configure("level_info", foreground="#1a1a1a")
        self.text.tag_configure("level_warning", foreground="#b8860b")
        self.text.tag_configure("level_error", foreground="#c0392b")
        self.text.tag_configure("level_critical", foreground="#ffffff", background="#c0392b")

    def append(self, level: str, message: str):
        self._queue.put((level.upper(), message))

    def _drain_queue(self):
        try:
            while True:
                level, message = self._queue.get_nowait()
                self._append_line(level, message)
        except queue.Empty:
            pass
        self.root.after(self._poll_interval_ms, self._drain_queue)

    def _append_line(self, level: str, message: str):
        tag = self._level_tags.get(level, "level_info")
        self.text.configure(state="normal")
        self.text.insert("end", message + "\n", tag)
        self.text.see("end")
        self.text.configure(state="disabled")
        line_count = int(self.text.index("end-1c").split(".")[0])
        if line_count > self.max_lines:
            self.text.configure(state="normal")
            self.text.delete("1.0", f"{line_count - self.max_lines}.0")
            self.text.configure(state="disabled")

    def clear(self):
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.configure(state="disabled")

    def log_system(self, message: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self.append("INFO", f"{ts} [系统] {message}")
