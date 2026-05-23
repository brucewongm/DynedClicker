---
name: dyclicker-audio-ocr
description: 实现 dyclicker 音频监测（播放/停顿/停顿时长）与 OCR 页面识别（Company+Description=step1、back 前非 step1 校验）。在用户实现音频检测、静音点击、页面 OCR 或 Ctrl+F2 热键时使用。
paths:
  - "**/audio/**"
  - "**/ocr/**"
  - "**/hotkeys/**"
---

# dyclicker 音频监测与 OCR

## When to Use

- 实现音频播放/停顿检测
- 实现 step3 静音 ≥5s 后点击 slot6
- 实现 OCR 判定 step1 页面
- 实现 back 按钮前的非 step1 安全校验
- 实现 Ctrl+F2 页面文字识别

## 音频监测

### 需求（rehearsal.txt）

1. 监测音频的 **播放** 和 **停顿**
2. 监测音频 **停顿时长**
3. step3：停顿 **超过 5 秒** 时点击 step3 slot6 续播

### 与 DynedClicker 的差异

| 项 | dyclicker | DynedClicker C/D 模式 |
|----|-----------|------------------------|
| 静音阈值 | **5 秒** | 3 秒 |
| 用途 | step3 video review 续播 | C 模式独立 / D 模式 step3 |

实现时可复用环回采集、RMS/峰值检测、相对阈值等思路，但 **silence_duration 默认必须为 5.0**。

### 推荐流程

```
AudioChunkSource 持续采集
  → SilenceDetector.process_chunk()
  → 停顿持续 ≥ 5s → 触发事件
  → 点击 step3 slot6
  → detector.reset()，等待下一轮播放
```

### 防误触建议

- 启动后须先检测到有效播放，再计停顿
- 点击后短冷却，避免连点
- 采集停滞时 watchdog 重启或墙钟兜底

### 配置

```yaml
dyclicker:
  silence_duration: 5.0
  click_cooldown: 2.0
  relative_detection: true
```

## OCR 页面识别

### step1 判定

- **条件**：OCR 结果 **同时包含** `Company` 和 `Description`（大小写策略在实现中统一，建议不区分大小写或按 Dy 界面实际文案）
- **结论**：当前为 **step1 页面**

```python
def is_step1_page(ocr_text: str) -> bool:
    t = ocr_text.lower()
    return "company" in t and "description" in t
```

### back 按钮安全（强制）

每次点击 **back (442, 955)** 前：

```
if is_step1_page(current_ocr()):
    skip_back()   # 禁止点击，防止误退出
else:
    click_back()
```

**不可省略**此校验。

### Ctrl+F2 热键

- 触发一次页面 OCR
- 用于测试/调试：输出识别文本及 step1 判定结果
- 配置键建议：`page_ocr_hotkey: Ctrl+F2`
- **日志**：`logger.info("OCR 测试: step1=%s, 文本片段=…", is_step1)`

## 日志要点

| 事件 | 级别 | 消息示例 |
|------|------|----------|
| 检测到播放 | DEBUG | `音频播放中 RMS=0.042` |
| 停顿达阈值 | INFO | `静音 5.1s ≥ 5.0s，触发 slot6 点击` |
| step1 OCR | INFO | `OCR 判定 step1 (Company+Description)` |
| back 拦截 | WARNING | `当前 step1 页面，跳过 back` |
| 环回设备异常 | ERROR | `未找到环回设备: …` |
| 失焦停止 | ERROR | `目标窗口已失焦，停止运行` |

音频/OCR 循环须检查共享 `stop_event`（含失焦触发）；失焦后 **不得** 再触发 slot6 点击。

## 模块建议

| 模块 | 职责 |
|------|------|
| `core/audio/monitor.py` | 音量、停顿判定 |
| `core/audio/chunk_source.py` | 环回采集 |
| `core/ocr/page_detect.py` | step1 判定、back 前校验 |
| `core/hotkeys/` | F9/F10/Ctrl+F2 |

## 测试建议

- 静音 4.9s 不触发；5.0s+ 触发点击
- OCR 仅含 Company 或仅含 Description → 非 step1
- 两者皆有 → step1；此时 back 被拦截
- Ctrl+F2 可独立触发 OCR 且不启动主循环

## 禁止事项

- 禁止将默认静音阈值改为 3 秒（除非用户明确要求）
- 禁止在 step1 页面执行 back 点击
- 禁止在 video review 播放中点击 back
- 禁止在 `stop_event` 已 set（含失焦）后继续音频续播点击
