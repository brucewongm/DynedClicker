"""绑定目标窗口：弹窗提示 + 前台保持检测"""
from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable, Optional


def run_window_bind_dialog(parent, window_manager, config, log_panel, on_complete: Optional[Callable[[], None]] = None) -> None:
    hold = float(config.get("target_window.focus_hold_seconds", 3))

    dlg = tk.Toplevel(parent)
    dlg.title("绑定目标窗口")
    dlg.transient(parent)
    dlg.resizable(False, False)
    try:
        dlg.attributes("-topmost", True)
    except tk.TclError:
        pass

    frame = ttk.Frame(dlg, padding=16)
    frame.pack()

    ttk.Label(frame, text="绑定目标音视频软件", font=("", 11, "bold")).pack(anchor=tk.W, pady=(0, 8))
    hint = (
        f"1. 点击「开始绑定」后，本工具窗口将暂时隐藏。\n"
        f"2. 请将被监测的软件窗口切换到最顶层（前台）。\n"
        f"3. 保持该窗口在最前 {hold:.0f} 秒，即可完成绑定。"
    )
    ttk.Label(frame, text=hint, justify=tk.LEFT, wraplength=360).pack(anchor=tk.W, pady=(0, 12))

    status_var = tk.StringVar(value="")
    ttk.Label(frame, textvariable=status_var, foreground="#0066cc").pack(anchor=tk.W, pady=(0, 8))

    btn_row = ttk.Frame(frame)
    btn_row.pack(fill=tk.X)

    def close_dialog():
        try:
            dlg.grab_release()
        except tk.TclError:
            pass
        dlg.destroy()

    def on_done(success: bool, title: str = "") -> None:
        parent.deiconify()
        parent.lift()
        close_dialog()
        if success:
            log_panel.log_system(f"[绑定] 成功: {title}")
            messagebox.showinfo("绑定成功", f"已绑定目标窗口：\n{title}", parent=parent)
        else:
            log_panel.log_system("[绑定] 失败：未检测到稳定的前台窗口")
            messagebox.showwarning(
                "绑定失败",
                f"未能在 {hold:.0f} 秒内检测到稳定的前台窗口。\n请确保目标软件已置于最顶层并保持不动。",
                parent=parent,
            )
        if on_complete:
            on_complete()

    def start_bind():
        status_var.set("准备中…")
        start_btn.configure(state=tk.DISABLED)
        cancel_btn.configure(state=tk.DISABLED)
        dlg.update_idletasks()
        dlg.withdraw()
        parent.withdraw()

        progress = tk.Toplevel(parent)
        progress.title("正在绑定…")
        progress.transient(parent)
        progress.resizable(False, False)
        try:
            progress.attributes("-topmost", True)
        except tk.TclError:
            pass
        prog_var = tk.StringVar(value=f"请将目标窗口置于最顶层并保持 {hold:.0f} 秒…")
        ttk.Label(progress, textvariable=prog_var, padding=20).pack()
        progress.update_idletasks()

        def hide_progress():
            try:
                progress.destroy()
            except tk.TclError:
                pass

        def on_tick(elapsed: float, title: str) -> None:
            remaining = max(0.0, hold - elapsed)
            text = title or "检测中"
            msg = f"正在检测前台窗口…\n当前: {text}\n请保持最前 {remaining:.1f} 秒"
            parent.after(0, lambda m=msg: prog_var.set(m))

        def work():
            from core.logging_setup import setup_logging

            logger = setup_logging(config, role="dyclicker")
            hwnd = window_manager.calibrate_from_focus_hold(
                delay_seconds=0,
                hold_seconds=hold,
                on_tick=on_tick,
                log=logger,
            )
            if hwnd:
                window_manager.persist_to_config(config)
                config.save()
                title = window_manager.window_title or ""
                parent.after(0, lambda: (hide_progress(), on_done(True, title)))
            else:
                parent.after(0, lambda: (hide_progress(), on_done(False)))

        threading.Thread(target=work, daemon=True).start()

    start_btn = ttk.Button(btn_row, text="开始绑定", command=start_bind)
    start_btn.pack(side=tk.LEFT, padx=(0, 8))
    cancel_btn = ttk.Button(btn_row, text="取消", command=close_dialog)
    cancel_btn.pack(side=tk.LEFT)

    dlg.protocol("WM_DELETE_WINDOW", close_dialog)
    dlg.grab_set()
    dlg.focus_force()
