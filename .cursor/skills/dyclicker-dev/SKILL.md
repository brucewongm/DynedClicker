---
name: dyclicker-dev
description: dyclicker 项目开发与功能实现指南（tkinter.ttk GUI、双通道日志、焦点监测、workflow/OCR/音频）。在用户开发、修改或调试 dyclicker 时使用；新建模块、GUI、日志或测试时优先遵循本 skill。
---

# dyclicker 开发指南

## When to Use

- 用户要求实现、扩展或修复 dyclicker 功能
- 新建项目骨架、**ttk GUI**、**日志模块**、配置或核心逻辑
- 需要确认 workflow、坐标、热键、定时退出是否符合 `rehearsal.txt`

## 权威文档

1. 项目规格：`rehearsal.txt`
2. `.cursor/rules/dyclicker.mdc` — 业务约定
3. `.cursor/rules/global-mouse-coords.mdc` — 坐标（alwaysApply）
4. `.cursor/rules/gui-ttk.mdc` — **ttk GUI**
5. `.cursor/rules/logging.mdc` — **日志**（alwaysApply）
6. `.cursor/rules/focus-monitor.mdc` — **焦点监测**（alwaysApply）
7. 专项 skill：`dyclicker-gui`、`dyclicker-workflow`、`dyclicker-audio-ocr`

## 项目概要

| 项 | 值 |
|----|-----|
| 工具名 | dyclicker |
| GUI | **tkinter + ttk** |
| 日志 | `logs/dyclicker.log` + GUI 日志区 |
| 能力 | 音频监测、OCR、鼠标自动化 |
| 工作流 | wf1–wf6，各 3 step |
| step 间停顿 | 2 秒 |
| 静音阈值 | 5 秒 |
| 热键 | F9 开始 / F10 停止 / Ctrl+F2 页面 OCR |
| 定时退出 | 默认当前时间 + 24h |
| video review | 可设播放次数，0 = 无限 |
| 焦点监测 | 目标软件失焦 → **立即停止**，不自动续跑 |

## 建议模块划分

```
dyclicker/
├── main.py                 # 入口：GUI 或 CLI
├── config/
│   └── config_manager.py
├── core/
│   ├── logging_setup.py    # setup_logging → 文件 + GuiLogHandler
│   ├── workflow/
│   ├── audio/
│   ├── ocr/
│   ├── mouse/
│   ├── focus_monitor.py    # 目标窗口失焦 → stop_event
│   └── hotkeys/
├── gui/                    # 仅 ttk + ScrolledText；不 import 到 core
│   ├── app.py
│   ├── main_panel.py
│   └── log_view.py         # GuiLogBus / LogPanelController
├── logs/                   # 运行时生成
└── tests/
```

实现可参考 sibling 项目 `DynedClicker` 的 `gui/app.py`、`gui/log_view.py`、`core/logging_setup.py`、`core/focus_monitor.py`，但须遵守本项目 **5 秒静音**、**失焦即停** 与 **单模式 dyclicker** 设计。

## 实现检查清单

### GUI（ttk）

- [ ] 控件均为 `ttk.*`（日志区可用 `ScrolledText`）
- [ ] 主窗口含底部日志区
- [ ] 启停按钮显示 F9/F10
- [ ] 后台线程经 `root.after` 更新 UI

### 日志

- [ ] `setup_logging(config, role="dyclicker")` 统一初始化
- [ ] 文件写入 `logs/dyclicker.log`（RotatingFileHandler）
- [ ] GUI 启动后 `GuiLogBus.set_active(True, …)`
- [ ] workflow 点击、静音触发、OCR、back 拦截均有 INFO/WARNING

### 启动前

- [ ] 目标 Dy 窗口可定位
- [ ] 坐标自 `REFERENCE_*` 或配置加载
- [ ] F9/F10 全局热键可注册
- [ ] `FocusMonitor` 随启动运行；`pause_on_focus_loss=false`

### 焦点监测

- [ ] `GetForegroundWindow() != target_hwnd` 时 `stop_event.set()`
- [ ] 失焦后 runner 退出、无后续点击
- [ ] GUI 显示「已停止（失焦）」；`logger.error` 记录
- [ ] 焦点恢复后不自动续跑

### 主循环

- [ ] 顺序 wf1→wf6；每 step 后 2s
- [ ] step1 点 slotN，step2/step3 点 slot6

### step3 / video review

- [ ] 静音 ≥5s → 再点 slot6；0 = 无限循环
- [ ] 播放中不点 back

### OCR / 安全

- [ ] Company + Description → step1
- [ ] back 前确认非 step1；Ctrl+F2 可测 OCR

### 定时退出

- [ ] 到达设定时间自动退出；默认 now + 24h

## 修改约定

- 坐标：同步 `global-mouse-coords.mdc`、`REFERENCE_*`、默认配置、测试
- GUI：只用 ttk；core 不 import tkinter
- 日志：业务状态用 `logger`，不用 `print`
- 静音阈值默认 5 秒，勿套用 DynedClicker 的 3 秒
- 失焦即停；勿启用 `pause_on_focus_loss`
- F9/F10 为默认启停热键

## 相关 Skill

- `/dyclicker-gui` — ttk 界面与日志区
- `/dyclicker-workflow` — 主循环与 step 执行
- `/dyclicker-audio-ocr` — 音频监测与 OCR
