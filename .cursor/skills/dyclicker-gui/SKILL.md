---
name: dyclicker-gui
description: 使用 tkinter.ttk 构建 dyclicker 主界面与日志区。在用户实现 GUI、主窗口、配置面板、焦点监测联动、坐标窗口、日志展示或热键与 UI 联动时使用。
paths:
  - "gui/**"
  - "main.py"
  - "**/app.py"
---

# dyclicker GUI（tkinter + ttk）

## When to Use

- 搭建主窗口、控制面板、坐标配置窗口
- 实现底部 **交互日志区**
- 绑定 F9/F10/Ctrl+F2 与按钮同路径
- 将配置项（播放次数、定时退出）暴露到界面

## 技术约束（强制）

```python
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

# ✓ ttk.Frame, ttk.Button, ttk.Label, ttk.Spinbox, ttk.Notebook, ttk.LabelFrame
# ✓ tk.Tk, tk.StringVar, scrolledtext.ScrolledText（日志）
# ✗ tk.Button, tk.Label, tk.Entry（业务 UI 禁止）
```

详情见 `.cursor/rules/gui-ttk.mdc`。

## 主窗口结构

```
tk.Tk
└── ttk.Frame (padding=8)
    ├── ttk.Label          # 标题
    ├── ttk.LabelFrame     # 配置摘要（目标窗口、回退坐标等）
    ├── ttk.Frame          # 参数：video_review_cycles、auto_exit_at
    ├── ttk.Frame          # 按钮：开始 (F9)、停止 (F10)、页面识别 (Ctrl+F2)
    └── ttk.LabelFrame     # 「运行日志」
        └── scrolledtext.ScrolledText  # state=disabled，只追加
```

参考 sibling：`DynedClicker/gui/app.py`、`gui/d_panel.py`（ttk 布局风格）。

## 日志区集成

1. 构建 UI 后创建 `LogPanelController(scrolledtext, root, max_lines=…)`。
2. `GuiLogBus.set_active(True, callback=log_panel.append)`。
3. 可选：`sys.stdout = StdoutToGui(original_stdout)`。
4. 调用 `setup_logging(config, role="dyclicker")` — 自动挂载 `GuiLogHandler`。
5. 关闭时：`GuiLogBus.set_active(False)`，恢复 stdout。

```python
def _setup_log_panel(self):
    self._log_panel = LogPanelController(self.log_text, self.root, max_lines=2000)
    GuiLogBus.set_active(True, self._log_panel.append)
    self._log_panel.log_system("dyclicker 已就绪")
```

日志约定见 `.cursor/rules/logging.mdc`。

## 启停与线程

```python
def _start(self):
    if self._task_thread and self._task_thread.is_alive():
        return
    wm = WindowManager()
    if not wm.ensure_target_window(self.config):
        messagebox.showerror("错误", "未找到目标窗口", parent=self.root)
        return
    self._stop_event = threading.Event()
    logger = setup_logging(self.config, role="dyclicker")

    def on_focus_lost():
        self._stop_event.set()
        self.root.after(0, self._on_focus_lost_ui)

    self._focus_monitor = FocusMonitor(
        self.config, wm, logger,
        on_focus_lost=on_focus_lost,
        pause_on_focus_loss=False,
    )
    self._hide_gui_for_run(True)  # 避免 dyclicker 抢焦点
    self._focus_monitor.start()
    logger.info("用户点击开始 (F9)")
    self._task_thread = threading.Thread(
        target=self._run_with_cleanup,
        args=(self._stop_event, logger),
        daemon=True,
    )
    self._task_thread.start()

def _on_focus_lost_ui(self):
    self._set_running(False)
    self._log_panel.log_system("目标窗口已失焦，已停止运行")
    self._hide_gui_for_run(False)

def _run_with_cleanup(self, stop_event, logger):
    try:
        self._runner.run(stop_event)
    finally:
        self._focus_monitor.stop()
        self.root.after(0, lambda: self._hide_gui_for_run(False))

def _stop(self):
    if self._stop_event:
        self._stop_event.set()
    if self._focus_monitor:
        self._focus_monitor.stop()
    logger.info("用户点击停止 (F10)")
```

- 热键回调：`root.after(0, self._start)` / `root.after(0, self._stop)`。
- runner 内只用 `logger.info/warning/error`，不碰 Tk 控件。
- **失焦停止**与 F10 共用 `stop_event`；UI 更新仅经 `root.after`。
- 监测对象是 **目标音视频软件**，不是 dyclicker 窗口；启动时建议隐藏自身 GUI。

焦点约定见 `.cursor/rules/focus-monitor.mdc`。

## 配置控件示例

| 配置项 | ttk 控件 |
|--------|----------|
| `video_review_cycles` | `ttk.Spinbox`（0 = 无限） |
| `auto_exit_at` | `ttk.Entry` + 日期时间校验 |
| `step_click_delay` | `ttk.Spinbox` |
| `silence_duration` | `ttk.Spinbox`（默认 5.0） |

保存时：`config.set(...)` + `config.save()` + `logger.info("配置已保存: …")`。

## 坐标窗口（可选）

- `ttk.Notebook` 分 tab：全局按钮 / Step1 / Step2 / Step3。
- 每行：`ttk.Label` + 坐标显示 + `ttk.Button("采样")`。
- 参考 `DynedClicker/gui/workflow_coords_window.py`。

## 检查清单

- [ ] 无 `tk.Button` / `tk.Label` 等业务控件
- [ ] 日志区可见且随运行滚动
- [ ] F9/F10 与按钮行为一致
- [ ] 启动时 `FocusMonitor` 运行；失焦后 UI 显示已停止
- [ ] 关闭窗口先 stop、`FocusMonitor.stop()` 再 destroy
- [ ] core 模块零 tkinter 依赖

## 禁止事项

- 禁止在工作线程 `text.insert` 或改控件 state
- 禁止去掉文件日志仅留 GUI
- 禁止引入非 ttk 的第三方 UI 库
- 禁止失焦后仅提示而不 `stop_event.set()`
