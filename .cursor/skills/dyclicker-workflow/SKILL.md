---
name: dyclicker-workflow
description: 实现 dyclicker workflow 主循环与 step1/step2/step3 点击逻辑。在用户实现或修改 workflow 遍历、step 点击顺序、video review 播放次数、step 间 2 秒停顿或失焦中断时使用。
paths:
  - "**/workflow/**"
  - "**/runner*"
  - "**/config*"
  - "**/gui/**"
---

# dyclicker Workflow 实现

## When to Use

- 实现或修改主循环（wf1→wf6）
- 实现单 workflow 的 step1/step2/step3 点击
- 配置 video review 播放次数
- 调试 step 间 2 秒停顿

## 执行流程（强制）

```
主循环:
  for wf in [wf1, wf2, wf3, wf4, wf5, wf6]:
    run_workflow(wf)

run_workflow(wfN):
  1. step1: 点击 slotN
     sleep(2)
  2. step2: 点击 slot6
     sleep(2)
  3. step3: 点击 slot6 → 进入 video review
     run_video_review_loop()
```

## Workflow → 槽位映射

| Workflow | step1 slot | step2 slot | step3 slot |
|----------|------------|------------|------------|
| wf1 | slot1 (525,420) | slot6 (570,837) | slot6 (980,837) |
| wf2 | slot2 (955,415) | slot6 | slot6 |
| wf3 | slot3 (525,530) | slot6 | slot6 |
| wf4 | slot4 (955,530) | slot6 | slot6 |
| wf5 | slot5 (525,655) | slot6 | slot6 |
| wf6 | slot6 (955,650) | slot6 | slot6 |

坐标完整表见 `.cursor/rules/global-mouse-coords.mdc`。

## Video Review 循环

```
video_review_cycles = config  # 0 = 无限

点击 step3 slot6  → 开始第 1 轮播放
loop:
  监测音频直到停顿 > 5 秒
  if 已达播放次数上限（且 cycles != 0）:
    break
  点击 step3 slot6  → 下一轮播放
```

- **cycles = 0**：无限循环，直到用户 F10 停止、**目标窗口失焦**或定时退出
- **cycles > 0**：共监测 N 轮；最后一轮自然结束后不再点击 slot6

## 伪代码参考

```python
STEP_DELAY = 2.0  # 秒

def interruptible_sleep(seconds, stop_event):
    """step 间等待须可因 F10 / 失焦而中断"""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if stop_event.is_set():
            return False
        time.sleep(min(0.2, deadline - time.monotonic()))
    return True

def run_workflow(wf_index: int, logger, stop_event):
    if stop_event.is_set():
        return
    logger.info("开始 wf%d", wf_index)
    click_step1_slot(wf_index)
    if not interruptible_sleep(STEP_DELAY, stop_event):
        return
    click_step2_slot(6)
    if not interruptible_sleep(STEP_DELAY, stop_event):
        return
    click_step3_slot(6)
    run_silence_click_loop(..., stop_event=stop_event, logger=logger)
    logger.info("wf%d 完成", wf_index)
```

## 实现要点

1. **step2 失败不继续 step3**：step2 点击未确认成功时不得进入 step3。
2. **播放阶段禁止 back**：仅在 video review 全部轮次结束后才允许回退（若业务需要）。
3. **坐标来源**：从 `workflows.step1_slots`、`step2_shared`、`step3_shared` 读取，索引 0-based（slot6 = index 5）。
4. **与 OCR 协作**：step1 页面可通过 OCR（Company + Description）辅助判定；back 前必须确认非 step1。
5. **日志**：runner 接收 `logger` 参数；每次 step 点击、workflow 切换、静音续播、轮次完成写 INFO；异常写 ERROR。详见 `.cursor/rules/logging.mdc`。
6. **焦点监测**：与 `FocusMonitor` 共享 `stop_event`；目标音视频软件失焦时 `stop_event.set()`，runner **立即退出**，不再点击。详见 `.cursor/rules/focus-monitor.mdc`。

## 配置项

```yaml
dyclicker:
  step_click_delay: 2.0
  video_review_cycles: 0    # 0 = 无限
```

## 测试建议

- 单元测试：wf1–wf6 的 step1 槽位索引正确（N → slot N）
- 单元测试：step2/step3 均使用 slot6（index 5）
- 集成测试：mock 音频停顿 5s 后触发 slot6 再点击
- 边界：`video_review_cycles=0` 时不因次数上限退出
- 焦点：mock 失焦后 `stop_event` 已 set，主循环不再执行点击
