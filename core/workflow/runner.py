"""dyclicker 主循环：wf1–wf6，step1/2/3 + video review + 回退切换"""
from __future__ import annotations

import threading
import time
from datetime import datetime

from core.audio.loopback_device import find_loopback_device
from core.audio.silence_click_loop import SilenceClickLoop
from core.mouse.background_click import BackgroundClicker
from core.mouse.window_tools import WindowManager
from core.ocr.page_detect import safe_click_back
from core.workflow_coords import (
    STEP2_SLOT_INDEX,
    STEP3_SLOT_INDEX,
    WORKFLOW_COUNT,
    get_step1_coord,
    get_step2_coord,
    get_step3_coord,
)


def interruptible_sleep(seconds: float, stop_event: threading.Event) -> bool:
    deadline = time.monotonic() + max(0.0, seconds)
    while time.monotonic() < deadline:
        if stop_event.is_set():
            return False
        time.sleep(min(0.2, deadline - time.monotonic()))
    return True


class DyclickerRunner:
    def __init__(self, config, logger, stop_event: threading.Event):
        self.config = config
        self.logger = logger
        self.stop_event = stop_event
        self.wm = WindowManager()
        self.clicker = BackgroundClicker(self.wm, logger)
        self._capture_device = None

    def is_ready(self) -> tuple[bool, str]:
        if not self.wm.ensure_target_window(self.config):
            title = self.config.get("target_window.window_title") or ""
            if not title:
                return False, "请先绑定目标窗口（目标音视频软件）"
            return False, f"未找到目标窗口: {title}"
        return True, ""

    def _check_auto_exit(self) -> bool:
        ae = self.config.get("auto_exit") or {}
        if not ae.get("enabled", True):
            return False
        at_str = ae.get("at")
        if not at_str:
            return False
        try:
            at = datetime.strptime(str(at_str), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return False
        if datetime.now() >= at:
            self.logger.info("到达 auto_exit_at=%s，停止运行", at_str)
            self.stop_event.set()
            return True
        return False

    def _silence_params(self) -> tuple[float, float, bool]:
        silence = float(self.config.get("dyclicker.silence_duration", 5.0))
        cooldown = float(self.config.get("dyclicker.click_cooldown", 2.0))
        relative = bool(self.config.get("dyclicker.relative_detection", True))
        return silence, cooldown, relative

    def _ensure_capture_device(self) -> None:
        if self._capture_device is None:
            self._capture_device = find_loopback_device(self.logger)

    def _click(self, x: int, y: int, label: str) -> bool:
        if self.stop_event.is_set():
            return False
        self.wm.focus_target_window()
        ok = self.clicker.click_at(x, y, self.config)
        self.logger.info("%s @ (%s, %s) %s", label, x, y, "成功" if ok else "失败")
        return ok

    def _wait_for_silence(self, wf_index: int, log_prefix: str) -> bool:
        if self.stop_event.is_set():
            return False
        silence, cooldown, relative = self._silence_params()
        self._ensure_capture_device()
        self.logger.info("%s 等待音频停顿 ≥%.1fs…", log_prefix, silence)

        loop = SilenceClickLoop(
            self.config,
            self.logger,
            self.stop_event,
            target_clicks=0,
            silence_duration=silence,
            click_cooldown=cooldown,
            relative_detection=relative,
            on_click=lambda _idx: None,
            capture_device=self._capture_device,
            playback_already_started=True,
            wait_final_silence=True,
            log_prefix=log_prefix,
        )
        loop.run()
        return not self.stop_event.is_set()

    def _run_video_review(self, wf_index: int) -> bool:
        cycles = int(self.config.get("dyclicker.video_review_cycles", 0))
        silence, cooldown, relative = self._silence_params()
        pt = get_step3_coord(self.config, STEP3_SLOT_INDEX)

        if not self._click(pt["x"], pt["y"], f"wf{wf_index} step3 slot6 启动 video review"):
            return False

        self._ensure_capture_device()

        def on_silence_click(idx: int) -> None:
            if self.stop_event.is_set():
                return
            self._click(pt["x"], pt["y"], f"wf{wf_index} step3 slot6 静音续播 #{idx}")

        if cycles == 0:
            round_no = 0
            while not self.stop_event.is_set():
                round_no += 1
                self.logger.info("wf%d video review 第 %d 轮（无限循环）", wf_index, round_no)
                loop = SilenceClickLoop(
                    self.config,
                    self.logger,
                    self.stop_event,
                    target_clicks=0,
                    silence_duration=silence,
                    click_cooldown=cooldown,
                    relative_detection=relative,
                    on_click=on_silence_click,
                    capture_device=self._capture_device,
                    playback_already_started=True,
                    wait_final_silence=True,
                    log_prefix=f"【wf{wf_index}】",
                )
                loop.run()
                if self.stop_event.is_set():
                    return False
                if not self._click(pt["x"], pt["y"], f"wf{wf_index} step3 slot6 下一轮"):
                    return False
            return False

        target_clicks = max(0, cycles - 1)
        loop = SilenceClickLoop(
            self.config,
            self.logger,
            self.stop_event,
            target_clicks=target_clicks,
            silence_duration=silence,
            click_cooldown=cooldown,
            relative_detection=relative,
            on_click=on_silence_click,
            capture_device=self._capture_device,
            playback_already_started=True,
            wait_final_silence=True,
            log_prefix=f"【wf{wf_index}】",
        )
        loop.run()
        if self.stop_event.is_set():
            return False
        self.logger.info("wf%d video review 完成 (%d 轮)", wf_index, cycles)
        return True

    def _return_to_step1_after_workflow(self, wf_index: int) -> bool:
        if self.stop_event.is_set():
            return False

        prefix = f"【wf{wf_index}→切换】"
        if not self._wait_for_silence(wf_index, prefix):
            return False

        self.logger.info("%s 停顿已满足，点击 back 回退至 step1", prefix)
        if not safe_click_back(self.clicker, self.config, self.wm, self.logger):
            self.logger.warning("%s back 未执行（可能已在 step1 或 OCR 拦截）", prefix)

        switch_delay = float(self.config.get("dyclicker.wf_switch_delay", 2.0))
        self.logger.info("%s 回退后停留 %.1fs，准备下一 workflow", prefix, switch_delay)
        return interruptible_sleep(switch_delay, self.stop_event)

    def _run_workflow(self, wf_index: int) -> None:
        if self.stop_event.is_set():
            return
        delay = float(self.config.get("dyclicker.step_click_delay", 2.0))
        self.logger.info("开始 wf%d", wf_index)

        s1 = get_step1_coord(self.config, wf_index)
        if not self._click(s1["x"], s1["y"], f"wf{wf_index} step1 slot{wf_index}"):
            return
        if not interruptible_sleep(delay, self.stop_event):
            return

        s2 = get_step2_coord(self.config, STEP2_SLOT_INDEX)
        if not self._click(s2["x"], s2["y"], f"wf{wf_index} step2 slot6"):
            return
        if not interruptible_sleep(delay, self.stop_event):
            return

        review_done = self._run_video_review(wf_index)
        if not review_done or self.stop_event.is_set():
            return

        if not self._return_to_step1_after_workflow(wf_index):
            return

        self.logger.info("wf%d 完成", wf_index)

    def run(self) -> None:
        if not self.wm.ensure_target_window(self.config):
            self.logger.error("目标窗口不可用，无法启动")
            return
        self.logger.info("dyclicker 主循环开始")
        while not self.stop_event.is_set():
            if self._check_auto_exit():
                break
            for wf in range(1, WORKFLOW_COUNT + 1):
                if self.stop_event.is_set() or self._check_auto_exit():
                    break
                self._run_workflow(wf)
            if self.stop_event.is_set():
                break
            self.logger.info("一轮 wf1–wf6 完成，开始下一轮")
        self.logger.info("dyclicker 主循环结束")
