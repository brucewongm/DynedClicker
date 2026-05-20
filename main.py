"""
Dy 音频自动化工具 (audioauto)
默认启动图形界面；连接服务与任务执行分离
"""
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config.config_manager import BUTTON_REGIONS, ConfigManager
from core.audio.master_monitor import MasterAudioMonitor
from core.audio.monitor import SilenceDetector
from core.audio.player import AudioPlayer
from core.audio.processor import AudioProcessor
from core.audio.recorder import AudioRecorder
from core.connection_service import ConnectionService
from core.focus_monitor import FocusMonitor
from core.logging_setup import setup_logging
from core.mouse.background_click import BackgroundClicker
from core.mouse.window_tools import WindowManager
from core.state_machine import MasterStateMachine, SlaveStateMachine
from core.vision.quiz_detector import QuizDetector


def _hide_console_on_windows():
    if sys.platform != "win32":
        return
    try:
        import ctypes
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)
    except Exception:
        pass


class TaskRunner:
    """仅运行自动化任务，使用已建立的共享网络连接"""

    def __init__(
        self,
        config: ConfigManager,
        mode: str,
        network,
        stop_event: threading.Event,
        pause_event: threading.Event = None,
    ):
        self.config = config
        self.mode = mode
        self.network = network
        self.stop_event = stop_event
        self.pause_event = pause_event or threading.Event()
        self.logger = setup_logging(config, role=mode)
        self._focus_monitor = None
        self._state_machine = None

    def run(self):
        try:
            if self.mode == "master":
                self._run_master_task()
            else:
                self._run_slave_task()
        except Exception as e:
            self.logger.exception("任务异常: %s", e)
        finally:
            self.stop_task()

    def pause_task(self):
        if self._state_machine and hasattr(self._state_machine, "pause_task"):
            self._state_machine.pause_task()

    def resume_task(self):
        if self._state_machine and hasattr(self._state_machine, "resume_task"):
            self._state_machine.resume_task()

    def _setup_focus_monitor(self, window_manager: WindowManager, state_machine=None):
        pause = self.mode == "master" and self.config.get("focus.pause_on_focus_loss", True)
        on_lost = self.stop
        on_regained = None
        if state_machine is not None:
            on_lost = state_machine.on_focus_lost
            on_regained = state_machine.on_focus_regained

        self._focus_monitor = FocusMonitor(
            self.config,
            window_manager,
            self.logger,
            on_focus_lost=on_lost,
            on_focus_regained=on_regained,
            pause_on_focus_loss=pause,
        )
        self._focus_monitor.start()

    def _run_master_task(self):
        self.logger.info("Master 任务启动")
        wm = WindowManager()
        wm.load_from_config(self.config)
        clicker = BackgroundClicker(wm, self.logger)
        quiz = QuizDetector(self.config, wm, self.logger)
        monitor = MasterAudioMonitor(self.config, self.logger)

        self._state_machine = MasterStateMachine(
            self.config,
            self.network,
            clicker,
            quiz,
            monitor,
            self.logger,
            self.stop_event,
            self.pause_event,
            owns_network=False,
        )
        self._setup_focus_monitor(wm, self._state_machine)

        if not self._state_machine.start_task():
            self.logger.error("Master 任务启动失败")
            return

        while not self.stop_event.is_set():
            time.sleep(0.2)

    def _run_slave_task(self):
        self.logger.info("Slave 任务启动")
        recorder = AudioRecorder(self.config, self.logger)
        detector = SilenceDetector(self.config)
        processor = AudioProcessor(self.config)
        player = AudioPlayer(self.config, self.logger)

        self._state_machine = SlaveStateMachine(
            self.config,
            self.network,
            recorder,
            detector,
            processor,
            player,
            self.logger,
            self.stop_event,
            self.pause_event,
            owns_network=False,
        )
        if not self._state_machine.start_task():
            self.logger.error("Slave 任务启动失败")
            return

        while not self.stop_event.is_set():
            time.sleep(0.2)

    def stop_task(self):
        if self._focus_monitor:
            self._focus_monitor.stop()
            self._focus_monitor = None
        if self._state_machine:
            self._state_machine.stop_task()
            self._state_machine = None


# 兼容旧引用
ServiceRunner = TaskRunner


class CModeTool:
    """C 模式：目标窗口与点击位置矫正"""

    def __init__(self, config: ConfigManager = None, gui_parent=None):
        self.config = config or ConfigManager()
        self.gui_parent = gui_parent

    def _prompt(self, message: str):
        if self.gui_parent is not None:
            from tkinter import messagebox
            messagebox.showinfo("C 模式", message, parent=self.gui_parent)
        else:
            input(message)

    def calibrate_window(self):
        log = setup_logging(self.config, role="c")
        wm = WindowManager()
        self._prompt("请先将目标窗口置于前台，点确定记录")
        hwnd = wm.calibrate_from_user_click()
        if hwnd:
            self.config.set("target_window.window_title", wm.window_title)
            self.config.set("target_window.window_class", wm.window_class)
            log.info("C 模式目标窗口: %s", wm.window_title)
            return True
        return False

    def calibrate_click(self):
        log = setup_logging(self.config, role="c")
        import pyautogui
        self._prompt("将鼠标移到【静音时需要点击的位置】上，点确定记录")
        x, y = pyautogui.position()
        self.config.set("c_mode.click", {"x": x, "y": y})
        log.info("C 模式点击位置: (%s, %s)", x, y)


class AudioAutomationTool:
    """A/B 模式：目标程序与区域矫正（由 GUI 调用）"""

    REGION_LABELS = {
        "continue": "继续 continue",
        "repeat": "重复 repeat",
        "record": "录音 record",
        "play": "播放 play",
    }

    def __init__(self, config: ConfigManager = None, gui_parent=None):
        self.config = config or ConfigManager()
        self.gui_parent = gui_parent

    def _prompt(self, message: str):
        if self.gui_parent is not None:
            from tkinter import messagebox
            messagebox.showinfo("提示", message, parent=self.gui_parent)
        else:
            input(message)

    def calibrate_window(self):
        log = setup_logging(self.config, role="calibrate")
        wm = WindowManager()
        self._prompt("请先将 Dy 窗口置于前台，点确定记录目标窗口")
        hwnd = wm.calibrate_from_user_click()
        if hwnd:
            self.config.set("target_window.window_title", wm.window_title)
            self.config.set("target_window.window_class", wm.window_class)
            log.info("目标窗口: %s (%s)", wm.window_title, wm.window_class)
            return True
        log.warning("未捕获目标窗口")
        return False

    def calibrate_region(self, region: str):
        log = setup_logging(self.config, role="calibrate")
        import pyautogui
        label = self.REGION_LABELS.get(region, region)
        self._prompt(f"将鼠标移到 [{label}] 上，点确定记录")
        x, y = pyautogui.position()
        self.config.update_mouse_region(region, x, y)
        log.info("%s: (%s, %s)", region, x, y)

    def run_calibration(self):
        log = setup_logging(self.config, role="calibrate")
        log.info("开始完整区域矫正")
        if not self.calibrate_window():
            return
        for region in BUTTON_REGIONS:
            self.calibrate_region(region)
        log.info("完整矫正完成")


def main():
    _hide_console_on_windows()
    from gui.app import launch_gui
    launch_gui()


if __name__ == "__main__":
    main()
