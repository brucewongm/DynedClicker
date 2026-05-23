"""全局坐标配置窗口"""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from core.workflow_coords import (
    REFERENCE_GLOBAL_BUTTONS,
    REFERENCE_STEP1_SLOTS,
    REFERENCE_STEP2_SHARED,
    REFERENCE_STEP3_SHARED,
    mark_coords_user_calibrated,
)
from gui.coord_sampler import CoordHotkeySampler


class CoordsWindow:
    def __init__(self, parent, config, log_panel):
        self.config = config
        self.log_panel = log_panel
        self._vars: dict[str, tk.StringVar] = {}
        self._pick_buttons: list[ttk.Button] = []
        self._sampler = CoordHotkeySampler(parent, config, log_panel)

        self.win = tk.Toplevel(parent)
        self.win.title("坐标配置")
        self.win.geometry("680x560")
        self.win.transient(parent)

        outer = ttk.Frame(self.win, padding=8)
        outer.pack(fill=tk.BOTH, expand=True)

        hk = self._sampler.hotkey_label
        ttk.Label(
            outer,
            text=f"采样：点击「选取」→ 移动鼠标到目标位置 → 按 {hk} 确定坐标",
            foreground="#555",
            wraplength=640,
        ).pack(anchor=tk.W, pady=(0, 6))

        self.pending_var = tk.StringVar(value=f"当前未选取（{hk}）")
        ttk.Label(outer, textvariable=self.pending_var, foreground="#0066cc").pack(
            anchor=tk.W, pady=(0, 6)
        )

        nb = ttk.Notebook(outer)
        nb.pack(fill=tk.BOTH, expand=True)

        self._tab_global(nb)
        self._tab_step1(nb)
        self._tab_shared(nb, "Step2 共享", "workflows.step2_shared", REFERENCE_STEP2_SHARED)
        self._tab_shared(nb, "Step3 共享", "workflows.step3_shared", REFERENCE_STEP3_SHARED)

        row = ttk.Frame(outer)
        row.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(row, text="取消选取", command=self._cancel_pick).pack(side=tk.LEFT)
        ttk.Button(row, text="保存", command=self._save).pack(side=tk.RIGHT, padx=4)
        ttk.Button(row, text="关闭", command=self._close).pack(side=tk.RIGHT)

        self._sampler.start()
        self._reload()
        self.win.protocol("WM_DELETE_WINDOW", self._close)

    def _var(self, key: str, x: int, y: int) -> tk.StringVar:
        v = tk.StringVar(value=f"({x}, {y})")
        self._vars[key] = v
        return v

    def _set_pending_ui(self, label: str | None) -> None:
        hk = self._sampler.hotkey_label
        if label:
            self.pending_var.set(f"正在选取：{label}（按 {hk} 确定）")
        else:
            self.pending_var.set(f"当前未选取（{hk}）")

    def _arm_global(self, key: str, label: str) -> None:
        def apply(x: int, y: int) -> None:
            self.config.config.setdefault("global_buttons", {})[key] = {"x": x, "y": y}
            mark_coords_user_calibrated(self.config)
            self.config.save()
            self._reload()
            self._set_pending_ui(None)

        self._arm(label, apply)

    def _arm_list(self, list_key: str, index: int, label: str) -> None:
        def apply(x: int, y: int) -> None:
            parts = list_key.split(".")
            cur = self.config.config
            for p in parts[:-1]:
                cur = cur.setdefault(p, {})
            lst = cur.setdefault(parts[-1], [])
            while len(lst) <= index:
                lst.append({"x": 0, "y": 0})
            lst[index] = {"x": x, "y": y}
            mark_coords_user_calibrated(self.config)
            self.config.save()
            self._reload()
            self._set_pending_ui(None)

        self._arm(label, apply)

    def _arm(self, label: str, apply_fn) -> None:
        self._sampler.arm(label, apply_fn)
        self._set_pending_ui(label)

    def _cancel_pick(self) -> None:
        self._sampler.cancel_arm()
        self._set_pending_ui(None)

    def _tab_global(self, nb) -> None:
        tab = ttk.Frame(nb, padding=8)
        nb.add(tab, text="全局按钮")
        labels = {"back": "回退", "record": "录音", "listen": "收听", "replay": "重播", "forward": "前进"}
        for i, (key, label) in enumerate(labels.items()):
            ref = REFERENCE_GLOBAL_BUTTONS[key]
            ttk.Label(tab, text=label, width=8).grid(row=i, column=0, sticky=tk.W, pady=2)
            ttk.Label(tab, textvariable=self._var(f"global.{key}", ref["x"], ref["y"]), width=16).grid(
                row=i, column=1, sticky=tk.W
            )
            btn = ttk.Button(tab, text="选取", command=lambda k=key, lb=label: self._arm_global(k, lb))
            btn.grid(row=i, column=2, padx=4)
            self._pick_buttons.append(btn)

    def _tab_step1(self, nb) -> None:
        tab = ttk.Frame(nb, padding=8)
        nb.add(tab, text="Step1")
        for i, ref in enumerate(REFERENCE_STEP1_SLOTS):
            wf = i + 1
            name = f"wf{wf} slot{wf}"
            ttk.Label(tab, text=name, width=12).grid(row=i, column=0, sticky=tk.W, pady=2)
            ttk.Label(tab, textvariable=self._var(f"step1.{wf}", ref["x"], ref["y"]), width=16).grid(
                row=i, column=1, sticky=tk.W
            )
            btn = ttk.Button(
                tab, text="选取", command=lambda idx=i, nm=name: self._arm_list("workflows.step1_slots", idx, nm)
            )
            btn.grid(row=i, column=2, padx=4)
            self._pick_buttons.append(btn)

    def _tab_shared(self, nb, title, prefix, refs) -> None:
        tab = ttk.Frame(nb, padding=8)
        nb.add(tab, text=title)
        short = prefix.split(".")[-1]
        for i, ref in enumerate(refs):
            name = f"{title} slot{i + 1}"
            ttk.Label(tab, text=f"slot{i + 1}", width=8).grid(row=i, column=0, sticky=tk.W, pady=2)
            ttk.Label(tab, textvariable=self._var(f"{short}.{i}", ref["x"], ref["y"]), width=16).grid(
                row=i, column=1, sticky=tk.W
            )
            btn = ttk.Button(
                tab, text="选取", command=lambda idx=i, p=prefix, nm=name: self._arm_list(p, idx, nm)
            )
            btn.grid(row=i, column=2, padx=4)
            self._pick_buttons.append(btn)

    def _reload(self) -> None:
        gb = self.config.get("global_buttons") or {}
        for key in REFERENCE_GLOBAL_BUTTONS:
            pt = gb.get(key, REFERENCE_GLOBAL_BUTTONS[key])
            self._vars.get(f"global.{key}", tk.StringVar()).set(f"({pt['x']}, {pt['y']})")
        s1 = self.config.get("workflows.step1_slots") or REFERENCE_STEP1_SLOTS
        for i, ref in enumerate(REFERENCE_STEP1_SLOTS):
            pt = s1[i] if i < len(s1) else ref
            self._vars.get(f"step1.{i + 1}", tk.StringVar()).set(f"({pt['x']}, {pt['y']})")
        for short, list_key, refs in (
            ("step2_shared", "workflows.step2_shared", REFERENCE_STEP2_SHARED),
            ("step3_shared", "workflows.step3_shared", REFERENCE_STEP3_SHARED),
        ):
            slots = self.config.get(list_key) or refs
            for i, ref in enumerate(refs):
                pt = slots[i] if i < len(slots) else ref
                self._vars.get(f"{short}.{i}", tk.StringVar()).set(f"({pt['x']}, {pt['y']})")

    def _save(self) -> None:
        mark_coords_user_calibrated(self.config)
        self.config.save()
        self.log_panel.log_system("坐标已保存到配置文件")
        messagebox.showinfo("保存", "坐标已保存", parent=self.win)

    def _close(self) -> None:
        self._sampler.stop()
        self.win.destroy()
