"""Unit tests for the LinkForge development entry point."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

import linkforge.main as main_module
from linkforge.application import ApplicationConfig
from linkforge.log import setup_logging

_REQUIRED_ENV = {
    "LINKFORGE_COURSE_URL": "https://example.test/course",
    "LINKFORGE_PROVIDER": "qwen",
    "LINKFORGE_MODEL": "qwen-plus",
    "LINKFORGE_API_KEY": "test-secret-key",
}


@pytest.fixture(autouse=True)
def avoid_writing_default_logs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    monkeypatch.setattr(main_module, "setup_logging", lambda: tmp_path / "unused.log")
    yield
    logger = logging.getLogger("linkforge")
    for handler in tuple(logger.handlers):
        if handler.get_name() == "linkforge.file":
            logger.removeHandler(handler)
            handler.close()


@pytest.mark.parametrize("missing_name", tuple(_REQUIRED_ENV))
def test_main_reports_each_missing_required_environment_variable(
    monkeypatch: pytest.MonkeyPatch,
    missing_name: str,
) -> None:
    for name, value in _REQUIRED_ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv(missing_name)

    with pytest.raises(
        RuntimeError,
        match=rf"^Missing required environment variable: {missing_name}$",
    ):
        main_module.main()


def test_main_composes_and_runs_application_without_starting_real_resources(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    for name, value in _REQUIRED_ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("LINKFORGE_PROFILE_DIR", " D:/profiles/linkforge ")

    captured: dict[str, Any] = {}
    submitter = object()
    platform = object()

    def create_platform(*, quiz_submitter: object) -> object:
        captured["quiz_submitter"] = quiz_submitter
        return platform

    class FakeApplication:
        def __init__(
            self,
            *,
            config: ApplicationConfig,
            platform: object,
        ) -> None:
            captured["config"] = config
            captured["platform"] = platform

        def run(self) -> None:
            captured["run_called"] = True

    monkeypatch.setattr(main_module, "ChaoxingQuizSubmitter", lambda: submitter)
    monkeypatch.setattr(main_module, "ChaoxingPlatformRuntime", create_platform)
    monkeypatch.setattr(main_module, "LinkForgeApplication", FakeApplication)

    main_module.main()

    config = captured["config"]
    assert isinstance(config, ApplicationConfig)
    assert config.course_url == "https://example.test/course"
    assert config.browser_config.headless is False
    assert config.browser_config.timeout_ms == 15_000
    assert config.browser_config.profile_dir == "D:/profiles/linkforge"
    assert config.model_config.api_key == "test-secret-key"
    assert config.model_config.model_name == "qwen-plus"
    assert config.model_config.base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert config.model_config.protocol == "openai"
    assert captured["quiz_submitter"] is submitter
    assert captured["platform"] is platform
    assert captured["run_called"] is True

    output = capsys.readouterr().out
    assert "LinkForge starting..." in output
    assert "Provider: qwen" in output
    assert "Model: qwen-plus" in output
    assert "test-secret-key" not in output


def test_main_logging_never_writes_api_key(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    for name, value in _REQUIRED_ENV.items():
        monkeypatch.setenv(name, value)

    log_dir = tmp_path / "logs"
    monkeypatch.setattr(main_module, "setup_logging", lambda: setup_logging(log_dir=log_dir))

    class FakeApplication:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def run(self) -> None:
            pass

    monkeypatch.setattr(main_module, "LinkForgeApplication", FakeApplication)
    main_module.main()

    for handler in logging.getLogger("linkforge").handlers:
        handler.flush()
    content = next(log_dir.glob("*.log")).read_text(encoding="utf-8")
    assert _REQUIRED_ENV["LINKFORGE_API_KEY"] not in content
