"""dyclicker 主界面（tkinter + ttk）"""
from __future__ import annotations

import os
import sys
import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from config.config_manager import ConfigManager
from core.focus_monitor import FocusMonitor
from core.global_hotkeys import WinGlobalHotkeys, format_hotkey_label
from core.logging_setup import setup_logging
from core.mouse.window_tools import WindowManager
from core.ocr.page_detect import ocr_target_window
from core.vision.ocr_setup import configure_tesseract, get_tesseract_status
from core.workflow.runner import DyclickerRunner
from gui.coords_window import CoordsWindow
from gui.log_view import GuiLogBus, LogPanelController, StdoutToGui
from gui.window_bind_dialog import run_window_bind_dialog


class DyclickerApp:
    def __init__(self):
        self.config = ConfigManager()
        self.root = tk.Tk()
        self.root.title("dyclicker")
        self.root.geometry("720x780")
        self.root.minsize(640, 680)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._stop_event: threading.Event | None = None
        self._task_thread: threading.Thread | None = None
        self._runner: DyclickerRunner | None = None
        self._focus_monitor: FocusMonitor | None = None
        self._wm = WindowManager()
        self._hotkeys = WinGlobalHotkeys()
        self._original_stdout = sys.stdout
        self._running = False
        self._logger = None

        self._build_ui()
        self._setup_log_panel()
        self._setup_hotkeys()
        self._refresh_summary()
        self._init_ocr()

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=8)
        outer.pack(fill=tk.BOTH, expand=True)

        ttk.Label(outer, text="dyclicker — 音频监测 · OCR · 鼠标自动化", font=("", 11, "bold")).pack(
            anchor=tk.W, pady=(0, 6)
        )

        summary = ttk.LabelFrame(outer, text="当前配置", padding=6)
        summary.pack(fill=tk.X, pady=(0, 8))
        self.target_var = tk.StringVar(value="未绑定")
        self.exit_var = tk.StringVar(value="")
        ttk.Label(summary, text="目标窗口:").grid(row=0, column=0, sticky=tk.W, padx=4, pady=2)
        ttk.Label(summary, textvariable=self.target_var, wraplength=520).grid(row=0, column=1, sticky=tk.W)
        ttk.Label(summary, text="定时退出:").grid(row=1, column=0, sticky=tk.W, padx=4, pady=2)
        ttk.Label(summary, textvariable=self.exit_var).grid(row=1, column=1, sticky=tk.W)

        opts = ttk.LabelFrame(outer, text="运行参数", padding=6)
        opts.pack(fill=tk.X, pady=(0, 8))

        self.vt_var = tk.IntVar(value=int(self.config.get("dyclicker.video_review_cycles", 0)))
        self.delay_var = tk.DoubleVar(value=float(self.config.get("dyclicker.step_click_delay", 2.0)))
        self.silence_var = tk.DoubleVar(value=float(self.config.get("dyclicker.silence_duration", 5.0)))
        self.exit_at_var = tk.StringVar(value=str(self.config.get("auto_exit.at") or ""))

        row = ttk.Frame(opts)
        row.pack(fill=tk.X, pady=2)
        ttk.Label(row, text="Video review 次数:").pack(side=tk.LEFT)
        ttk.Spinbox(row, from_=0, to=999, width=6, textvariable=self.vt_var).pack(side=tk.LEFT, padx=4)
        ttk.Label(row, text="(0=无限)", foreground="#666").pack(side=tk.LEFT)

        row2 = ttk.Frame(opts)
        row2.pack(fill=tk.X, pady=2)
        ttk.Label(row2, text="Step 停顿(秒):").pack(side=tk.LEFT)
        ttk.Spinbox(row2, from_=0.5, to=30, increment=0.5, width=6, textvariable=self.delay_var).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Label(row2, text="静音阈值(秒):").pack(side=tk.LEFT, padx=(12, 0))
        ttk.Spinbox(row2, from_=1, to=30, increment=0.5, width=6, textvariable=self.silence_var).pack(
            side=tk.LEFT, padx=4
        )

        row3 = ttk.Frame(opts)
        row3.pack(fill=tk.X, pady=2)
        ttk.Label(row3, text="定时退出:").pack(side=tk.LEFT)
        ttk.Entry(row3, textvariable=self.exit_at_var, width=22).pack(side=tk.LEFT, padx=4)
        ttk.Label(row3, text="YYYY-MM-DD HH:MM:SS", foreground="#666").pack(side=tk.LEFT)

        btns = ttk.Frame(outer)
        btns.pack(fill=tk.X, pady=(0, 8))
        start_hk = format_hotkey_label(self.config.get("dyclicker.start_hotkey", "F9"))
        stop_hk = format_hotkey_label(self.config.get("dyclicker.stop_hotkey", "F10"))
        ocr_hk = format_hotkey_label(self.config.get("dyclicker.page_ocr_hotkey", "Ctrl+F2"))

        self.start_btn = ttk.Button(btns, text=f"开始 ({start_hk})", command=self._start)
        self.start_btn.pack(side=tk.LEFT, padx=(0, 6))
        self.stop_btn = ttk.Button(btns, text=f"停止 ({stop_hk})", command=self._stop, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(btns, text=f"页面识别 ({ocr_hk})", command=self._page_ocr).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(btns, text="绑定目标窗口", command=self._calibrate_window).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(btns, text="坐标配置", command=self._open_coords).pack(side=tk.LEFT)

        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(outer, textvariable=self.status_var, foreground="#333").pack(anchor=tk.W, pady=(0, 4))

        log_frame = ttk.LabelFrame(outer, text="运行日志", padding=4)
        log_frame.pack(fill=tk.BOTH, expand=True)
        self.log_text = scrolledtext.ScrolledText(log_frame, height=16, state=tk.DISABLED, wrap=tk.WORD)
        self.log_text.pack(fill=tk.BOTH, expand=True)

    def _setup_log_panel(self) -> None:
        max_lines = int(self.config.get("logging.gui_max_lines", 2000))
        self._log_panel = LogPanelController(self.log_text, self.root, max_lines=max_lines)
        GuiLogBus.set_active(True, self._log_panel.append)
        sys.stdout = StdoutToGui(self._original_stdout)
        self._log_panel.log_system("dyclicker 已就绪")

    def _init_ocr(self) -> None:
        configure_tesseract(self.config)
        ok, msg, _ = get_tesseract_status(self.config)
        self._log_panel.log_system(f"[OCR] {msg.split(chr(10))[0]}")

    def _setup_hotkeys(self) -> None:
        def wrap(fn):
            return lambda: self.root.after(0, fn)

        bindings = [
            (1, self.config.get("dyclicker.start_hotkey", "F9"), wrap(self._start)),
            (2, self.config.get("dyclicker.stop_hotkey", "F10"), wrap(self._stop)),
            (3, self.config.get("dyclicker.page_ocr_hotkey", "Ctrl+F2"), wrap(self._page_ocr)),
        ]
        errors = self._hotkeys.apply(bindings)
        for e in errors:
            self._log_panel.log_system(f"[热键] 注册失败: {e}")

    def _refresh_summary(self) -> None:
        title = self.config.get("target_window.window_title") or "未绑定"
        self.target_var.set(title)
        at = self.config.get("auto_exit.at") or ""
        self.exit_var.set(at or "未设置")

    def _persist_options(self) -> None:
        self.config.set("dyclicker.video_review_cycles", max(0, int(self.vt_var.get())))
        self.config.set("dyclicker.step_click_delay", float(self.delay_var.get()))
        self.config.set("dyclicker.silence_duration", float(self.silence_var.get()))
        at = self.exit_at_var.get().strip()
        if at:
            self.config.set("auto_exit.at", at)
            self.config.set("auto_exit.enabled", True)
        self.config.save()
        self._refresh_summary()

    def _set_running(self, running: bool) -> None:
        self._running = running
        self.start_btn.configure(state=tk.DISABLED if running else tk.NORMAL)
        self.stop_btn.configure(state=tk.NORMAL if running else tk.DISABLED)
        self.status_var.set("运行中…" if running else "就绪")

    def _hide_gui_for_run(self, hide: bool) -> None:
        if not bool(self.config.get("dyclicker.hide_gui_while_running", True)):
            return
        if hide:
            self.root.withdraw()
        else:
            self.root.deiconify()
            self.root.lift()

    def _calibrate_window(self) -> None:
        if self._running:
            messagebox.showwarning("提示", "请先停止运行", parent=self.root)
            return
        run_window_bind_dialog(
            self.root,
            self._wm,
            self.config,
            self._log_panel,
            on_complete=self._refresh_summary,
        )

    def _open_coords(self) -> None:
        CoordsWindow(self.root, self.config, self._log_panel)

    def _page_ocr(self) -> None:
        if not self._wm.ensure_target_window(self.config):
            messagebox.showwarning("提示", "请先绑定目标窗口", parent=self.root)
            return
        logger = setup_logging(self.config, role="dyclicker")

        def work():
            text, step1 = ocr_target_window(self._wm, self.config, logger)
            snippet = (text or "").replace("\n", " ")[:120]
            self.root.after(
                0,
                lambda: self._log_panel.log_system(
                    f"[OCR 测试] step1={step1} 片段: {snippet or '(空)'}"
                ),
            )

        threading.Thread(target=work, daemon=True).start()

    def _on_focus_lost(self) -> None:
        if self._stop_event:
            self._stop_event.set()
        self.root.after(0, self._on_focus_lost_ui)

    def _on_focus_lost_ui(self) -> None:
        self._set_running(False)
        self.status_var.set("已停止（失焦）")
        self._hide_gui_for_run(False)
        self._log_panel.log_system("目标窗口已失焦，已停止运行")

    def _start(self) -> None:
        if self._running:
            return
        self._persist_options()
        if not self._wm.ensure_target_window(self.config):
            messagebox.showerror("错误", "请先绑定目标窗口", parent=self.root)
            return

        self._stop_event = threading.Event()
        self._logger = setup_logging(self.config, role="dyclicker")
        self._runner = DyclickerRunner(self.config, self._logger, self._stop_event)
        ok, msg = self._runner.is_ready()
        if not ok:
            messagebox.showerror("错误", msg, parent=self.root)
            return

        self._focus_monitor = FocusMonitor(
            self.config,
            self._wm,
            self._logger,
            on_focus_lost=self._on_focus_lost,
            pause_on_focus_loss=False,
        )
        self._hide_gui_for_run(True)
        self._focus_monitor.start()
        self._set_running(True)
        self._logger.info("用户启动 dyclicker (F9)")

        def work():
            try:
                self._runner.run()
            finally:
                if self._focus_monitor:
                    self._focus_monitor.stop()
                self.root.after(0, lambda: self._finish_run())

        self._task_thread = threading.Thread(target=work, daemon=True, name="dyclicker-runner")
        self._task_thread.start()

    def _finish_run(self) -> None:
        self._set_running(False)
        self._hide_gui_for_run(False)
        if self._stop_event and self._stop_event.is_set():
            self._log_panel.log_system("dyclicker 已停止")

    def _stop(self) -> None:
        if self._stop_event:
            self._stop_event.set()
        if self._focus_monitor:
            self._focus_monitor.stop()
        if self._logger:
            self._logger.info("用户停止 dyclicker (F10)")

    def _on_close(self) -> None:
        self._stop()
        self._hotkeys.stop(wait=True)
        GuiLogBus.set_active(False)
        sys.stdout = self._original_stdout
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def launch_gui() -> None:
    DyclickerApp().run()
