"""Logging setup: rotating log file in ``logs/`` plus optional console output."""
from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOGGER_NAME = "newspulse"
logging.getLogger(LOGGER_NAME).addHandler(logging.NullHandler())  # silent until setup_logging() is called
_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"


def setup_logging(logs_dir: Path, level: str = "INFO", console: bool = False) -> logging.Logger:
    """Configure the application logger. Safe to call more than once."""
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.propagate = False

    for handler in list(logger.handlers):
        if getattr(handler, "_newspulse", False):
            logger.removeHandler(handler)
            handler.close()

    logs_dir.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        logs_dir / "newspulse.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(logging.Formatter(_FORMAT))
    file_handler._newspulse = True  # type: ignore[attr-defined]
    logger.addHandler(file_handler)

    if console:
        stream = logging.StreamHandler(sys.stderr)
        stream.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
        stream._newspulse = True  # type: ignore[attr-defined]
        logger.addHandler(stream)
    return logger


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"{LOGGER_NAME}.{name}")
