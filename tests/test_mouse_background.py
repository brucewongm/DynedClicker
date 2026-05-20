"""
鼠标/窗口测试（manual 项需人工操作，默认 pytest 不执行）
"""
import os
import sys

import pytest
import win32gui

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.config_manager import ConfigManager
from core.mouse.background_click import BackgroundClicker
from core.mouse.window_tools import WindowManager


def test_window_manager():
    manager = WindowManager()
    hwnd = manager.get_foreground_window()
    assert hwnd is not None
    assert win32gui.GetWindowText(hwnd) is not None


@pytest.mark.manual
def test_background_click():
    config = ConfigManager()
    manager = WindowManager()
    clicker = BackgroundClicker(manager)
    hwnd = manager.calibrate_from_user_click()
    assert hwnd is not None
    import pyautogui
    x, y = pyautogui.position()
    assert clicker.click_screen(x, y)


@pytest.mark.manual
def test_region_click():
    config = ConfigManager()
    manager = WindowManager()
    clicker = BackgroundClicker(manager)
    hwnd = manager.calibrate_from_user_click()
    assert hwnd is not None
    for region in ("record", "play", "continue"):
        coords = config.get_mouse_region(region)
        if coords["x"] == 0 and coords["y"] == 0:
            continue
        assert clicker.click_region(region, config)


if __name__ == "__main__":
    test_window_manager()
    if input("运行后台点击测试? (y/n): ").lower() == "y":
        test_background_click()
    if input("运行区域点击测试? (y/n): ").lower() == "y":
        test_region_click()
