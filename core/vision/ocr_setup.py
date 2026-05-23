"""Tesseract OCR 配置与调用"""
from __future__ import annotations

import logging
import os
import shutil
from typing import Any, Optional, Tuple

try:
    import pytesseract
    from PIL import Image

    HAS_PYTESSERACT = True
except ImportError:
    HAS_PYTESSERACT = False
    pytesseract = None  # type: ignore
    Image = None  # type: ignore

_configured_cmd: Optional[str] = None


def _resolve_tesseract_cmd(config: Any = None) -> Optional[str]:
    if config:
        cmd = (config.get("ocr.tesseract_cmd") or "").strip()
        if cmd and os.path.isfile(cmd):
            return cmd
    for candidate in (
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ):
        if os.path.isfile(candidate):
            return candidate
    return shutil.which("tesseract")


def configure_tesseract(config: Any = None, logger: Optional[logging.Logger] = None) -> Optional[str]:
    global _configured_cmd
    if not HAS_PYTESSERACT:
        return None
    cmd = _resolve_tesseract_cmd(config)
    if not cmd:
        _configured_cmd = None
        return None
    pytesseract.pytesseract.tesseract_cmd = cmd
    _configured_cmd = cmd
    tessdata = (config.get("ocr.tessdata_dir") or "").strip() if config else ""
    if tessdata and os.path.isdir(tessdata):
        os.environ["TESSDATA_PREFIX"] = tessdata
    if logger:
        logger.debug("Tesseract: %s", cmd)
    return cmd


def get_tesseract_status(config: Any = None) -> Tuple[bool, str, Optional[str]]:
    if not HAS_PYTESSERACT:
        return False, "未安装 pytesseract / Pillow", None
    cmd = configure_tesseract(config)
    if not cmd:
        return False, "未找到 tesseract.exe，请安装 Tesseract 或在配置中指定 ocr.tesseract_cmd", None
    try:
        pytesseract.get_tesseract_version()
    except Exception as e:
        return False, f"Tesseract 不可用: {e}", cmd
    return True, f"Tesseract 就绪: {cmd}", cmd


def image_to_text(image, config: Any = None, logger: Optional[logging.Logger] = None) -> str:
    if not HAS_PYTESSERACT or image is None:
        return ""
    if not configure_tesseract(config):
        return ""
    lang = (config.get("ocr.lang") or "eng") if config else "eng"
    try:
        return pytesseract.image_to_string(image, lang=lang) or ""
    except Exception as e:
        if logger:
            logger.warning("OCR 失败: %s", e)
        return ""
