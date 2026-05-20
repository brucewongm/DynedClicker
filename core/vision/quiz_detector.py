"""
Dy 互动问答界面：截图 + 关键词定位可点击区域
"""
import re
from typing import List, Optional, Tuple

from PIL import ImageGrab

try:
    import pytesseract
    HAS_OCR = True
except ImportError:
    HAS_OCR = False


class QuizDetector:
    """检测并返回首个可点击选项的屏幕坐标"""

    def __init__(self, config, window_manager, logger):
        self.config = config
        self.window_manager = window_manager
        self.logger = logger
        self.enabled = config.get("quiz.enabled", True)
        keywords = config.get("quiz.keywords") or [
            "yes", "no", "true", "false",
        ]
        self.keywords = [k.lower() for k in keywords]
        self.default_choice = config.get("quiz.default_choice", "first")

    def capture_window_image(self):
        if not self.window_manager.ensure_target_window(self.config):
            return None
        import win32gui
        hwnd = self.window_manager.target_hwnd
        rect = win32gui.GetWindowRect(hwnd)
        return ImageGrab.grab(bbox=rect)

    def detect_click_point(self) -> Optional[Tuple[int, int]]:
        """若检测到问答界面，返回屏幕坐标；否则 None"""
        if not self.enabled:
            return None

        image = self.capture_window_image()
        if image is None:
            return None

        if not HAS_OCR:
            self.logger.warning("未安装 pytesseract，跳过问答识别")
            return None

        try:
            data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
        except Exception as e:
            self.logger.warning("OCR 失败: %s", e)
            return None

        candidates: List[Tuple[int, int, str]] = []
        n = len(data["text"])
        for i in range(n):
            text = (data["text"][i] or "").strip().lower()
            if not text:
                continue
            if not any(kw in text for kw in self.keywords):
                continue
            conf = int(float(data["conf"][i])) if str(data["conf"][i]).isdigit() else 0
            if conf < 30:
                continue
            x = data["left"][i] + data["width"][i] // 2
            y = data["top"][i] + data["height"][i] // 2
            import win32gui
            hwnd = self.window_manager.target_hwnd
            left, top, _, _ = win32gui.GetWindowRect(hwnd)
            candidates.append((left + x, top + y, text))

        if not candidates:
            return None

        if self.default_choice == "last":
            point = candidates[-1]
        else:
            point = candidates[0]

        self.logger.info("检测到问答选项 '%s' @ (%s, %s)", point[2], point[0], point[1])
        return point[0], point[1]

    def has_quiz_visible(self) -> bool:
        return self.detect_click_point() is not None
