"""
C 模式 GUI（与 A/B 完全隔离）
"""
import threading
import tkinter as tk
from tkinter import messagebox, ttk


class CModePanel:
    """C 模式界面：目标窗口、点击区域、监测任务"""

    def __init__(self, parent, config, root, log_panel, on_running_change=None):
        self.parent = parent
        self.config = config
        self.root = root
        self._log_panel = log_panel
        self._on_running_change = on_running_change
        self._thread = None
        self._stop_event = None
        self._runner = None

        self.win_title_var = tk.StringVar(value="（未配置）")
        self.win_class_var = tk.StringVar(value="")
        self.click_coord_var = tk.StringVar(value="(0, 0)")
        self.c_task_status_var = tk.StringVar(value="监测未启动")

        self._build()

    def _build(self):
        pad = {"padx": 6, "pady": 3}
        nb = ttk.Notebook(self.parent)
        nb.pack(fill=tk.BOTH, expand=True)

        tab_task = ttk.Frame(nb, padding=8)
        tab_setup = ttk.Frame(nb, padding=8)
        nb.add(tab_task, text="静音点击")
        nb.add(tab_setup, text="目标与点击区域")
        nb.select(tab_task)

        ttk.Label(
            tab_task,
            text="C 模式：本机无音频播放（静音）时自动点击一次",
            font=("", 10, "bold"),
            wraplength=560,
        ).pack(anchor=tk.W, pady=(0, 8))

        ttk.Label(
            tab_task,
            text="与 A/B 协同无关，无需网络。需先完成「目标与点击区域」矫正。",
            foreground="#666",
            wraplength=560,
        ).pack(anchor=tk.W, pady=(0, 10))

        btn_f = ttk.Frame(tab_task)
        btn_f.pack(fill=tk.X)
        self.btn_c_start = ttk.Button(btn_f, text="开始监测", width=12, command=self._start)
        self.btn_c_start.pack(side=tk.LEFT, padx=3)
        self.btn_c_stop = ttk.Button(
            btn_f, text="停止", width=10, command=self._stop, state=tk.DISABLED
        )
        self.btn_c_stop.pack(side=tk.LEFT, padx=3)
        ttk.Label(tab_task, textvariable=self.c_task_status_var, foreground="#333").pack(
            anchor=tk.W, pady=(12, 0)
        )

        ttk.Label(tab_setup, text="目标程序与点击位置", font=("", 10, "bold")).grid(
            row=0, column=0, columnspan=2, sticky=tk.W, pady=(0, 6)
        )
        ttk.Label(tab_setup, text="标题:").grid(row=1, column=0, sticky=tk.W, **pad)
        ttk.Label(tab_setup, textvariable=self.win_title_var, wraplength=480).grid(
            row=1, column=1, sticky=tk.W, **pad
        )
        ttk.Label(tab_setup, text="类名:").grid(row=2, column=0, sticky=tk.W, **pad)
        ttk.Label(tab_setup, textvariable=self.win_class_var, wraplength=480).grid(
            row=2, column=1, sticky=tk.W, **pad
        )
        win_btn = ttk.Frame(tab_setup)
        win_btn.grid(row=3, column=0, columnspan=2, sticky=tk.W, **pad)
        ttk.Button(win_btn, text="确认目标窗口", command=self._calibrate_window).pack(
            side=tk.LEFT, padx=(0, 6)
        )

        ttk.Separator(tab_setup, orient=tk.HORIZONTAL).grid(
            row=4, column=0, columnspan=2, sticky=tk.EW, pady=8
        )
        ttk.Label(tab_setup, text="静音时点击位置 (x, y):").grid(row=5, column=0, sticky=tk.W, **pad)
        ttk.Label(tab_setup, textvariable=self.click_coord_var).grid(row=5, column=1, sticky=tk.W, **pad)
        ttk.Button(tab_setup, text="矫正点击位置", command=self._calibrate_click).grid(
            row=6, column=0, columnspan=2, sticky=tk.W, **pad
        )

    def refresh_display(self):
        title = self.config.get("target_window.window_title", "") or "（未配置）"
        cls = self.config.get("target_window.window_class", "") or "—"
        self.win_title_var.set(title)
        self.win_class_var.set(cls)
        c = self.config.get("c_mode.click", {"x": 0, "y": 0})
        x, y = c.get("x", 0), c.get("y", 0)
        ok = "✓" if x or y else "○"
        self.click_coord_var.set(f"{ok} ({x}, {y})")

    def _calibrate_window(self):
        from main import CModeTool
        tool = CModeTool(self.config, gui_parent=self.root)
        self.root.withdraw()
        try:
            tool.calibrate_window()
        finally:
            self.root.deiconify()
        self.refresh_display()
        self._log_panel.log_system("[C 模式] 目标窗口已更新")

    def _calibrate_click(self):
        from main import CModeTool
        tool = CModeTool(self.config, gui_parent=self.root)
        self.root.withdraw()
        try:
            tool.calibrate_click()
        finally:
            self.root.deiconify()
        self.refresh_display()
        self._log_panel.log_system("[C 模式] 点击位置已矫正")

    def _set_running(self, running: bool):
        self.btn_c_start.config(state=tk.DISABLED if running else tk.NORMAL)
        self.btn_c_stop.config(state=tk.NORMAL if running else tk.DISABLED)
        if self._on_running_change:
            self._on_running_change(running)

    def _start(self):
        if self._thread and self._thread.is_alive():
            return
        c = self.config.get("c_mode.click", {"x": 0, "y": 0})
        if not c.get("x", 0) and not c.get("y", 0):
            messagebox.showerror("错误", "请先矫正点击位置", parent=self.root)
            return
        from core.c_mode import CModeRunner
        from core.logging_setup import setup_logging

        self._stop_event = threading.Event()
        logger = setup_logging(self.config, role="c")
        self._runner = CModeRunner(self.config, logger, self._stop_event)
        self._thread = threading.Thread(target=self._runner.run, daemon=True)
        self._thread.start()
        self.c_task_status_var.set("监测运行中…")
        self._set_running(True)
        self._log_panel.log_system("[C 模式] 监测已启动")

    def _stop(self):
        if self._stop_event:
            self._stop_event.set()
        if self._runner:
            self._runner.stop()
        self._runner = None
        self.c_task_status_var.set("监测已停止")
        self._set_running(False)
        self._log_panel.log_system("[C 模式] 监测已停止")

    def stop_all(self):
        self._stop()

    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())
