"""集中日志配置。

日志默认写到 ``%APPDATA%/CrushChatAnalyzer/logs/app.log``，
方便用户反馈问题时直接打包日志目录。
"""
from __future__ import annotations

from logging.handlers import RotatingFileHandler
import logging
import sys
import threading

from .config import app_home

_LOGGER_NAME = "crush_analyzer"
_initialized = False


def init_logging(level: int = logging.DEBUG) -> logging.Logger:
    global _initialized
    logger = logging.getLogger(_LOGGER_NAME)
    if _initialized:
        return logger
    logger.setLevel(level)
    logger.propagate = False

    log_dir = app_home() / "logs"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            log_dir / "app.log",
            maxBytes=5 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
    except Exception:
        handler = logging.StreamHandler(sys.stderr)

    handler.setLevel(level)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s | %(levelname)s | %(threadName)s | %(name)s:%(lineno)d | %(message)s"
        )
    )
    logger.addHandler(handler)
    _initialized = True
    logger.info("=" * 60)
    logger.info("日志系统启动，日志目录：%s", log_dir)
    logger.info("Python: %s", sys.version.replace("\n", " "))
    logger.info("frozen: %s", getattr(sys, "frozen", False))
    return logger


def get_logger(name: str = "") -> logging.Logger:
    return logging.getLogger(f"{_LOGGER_NAME}.{name}" if name else _LOGGER_NAME)


def log_dir():
    return app_home() / "logs"


def log_exception(logger: logging.Logger, message: str, exc: BaseException) -> None:
    logger.error("%s: %s: %s", message, type(exc).__name__, exc, exc_info=True)
