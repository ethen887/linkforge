"""Unit tests for LinkForge file logging configuration."""

from __future__ import annotations

import logging
import re
import sys
from pathlib import Path

import pytest

from linkforge.log import setup_logging
from linkforge.log.config import _default_log_dir


@pytest.fixture(autouse=True)
def remove_linkforge_file_handler() -> None:
    """Keep process-global logging state isolated between tests."""
    yield
    logger = logging.getLogger("linkforge")
    for handler in tuple(logger.handlers):
        if handler.get_name() == "linkforge.file":
            logger.removeHandler(handler)
            handler.close()


def _flush_linkforge_handlers() -> None:
    for handler in logging.getLogger("linkforge").handlers:
        handler.flush()


def test_setup_logging_creates_timestamped_file_and_records_all_required_levels(
    tmp_path: Path,
) -> None:
    log_dir = tmp_path / "logs"

    log_file = setup_logging(log_dir=log_dir)
    logger = logging.getLogger("linkforge.test")
    logger.debug("debug detail")
    logger.info("info lifecycle")
    try:
        raise RuntimeError("test failure")
    except RuntimeError:
        logger.exception("operation failed")
    _flush_linkforge_handlers()

    assert log_dir.is_dir()
    assert log_file.parent == log_dir.resolve()
    assert re.fullmatch(r"linkforge_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}\.log", log_file.name)
    assert log_file.is_file()

    content = log_file.read_text(encoding="utf-8")
    assert "DEBUG" in content and "linkforge.test" in content and "debug detail" in content
    assert "INFO" in content and "info lifecycle" in content
    assert "operation failed" in content
    assert "Traceback (most recent call last)" in content
    assert "RuntimeError: test failure" in content


def test_setup_logging_is_idempotent_and_does_not_duplicate_records(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"

    first_path = setup_logging(log_dir=log_dir)
    second_path = setup_logging(log_dir=log_dir)
    logger = logging.getLogger("linkforge.test")
    logger.info("written exactly once")
    _flush_linkforge_handlers()

    owned_handlers = [
        handler
        for handler in logging.getLogger("linkforge").handlers
        if handler.get_name() == "linkforge.file"
    ]
    assert first_path == second_path
    assert len(owned_handlers) == 1
    assert first_path.read_text(encoding="utf-8").count("written exactly once") == 1


def test_frozen_logs_follow_executable_not_working_directory(tmp_path, monkeypatch):
    executable = tmp_path / "中文 Portable" / "LinkForge.exe"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(executable))
    monkeypatch.chdir(tmp_path)
    log_file = setup_logging()
    assert log_file.parent == executable.parent / "logs"


def test_source_log_location_is_unchanged(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert _default_log_dir() == Path(__file__).resolve().parents[3] / "logs"
