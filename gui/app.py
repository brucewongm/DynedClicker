"""
图形界面：分区功能 + 任务控制 + 交互日志
"""
import os
import socket
import sys
import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from config.config_manager import ConfigManager
from gui.c_panel import CModePanel
from gui.log_view import GuiLogBus, LogPanelController, StdoutToGui

REGION_DISPLAY = (
    ("record", "录音 record"),
    ("play", "播放 play"),
    ("repeat", "重复 repeat"),
    ("continue", "继续 continue"),
)


class AutomationGUI:
    """Tkinter 主界面"""

    def __init__(self):
        self.config = ConfigManager()
        self._task_thread = None
        self._task_stop_event = None
        self._pause_event = threading.Event()
        self._task_runner = None
        self._conn_stop_event = threading.Event()
        self._connection_service = None
        self._original_stdout = sys.stdout
        self._region_vars = {}
        self.c_panel = None
        self.frame_ab = None
        self.frame_c = None

        self.root = tk.Tk()
        self.root.title("Dy 音频自动化工具 (audioauto)")
        self.root.geometry("700x780")
        self.root.minsize(640, 680)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._build_ui()
        self._setup_log_panel()
        self.c_panel = CModePanel(
            self.frame_c,
            self.config,
            self.root,
            self._log_panel,
        )
        self._load_config_to_ui()
        self._refresh_target_display()
        self._apply_app_profile(initial=True)

    def _build_ui(self):
        self.conn_status_var = tk.StringVar(value="搜索中…")
        self.app_profile_var = tk.StringVar(value="ab")

        outer = ttk.Frame(self.root, padding=6)
        outer.pack(fill=tk.BOTH, expand=True)

        profile_bar = ttk.LabelFrame(outer, text="应用模式（A/B 与 C 互斥）", padding=8)
        profile_bar.pack(fill=tk.X, pady=(0, 6))
        pf = ttk.Frame(profile_bar)
        pf.pack(fill=tk.X)
        ttk.Radiobutton(
            pf,
            text="A/B 协同模式",
            variable=self.app_profile_var,
            value="ab",
            command=self._on_app_profile_changed,
        ).pack(side=tk.LEFT)
        ttk.Radiobutton(
            pf,
            text="C 独立模式（静音点击）",
            variable=self.app_profile_var,
            value="c",
            command=self._on_app_profile_changed,
        ).pack(side=tk.LEFT, padx=16)
        ttk.Label(
            profile_bar,
            text="两种模式不可同时使用；切换前将自动停止当前侧任务与连接。",
            foreground="#666",
        ).pack(anchor=tk.W, pady=(6, 0))

        paned = ttk.PanedWindow(outer, orient=tk.VERTICAL)
        paned.pack(fill=tk.BOTH, expand=True)

        self.content_host = ttk.Frame(paned)
        paned.add(self.content_host, weight=2)

        log_outer = ttk.LabelFrame(paned, text="日志（始终显示）", padding=4)
        paned.add(log_outer, weight=3)

        self.frame_ab = ttk.Frame(self.content_host)
        self.frame_c = ttk.Frame(self.content_host)

        self.notebook = ttk.Notebook(self.frame_ab)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        tab_task = ttk.Frame(self.notebook, padding=8)
        tab_target = ttk.Frame(self.notebook, padding=8)
        tab_network = ttk.Frame(self.notebook, padding=8)

        self.notebook.add(tab_task, text="任务执行")
        self.notebook.add(tab_target, text="目标与区域")
        self.notebook.add(tab_network, text="模式与网络")
        self.notebook.select(tab_task)

        pad = {"padx": 6, "pady": 3}
        self._build_func2(tab_network, pad)
        self._build_func1(tab_target, pad)
        self._build_func3(tab_task, pad)

        log_toolbar = ttk.Frame(log_outer)
        log_toolbar.pack(fill=tk.X, pady=(0, 4))
        ttk.Button(log_toolbar, text="清空日志", width=10, command=self._clear_log).pack(side=tk.RIGHT)

        self.log_text = scrolledtext.ScrolledText(
            log_outer,
            height=12,
            wrap=tk.WORD,
            state="disabled",
            font=("Consolas", 9),
        )
        self.log_text.pack(fill=tk.BOTH, expand=True)

    def _on_app_profile_changed(self):
        if self.c_panel and self.c_panel.is_running():
            messagebox.showwarning("提示", "请先停止 C 模式监测", parent=self.root)
            self.app_profile_var.set("c")
            return
        if self._task_thread and self._task_thread.is_alive():
            messagebox.showwarning("提示", "请先停止 A/B 任务", parent=self.root)
            self.app_profile_var.set("ab")
            return
        self._apply_app_profile()

    def _stop_ab_all(self):
        self._stop_task()
        self._conn_stop_event.set()
        if self._connection_service:
            self._connection_service.stop()
            self._connection_service = None
        self._conn_stop_event = threading.Event()

    def _apply_app_profile(self, initial: bool = False):
        profile = self.app_profile_var.get()
        self.config.set("gui.app_profile", profile)

        if profile == "c":
            self._stop_ab_all()
            self.frame_ab.pack_forget()
            self.frame_c.pack(fill=tk.BOTH, expand=True)
            if self.c_panel:
                self.c_panel.refresh_display()
            self.root.title("Dy 音频自动化 · C 模式")
            self._log_panel.log_system("已切换到 C 独立模式")
        else:
            if self.c_panel:
                self.c_panel.stop_all()
            self.frame_c.pack_forget()
            self.frame_ab.pack(fill=tk.BOTH, expand=True)
            self.root.title("Dy 音频自动化 · A/B 协同")
            self._log_panel.log_system("已切换到 A/B 协同模式")
            self._conn_stop_event = threading.Event()
            if not initial:
                self.root.after(200, self._start_connection_service)
            else:
                self.root.after(300, self._start_connection_service)

    def _build_func1(self, parent, pad):
        ttk.Label(
            parent,
            text="目标程序与按钮区域校正",
            font=("", 10, "bold"),
        ).grid(row=0, column=0, columnspan=3, sticky=tk.W, pady=(0, 6))

        f1 = parent
        ttk.Label(f1, text="目标程序窗口", font=("", 9, "bold")).grid(row=1, column=0, columnspan=3, sticky=tk.W, **pad)
        self.win_title_var = tk.StringVar(value="（未配置）")
        self.win_class_var = tk.StringVar(value="")
        ttk.Label(f1, text="标题:").grid(row=2, column=0, sticky=tk.W, **pad)
        ttk.Label(f1, textvariable=self.win_title_var, wraplength=480).grid(row=2, column=1, columnspan=2, sticky=tk.W, **pad)
        ttk.Label(f1, text="类名:").grid(row=3, column=0, sticky=tk.W, **pad)
        ttk.Label(f1, textvariable=self.win_class_var, wraplength=480).grid(row=3, column=1, columnspan=2, sticky=tk.W, **pad)

        win_btn = ttk.Frame(f1)
        win_btn.grid(row=4, column=0, columnspan=3, sticky=tk.W, **pad)
        ttk.Button(win_btn, text="确认目标窗口", command=self._calibrate_window).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(win_btn, text="矫正全部按钮", command=self._calibrate_all_regions).pack(side=tk.LEFT)

        ttk.Separator(f1, orient=tk.HORIZONTAL).grid(row=5, column=0, columnspan=3, sticky=tk.EW, pady=6)

        ttk.Label(f1, text="点击区域 (x, y)", font=("", 9, "bold")).grid(row=6, column=0, columnspan=3, sticky=tk.W, **pad)
        ttk.Label(f1, text="按钮", width=14).grid(row=7, column=0, sticky=tk.W, **pad)
        ttk.Label(f1, text="坐标").grid(row=7, column=1, sticky=tk.W, **pad)
        ttk.Label(f1, text="操作").grid(row=7, column=2, sticky=tk.W, **pad)

        for i, (key, label) in enumerate(REGION_DISPLAY):
            row = 8 + i
            ttk.Label(f1, text=label).grid(row=row, column=0, sticky=tk.W, **pad)
            coord_var = tk.StringVar(value="(0, 0)")
            self._region_vars[key] = coord_var
            ttk.Label(f1, textvariable=coord_var, width=16).grid(row=row, column=1, sticky=tk.W, **pad)
            ttk.Button(f1, text="矫正", width=8, command=lambda k=key: self._calibrate_region(k)).grid(
                row=row, column=2, sticky=tk.W, **pad
            )

    def _build_func2(self, parent, pad):
        ttk.Label(
            parent,
            text="运行模式与网络配置",
            font=("", 10, "bold"),
        ).grid(row=0, column=0, columnspan=2, sticky=tk.W, pady=(0, 8))

        f2 = parent
        self.mode_var = tk.StringVar(value="master")
        mode_f = ttk.Frame(f2)
        mode_f.grid(row=1, column=0, columnspan=2, sticky=tk.W, **pad)
        ttk.Radiobutton(mode_f, text="A 模式 (Master)", variable=self.mode_var, value="master").pack(side=tk.LEFT)
        ttk.Radiobutton(mode_f, text="B 模式 (Slave)", variable=self.mode_var, value="slave").pack(side=tk.LEFT, padx=14)
        self.mode_var.trace_add("write", self._on_mode_changed)

        self.ip_label = ttk.Label(f2, text="绑定 IP (bind_ip):")
        self.ip_label.grid(row=2, column=0, sticky=tk.W, **pad)
        ip_row = ttk.Frame(f2)
        ip_row.grid(row=2, column=1, sticky=tk.W, **pad)
        self.ip_var = tk.StringVar()
        ttk.Entry(ip_row, textvariable=self.ip_var, width=22).pack(side=tk.LEFT)
        self.btn_use_all = ttk.Button(ip_row, text="0.0.0.0", width=8, command=self._fill_bind_all)
        self.btn_use_all.pack(side=tk.LEFT, padx=(6, 0))

        ttk.Label(f2, text="端口:").grid(row=3, column=0, sticky=tk.W, **pad)
        self.port_var = tk.StringVar()
        ttk.Entry(f2, textvariable=self.port_var, width=10).grid(row=3, column=1, sticky=tk.W, **pad)

        self.ip_hint_var = tk.StringVar()
        ttk.Label(f2, textvariable=self.ip_hint_var, foreground="#555", wraplength=620).grid(
            row=4, column=0, columnspan=2, sticky=tk.W, padx=6, pady=2
        )

        ttk.Button(f2, text="保存网络配置", command=self._save_network_only).grid(
            row=5, column=0, columnspan=2, sticky=tk.W, **pad
        )

        ttk.Separator(f2, orient=tk.HORIZONTAL).grid(row=6, column=0, columnspan=2, sticky=tk.EW, pady=8)
        ttk.Label(f2, text="连接状态", font=("", 9, "bold")).grid(row=7, column=0, sticky=tk.W, **pad)
        self.conn_status_label_net = ttk.Label(f2, textvariable=self.conn_status_var, font=("", 10))
        self.conn_status_label_net.grid(row=7, column=1, sticky=tk.W, **pad)

    def _build_func3(self, parent, pad):
        conn_box = ttk.LabelFrame(parent, text="连接状态（启动后自动运行）", padding=8)
        conn_box.pack(fill=tk.X, pady=(0, 10))
        self.conn_status_label_task = ttk.Label(
            conn_box, textvariable=self.conn_status_var, font=("", 11, "bold")
        )
        self.conn_status_label_task.pack(anchor=tk.W)
        ttk.Label(
            conn_box,
            text="连接与任务无关；切换模式或保存网络后将自动重连。",
            foreground="#666",
            wraplength=580,
        ).pack(anchor=tk.W, pady=(4, 0))
        ttk.Label(
            parent,
            text="主任务：开始 / 暂停 / 继续 / 停止",
            font=("", 10, "bold"),
        ).pack(anchor=tk.W, pady=(0, 8))

        task_btn = ttk.Frame(parent)
        task_btn.pack(fill=tk.X)
        self.btn_start = ttk.Button(task_btn, text="开始任务", width=12, command=self._start_task)
        self.btn_start.pack(side=tk.LEFT, padx=3)
        self.btn_pause = ttk.Button(task_btn, text="暂停", width=10, command=self._pause_task, state=tk.DISABLED)
        self.btn_pause.pack(side=tk.LEFT, padx=3)
        self.btn_resume = ttk.Button(task_btn, text="继续", width=10, command=self._resume_task, state=tk.DISABLED)
        self.btn_resume.pack(side=tk.LEFT, padx=3)
        self.btn_stop = ttk.Button(task_btn, text="停止", width=10, command=self._stop_task, state=tk.DISABLED)
        self.btn_stop.pack(side=tk.LEFT, padx=3)

        self.task_status_var = tk.StringVar(value="任务未启动")
        ttk.Label(parent, textvariable=self.task_status_var, foreground="#333").pack(anchor=tk.W, pady=(12, 0))

        mode_hint = ttk.LabelFrame(parent, text="当前运行模式（在「模式与网络」页配置）", padding=8)
        mode_hint.pack(fill=tk.X, pady=(12, 0))
        self.task_mode_hint_var = tk.StringVar()
        ttk.Label(mode_hint, textvariable=self.task_mode_hint_var, wraplength=600).pack(anchor=tk.W)

        ttk.Label(
            parent,
            text="暂停将停止：Dy 按钮点击、Slave 录音/变音/播放；继续后从当前流程恢复。",
            foreground="#666",
            wraplength=620,
        ).pack(anchor=tk.W, pady=(12, 0))

    def _setup_log_panel(self):
        self._log_panel = LogPanelController(self.log_text, self.root)
        GuiLogBus.set_active(True, self._log_panel.append)
        sys.stdout = StdoutToGui(self._original_stdout)
        self._log_panel.log_system("Dy 音频自动化工具已启动")

    def _clear_log(self):
        self._log_panel.clear()
        self._log_panel.log_system("日志已清空")

    def _refresh_target_display(self):
        title = self.config.get("target_window.window_title", "") or "（未配置）"
        cls = self.config.get("target_window.window_class", "") or "—"
        self.win_title_var.set(title)
        self.win_class_var.set(cls)
        for key, _ in REGION_DISPLAY:
            c = self.config.get_mouse_region(key)
            x, y = c.get("x", 0), c.get("y", 0)
            ok = "✓" if x or y else "○"
            self._region_vars[key].set(f"{ok} ({x}, {y})")

    @staticmethod
    def _guess_lan_ip() -> str:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                return s.getsockname()[0]
        except OSError:
            return ""

    def _fill_bind_all(self):
        self.ip_var.set("0.0.0.0")
        self._refresh_ip_hint()

    def _update_task_mode_hint(self):
        mode = self.mode_var.get()
        if mode == "master":
            ip = self.ip_var.get() or self.config.get("network.bind_ip", "0.0.0.0")
            self.task_mode_hint_var.set(f"A 模式 (Master) · 绑定 {ip} · 端口 {self.port_var.get()}")
        else:
            ip = self.ip_var.get() or self.config.get("network.master_ip", "")
            self.task_mode_hint_var.set(f"B 模式 (Slave) · Master IP {ip} · 端口 {self.port_var.get()}")

    def _on_mode_changed(self, *_args):
        self._refresh_ip_ui()
        self._load_ip_from_config()
        self._update_task_mode_hint()
        if self._connection_service is not None:
            self._restart_connection_service()

    def _on_conn_status(self, text: str, level: str = "info"):
        def apply():
            self.conn_status_var.set(text)
            color = {"searching": "#b8860b", "connected": "#2e7d32", "error": "#c0392b"}.get(level, "#333333")
            self.conn_status_label_task.config(foreground=color)
            self.conn_status_label_net.config(foreground=color)
        self.root.after(0, apply)

    def _start_connection_service(self):
        if not self._persist_network_from_ui(notify=False):
            self._on_conn_status("连接配置无效", "error")
            return
        mode = self.mode_var.get()
        from core.connection_service import ConnectionService

        self._connection_service = ConnectionService(
            self.config,
            mode,
            self._conn_stop_event,
            on_status=self._on_conn_status,
        )
        if self._connection_service.start():
            self._log_panel.log_system(f"[连接] {mode} 模式连接服务已启动")
        else:
            self._on_conn_status("连接服务启动失败", "error")

    def _restart_connection_service(self):
        if self._task_thread and self._task_thread.is_alive():
            messagebox.showwarning(
                "提示",
                "任务运行中无法切换连接，请先停止任务。",
                parent=self.root,
            )
            self._load_ip_from_config()
            return
        if self._connection_service:
            self._connection_service.stop()
        self._start_connection_service()

    def _refresh_ip_ui(self):
        is_master = self.mode_var.get() == "master"
        if is_master:
            self.ip_label.config(text="绑定 IP (bind_ip):")
            self.btn_use_all.pack(side=tk.LEFT, padx=(6, 0))
        else:
            self.ip_label.config(text="Master IP (master_ip):")
            self.btn_use_all.pack_forget()
        self._refresh_ip_hint()

    def _refresh_ip_hint(self):
        if self.mode_var.get() == "master":
            lan = self._guess_lan_ip()
            self.ip_hint_var.set(
                f"A 模式：推荐 bind_ip=0.0.0.0；Slave 填 Master IP={lan}" if lan
                else "A 模式：推荐 bind_ip=0.0.0.0"
            )
        else:
            self.ip_hint_var.set("B 模式：填 Master 局域网 IPv4，勿用 127.0.0.1")

    def _load_ip_from_config(self):
        if self.mode_var.get() == "master":
            ip = self.config.get("network.bind_ip", "0.0.0.0")
        else:
            ip = self.config.get("network.master_ip", "192.168.1.100")
        self.ip_var.set(str(ip) if ip is not None else "")
        self._refresh_ip_hint()

    def _load_config_to_ui(self):
        profile = self.config.get("gui.app_profile", "ab")
        if profile in ("ab", "c"):
            self.app_profile_var.set(profile)
        saved_mode = self.config.get("gui.last_mode", "master")
        if saved_mode in ("master", "slave"):
            self.mode_var.set(saved_mode)
        self._refresh_ip_ui()
        self._load_ip_from_config()
        self.port_var.set(str(self.config.get("network.port", 8888)))
        self._update_task_mode_hint()
        if self.c_panel:
            self.c_panel.refresh_display()

    def _persist_network_from_ui(self, notify: bool) -> bool:
        ip = self.ip_var.get().strip()
        if not ip:
            messagebox.showerror("错误", "IP 不能为空", parent=self.root)
            return False
        try:
            port = int(self.port_var.get())
        except ValueError:
            messagebox.showerror("错误", "端口必须是数字", parent=self.root)
            return False

        mode = self.mode_var.get()
        if mode == "master":
            self.config.set("network.bind_ip", ip)
            if ip == "0.0.0.0":
                lan = self._guess_lan_ip()
                if lan:
                    self.config.set("network.master_ip", lan)
            else:
                self.config.set("network.master_ip", ip)
        else:
            if ip in ("127.0.0.1", "0.0.0.0", "localhost"):
                messagebox.showerror("错误", "Slave 的 Master IP 无效", parent=self.root)
                return False
            self.config.set("network.master_ip", ip)
        self.config.set("network.port", port)
        self.config.set("gui.last_mode", mode)
        self._log_panel.log_system(f"[功能2] 网络已保存: 模式={mode}, IP={ip}, 端口={port}")
        if notify:
            messagebox.showinfo("保存", "网络配置已写入 config.yaml", parent=self.root)
        return True

    def _save_network_only(self):
        if self._persist_network_from_ui(notify=True):
            self.task_status_var.set("网络配置已保存（未启动任务）")
            self._restart_connection_service()

    def _calibrate_window(self):
        from main import AudioAutomationTool
        tool = AudioAutomationTool(self.config, gui_parent=self.root)
        self.root.withdraw()
        try:
            tool.calibrate_window()
        finally:
            self.root.deiconify()
        self._refresh_target_display()
        self._log_panel.log_system("[功能1] 目标窗口已更新")

    def _calibrate_region(self, region: str):
        from main import AudioAutomationTool
        tool = AudioAutomationTool(self.config, gui_parent=self.root)
        self.root.withdraw()
        try:
            tool.calibrate_region(region)
        finally:
            self.root.deiconify()
        self._refresh_target_display()

    def _calibrate_all_regions(self):
        from main import AudioAutomationTool
        tool = AudioAutomationTool(self.config, gui_parent=self.root)
        self.root.withdraw()
        try:
            tool.run_calibration()
        finally:
            self.root.deiconify()
        self._refresh_target_display()
        self._log_panel.log_system("[功能1] 全部区域矫正完成")

    def _set_task_buttons_running(self, running: bool, paused: bool = False):
        self.btn_start.config(state=tk.DISABLED if running else tk.NORMAL)
        self.btn_stop.config(state=tk.NORMAL if running else tk.DISABLED)
        if not running:
            self.btn_pause.config(state=tk.DISABLED)
            self.btn_resume.config(state=tk.DISABLED)
        elif paused:
            self.btn_pause.config(state=tk.DISABLED)
            self.btn_resume.config(state=tk.NORMAL)
        else:
            self.btn_pause.config(state=tk.NORMAL)
            self.btn_resume.config(state=tk.DISABLED)

    def _start_task(self):
        if self._task_thread and self._task_thread.is_alive():
            messagebox.showwarning("提示", "任务已在运行", parent=self.root)
            return
        if not self._connection_service or not self._connection_service.network:
            messagebox.showwarning("提示", "连接服务未就绪", parent=self.root)
            return
        if not self._connection_service.is_connected():
            messagebox.showwarning(
                "提示",
                "尚未连接到对端，请等待连接成功后再开始任务。",
                parent=self.root,
            )
            return

        mode = self.mode_var.get()
        missing = self.config.list_unconfigured_regions()
        if mode == "master" and missing:
            if not messagebox.askyesno(
                "配置不完整",
                f"未矫正按钮: {', '.join(missing)}\n是否仍开始任务?",
                parent=self.root,
            ):
                return

        self._pause_event.clear()
        self._task_stop_event = threading.Event()
        from main import TaskRunner
        self._task_runner = TaskRunner(
            self.config,
            mode,
            self._connection_service.network,
            self._task_stop_event,
            self._pause_event,
        )
        self._task_thread = threading.Thread(target=self._task_runner.run, daemon=True)
        self._task_thread.start()

        label = "Master" if mode == "master" else "Slave"
        self.task_status_var.set(f"{label} 任务运行中")
        self._set_task_buttons_running(True, paused=False)
        self._log_panel.log_system(f"[功能3] {label} 任务已开始（连接保持）")

    def _pause_task(self):
        if self._task_runner:
            self._task_runner.pause_task()
        self._pause_event.set()
        self.task_status_var.set("任务已暂停")
        self._set_task_buttons_running(True, paused=True)
        self._log_panel.log_system("[功能3] 任务已暂停")

    def _resume_task(self):
        if self._task_runner:
            self._task_runner.resume_task()
        self._pause_event.clear()
        mode = self.mode_var.get()
        label = "Master" if mode == "master" else "Slave"
        self.task_status_var.set(f"{label} 任务运行中")
        self._set_task_buttons_running(True, paused=False)
        self._log_panel.log_system("[功能3] 任务已继续")

    def _stop_task(self):
        if self._task_stop_event:
            self._task_stop_event.set()
        if self._task_runner:
            self._task_runner.stop_task()
        self._task_runner = None
        self._pause_event.clear()
        self.task_status_var.set("任务已停止（连接保持）")
        self._set_task_buttons_running(False)
        self._log_panel.log_system("[功能3] 任务已停止，连接保持")

    def _on_close(self):
        if self.c_panel:
            self.c_panel.stop_all()
        self._stop_ab_all()
        GuiLogBus.set_active(False)
        sys.stdout = self._original_stdout
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def launch_gui():
    AutomationGUI().run()
