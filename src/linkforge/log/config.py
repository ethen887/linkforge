"""Configure the shared LinkForge file logger."""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path

_LOGGER_NAME = "linkforge"
_HANDLER_NAME = "linkforge.file"
_LOG_FILE_PREFIX = "linkforge_"
_LOG_FILE_SUFFIX = ".log"


def setup_logging(*, log_dir: Path | None = None) -> Path:
    """Configure DEBUG file logging and return the active log file path.

    Repeated calls for the same directory reuse the existing LinkForge-owned
    handler. Passing ``log_dir`` is primarily useful for isolated callers such
    as tests; normal application runs use the repository's ``logs`` directory.
    """
    destination = (log_dir or _default_log_dir()).resolve()
    destination.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    existing = _find_file_handler(logger)
    if existing is not None:
        current_path = Path(existing.baseFilename).resolve()
        if current_path.parent == destination:
            return current_path
        logger.removeHandler(existing)
        existing.close()

    log_file = _create_log_file(destination)
    handler = logging.FileHandler(log_file, encoding="utf-8")
    handler.set_name(_HANDLER_NAME)
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s.%(msecs)03d | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    logger.addHandler(handler)
    return log_file.resolve()


def _default_log_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "logs"
    return Path(__file__).resolve().parents[3] / "logs"


def _timestamped_filename() -> str:
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    return f"{_LOG_FILE_PREFIX}{timestamp}{_LOG_FILE_SUFFIX}"


def _create_log_file(destination: Path) -> Path:
    base_path = destination / _timestamped_filename()
    candidate = base_path
    collision_index = 1
    while True:
        try:
            candidate.touch(exist_ok=False)
        except FileExistsError:
            candidate = base_path.with_stem(f"{base_path.stem}_{collision_index}")
            collision_index += 1
        else:
            return candidate


def _find_file_handler(logger: logging.Logger) -> logging.FileHandler | None:
    for handler in logger.handlers:
        if isinstance(handler, logging.FileHandler) and handler.get_name() == _HANDLER_NAME:
            return handler
    return None
