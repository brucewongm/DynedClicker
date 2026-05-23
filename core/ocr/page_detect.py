"""页面 OCR：step1 判定与 back 安全"""
from __future__ import annotations

from typing import Any, List, Tuple

from core.vision.ocr_setup import get_tesseract_status, image_to_text


def _keywords(config: Any) -> List[str]:
    kws = config.get("ocr.step1_keywords") if config else None
    if isinstance(kws, list) and kws:
        return [str(k) for k in kws]
    return ["Company", "Description"]


def is_step1_text(text: str, config: Any = None) -> bool:
    t = (text or "").lower()
    keys = [k.lower() for k in _keywords(config)]
    return all(k in t for k in keys)


def ocr_target_window(window_manager, config, logger=None) -> Tuple[str, bool]:
    ok, msg, _ = get_tesseract_status(config)
    if not ok:
        if logger:
            logger.warning("OCR 不可用: %s", msg.split("\n")[0])
        return "", False
    image = window_manager.capture_window_image()
    if image is None:
        if logger:
            logger.warning("无法截取目标窗口图像")
        return "", False
    text = image_to_text(image, config, logger)
    step1 = is_step1_text(text, config)
    if logger:
        logger.info("OCR 判定 step1=%s", step1)
    return text, step1


def safe_click_back(clicker, config, window_manager, logger=None) -> bool:
    _, step1 = ocr_target_window(window_manager, config, logger)
    if step1:
        if logger:
            logger.warning("当前 step1 页面，跳过 back 点击")
        return False
    pt = config.get("global_buttons.back") or {"x": 442, "y": 955}
    if logger:
        logger.info("点击 back @ (%s, %s)", pt["x"], pt["y"])
    return clicker.click_at(int(pt["x"]), int(pt["y"]), config)
