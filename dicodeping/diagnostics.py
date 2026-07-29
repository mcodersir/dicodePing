from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .constants import LOG_FILE

_LOGGER_NAME = "dicodeping"
_configured = False
_handler: RotatingFileHandler | None = None
_enabled = False
_original_excepthook = sys.excepthook


def configure_logging(enabled: bool = False, level: str = "INFO") -> logging.Logger:
    global _configured, _handler, _enabled
    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(logging.DEBUG if str(level).upper() == "DEBUG" else logging.INFO)
    logger.propagate = False
    if _handler:
        logger.removeHandler(_handler)
        _handler.close()
        _handler = None
    logger.handlers = [handler for handler in logger.handlers if isinstance(handler, logging.NullHandler)]
    if enabled:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        _handler = RotatingFileHandler(LOG_FILE, maxBytes=1024 * 1024, backupCount=1, encoding="utf-8")
        _handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(threadName)s | %(name)s | %(message)s"))
        logger.addHandler(_handler)
    elif not logger.handlers:
        logger.addHandler(logging.NullHandler())

    def excepthook(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        logger.critical("Unhandled exception", exc_info=(exc_type, exc_value, exc_traceback))
        sys.__excepthook__(exc_type, exc_value, exc_traceback)

    if enabled:
        sys.excepthook = excepthook
    else:
        sys.excepthook = _original_excepthook
    _enabled = enabled
    _configured = True
    if enabled:
        logger.info("Diagnostic logging initialized: %s", Path(LOG_FILE))
    return logger


def diagnostics_enabled() -> bool:
    return _enabled


def get_logger(name: str | None = None) -> logging.Logger:
    root = logging.getLogger(_LOGGER_NAME)
    if not root.handlers:
        root.addHandler(logging.NullHandler())
    return logging.getLogger(f"{_LOGGER_NAME}.{name}" if name else _LOGGER_NAME)
