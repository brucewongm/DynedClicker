"""日志：文件轮转 + GUI / 控制台"""
from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler

import colorlog

_configured: set[str] = set()


def setup_logging(config, role: str = "dyclicker") -> logging.Logger:
    log_cfg = config.get("logging", {}) or {}
    level = getattr(logging, str(log_cfg.get("level", "INFO")).upper(), logging.INFO)
    log_file = log_cfg.get("file", "logs/dyclicker.log")
    if role and role != "app":
        base, ext = os.path.splitext(log_file)
        log_file = f"{base}_{role}{ext or '.log'}"

    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if not os.path.isabs(log_file):
        log_file = os.path.join(project_root, log_file)
    os.makedirs(os.path.dirname(log_file), exist_ok=True)

    logger_name = f"dyclicker.{role}"
    if logger_name in _configured:
        return logging.getLogger(logger_name)

    logger = logging.getLogger(logger_name)
    logger.setLevel(level)
    logger.handlers.clear()
    logger.propagate = False

    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"
    fh = RotatingFileHandler(
        log_file,
        maxBytes=int(log_cfg.get("max_bytes", 10 * 1024 * 1024)),
        backupCount=int(log_cfg.get("backup_count", 5)),
        encoding="utf-8",
    )
    fh.setFormatter(logging.Formatter(fmt, datefmt=datefmt))
    logger.addHandler(fh)

    try:
        from gui.log_view import GuiLogBus, GuiLogHandler

        use_gui = GuiLogBus.is_active()
    except ImportError:
        use_gui = False
        GuiLogHandler = None  # type: ignore

    if use_gui and GuiLogHandler is not None:
        logger.addHandler(GuiLogHandler())
    else:
        ch = colorlog.StreamHandler()
        ch.setFormatter(
            colorlog.ColoredFormatter(
                "%(log_color)s" + fmt,
                datefmt=datefmt,
                log_colors={
                    "DEBUG": "cyan",
                    "INFO": "green",
                    "WARNING": "yellow",
                    "ERROR": "red",
                    "CRITICAL": "bold_red",
                },
            )
        )
        logger.addHandler(ch)

    _configured.add(logger_name)
    logger.info("日志已初始化: %s", log_file)
    return logger
