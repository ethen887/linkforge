"""Tests for shared production application composition."""

from collections.abc import Callable

import linkforge.composition as composition_module
from linkforge.application import ApplicationConfig
from linkforge.config import BrowserConfig, ModelConfig


def test_create_application_builds_production_runtime(monkeypatch) -> None:
    progress: list[str] = []
    callback = progress.append
    config = ApplicationConfig(
        course_url="https://example.test/course",
        browser_config=BrowserConfig(),
        model_config=ModelConfig(
            api_key="secret",
            base_url="https://models.example.test/v1",
            model_name="model",
        ),
        on_course_url_changed=callback,
    )
    submitter = object()
    platform = object()
    captured: dict[str, object] = {}

    monkeypatch.setattr(composition_module, "ChaoxingQuizSubmitter", lambda: submitter)

    def create_platform(*, quiz_submitter: object, on_course_url_changed: Callable[[str], None]) -> object:
        assert quiz_submitter is submitter
        assert on_course_url_changed is callback
        return platform

    def create_runtime(*, config: ApplicationConfig, platform: object) -> object:
        captured["config"] = config
        captured["platform"] = platform
        return "application"

    monkeypatch.setattr(composition_module, "ChaoxingPlatformRuntime", create_platform)
    monkeypatch.setattr(composition_module, "LinkForgeApplication", create_runtime)

    assert composition_module.create_application(config) == "application"
    assert captured == {"config": config, "platform": platform}
