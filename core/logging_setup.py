"""
日志初始化：Master/Slave 本地文件 + 控制台彩色输出
"""
import logging
import os
from logging.handlers import RotatingFileHandler
from typing import Optional

import colorlog

_configured_loggers: set[str] = set()


def setup_logging(config, role: str = "app") -> logging.Logger:
    """根据配置创建 logger，role 用于区分 master/slave 日志文件名"""
    log_cfg = config.get("logging", {}) or {}
    level_name = log_cfg.get("level", "INFO")
    level = getattr(logging, str(level_name).upper(), logging.INFO)

    log_file = log_cfg.get("file", "logs/automation.log")
    if role and role != "app":
        base, ext = os.path.splitext(log_file)
        log_file = f"{base}_{role}{ext or '.log'}"

    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if not os.path.isabs(log_file):
        log_file = os.path.join(project_root, log_file)
    os.makedirs(os.path.dirname(log_file), exist_ok=True)

    logger_name = f"audioauto.{role}"
    if logger_name in _configured_loggers:
        return logging.getLogger(logger_name)

    logger = logging.getLogger(logger_name)
    logger.setLevel(level)
    logger.handlers.clear()
    logger.propagate = False

    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=log_cfg.get("max_bytes", 10 * 1024 * 1024),
        backupCount=log_cfg.get("backup_count", 5),
        encoding="utf-8",
    )
    file_handler.setFormatter(logging.Formatter(fmt, datefmt=datefmt))
    logger.addHandler(file_handler)

    try:
        from gui.log_view import GuiLogBus, GuiLogHandler
        use_gui = GuiLogBus.is_active()
    except ImportError:
        use_gui = False
        GuiLogHandler = None  # type: ignore

    if use_gui and GuiLogHandler is not None:
        logger.addHandler(GuiLogHandler())
    else:
        console = colorlog.StreamHandler()
        console.setFormatter(colorlog.ColoredFormatter(
            "%(log_color)s" + fmt,
            datefmt=datefmt,
            log_colors={
                "DEBUG": "cyan",
                "INFO": "green",
                "WARNING": "yellow",
                "ERROR": "red",
                "CRITICAL": "bold_red",
            },
        ))
        logger.addHandler(console)

    _configured_loggers.add(logger_name)
    logger.info("日志已初始化: %s", log_file)
    return logger
