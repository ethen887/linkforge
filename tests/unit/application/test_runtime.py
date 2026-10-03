"""Unit tests for the platform-neutral application runtime."""

import ast
import inspect
from collections.abc import Callable

import pytest

import linkforge.application.runtime as runtime_module
from linkforge.application.runtime import ApplicationConfig, LinkForgeApplication
from linkforge.application.task_runner import TaskRunner
from linkforge.browser.base import Browser
from linkforge.config.settings import BrowserConfig, ModelConfig
from linkforge.llm.base import LLM, LLMMessage, LLMResponse
from tests.fakes import FakeBrowser


class RecordingBrowser(FakeBrowser):
    def __init__(self, events: list[str], *, open_error: Exception | None = None) -> None:
        super().__init__()
        self._events = events
        self._open_error = open_error

    def start(self) -> None:
        self._events.append("browser.start")

    def open(self, url: str) -> None:
        self._events.append(f"browser.open:{url}")
        if self._open_error is not None:
            raise self._open_error
        super().open(url)

    def close(self) -> None:
        self._events.append("browser.close")
        super().close()


class FakeLLM(LLM):
    def call_model(
        self,
        model: str,
        messages: list[LLMMessage],
        tools: list[dict[str, object]],
    ) -> LLMResponse:
        raise AssertionError("The application runtime must not call the model directly.")


class RecordingTaskRunner(TaskRunner):
    def __init__(self, events: list[str], *, run_error: Exception | None = None) -> None:
        self._events = events
        self._run_error = run_error
        self.should_stop: Callable[[], bool] | None = None

    def run(self, *, should_stop: Callable[[], bool] | None = None) -> None:
        self._events.append("runner.run")
        self.should_stop = should_stop
        if self._run_error is not None:
            raise self._run_error


class RecordingPlatformRuntime:
    def __init__(
        self,
        events: list[str],
        runner: TaskRunner,
        *,
        build_error: Exception | None = None,
        prepare_error: Exception | None = None,
        ready: bool = True,
    ) -> None:
        self._events = events
        self._runner = runner
        self._build_error = build_error
        self._prepare_error = prepare_error
        self._ready = ready
        self.stop_during_prepare: Callable[[], None] | None = None
        self.received: tuple[Browser, LLM, str] | None = None

    def prepare(self, *, browser: Browser, course_url: str, should_stop: Callable[[], bool]) -> bool:
        self._events.append("platform.prepare")
        assert browser.current_url() == course_url
        if self._prepare_error is not None:
            raise self._prepare_error
        if self.stop_during_prepare is not None:
            self.stop_during_prepare()
            assert should_stop()
            return False
        return self._ready

    def build_runner(self, *, browser: Browser, llm: LLM, model: str) -> TaskRunner:
        self._events.append("platform.build_runner")
        self.received = (browser, llm, model)
        if self._build_error is not None:
            raise self._build_error
        return self._runner


def _config(course_url: str = "https://courses.example.test/course") -> ApplicationConfig:
    return ApplicationConfig(
        course_url=course_url,
        browser_config=BrowserConfig(
            headless=True,
            timeout_ms=5_000,
            profile_dir="browser-profile",
        ),
        model_config=ModelConfig(
            api_key="test-key",
            base_url="https://models.example.test/v1",
            model_name="test-model",
        ),
    )


def _application(
    *,
    events: list[str],
    browser: Browser,
    llm: LLM,
    platform: RecordingPlatformRuntime,
) -> LinkForgeApplication:
    config = _config()

    def browser_factory(received: BrowserConfig) -> Browser:
        events.append("browser.factory")
        assert received is config.browser_config
        return browser

    def llm_factory(received: ModelConfig) -> LLM:
        events.append("llm.factory")
        assert received is config.model_config
        return llm

    return LinkForgeApplication(
        config=config,
        platform=platform,
        browser_factory=browser_factory,
        llm_factory=llm_factory,
    )


def test_run_owns_lifecycle_and_passes_resources_to_platform() -> None:
    events: list[str] = []
    browser = RecordingBrowser(events)
    llm = FakeLLM()
    runner = RecordingTaskRunner(events)
    platform = RecordingPlatformRuntime(events, runner)
    application = _application(events=events, browser=browser, llm=llm, platform=platform)

    application.run()

    assert events == [
        "browser.factory",
        "llm.factory",
        "browser.start",
        "browser.open:https://courses.example.test/course",
        "platform.prepare",
        "platform.build_runner",
        "runner.run",
        "browser.close",
    ]
    assert browser.current_url() == "https://courses.example.test/course"
    assert platform.received == (browser, llm, "test-model")
    assert runner.should_stop is not None
    assert runner.should_stop() is False


@pytest.mark.parametrize("failure_stage", ["open", "prepare", "build", "run"])
def test_run_closes_browser_and_propagates_errors(failure_stage: str) -> None:
    events: list[str] = []
    error = RuntimeError(f"{failure_stage} failed")
    browser = RecordingBrowser(events, open_error=error if failure_stage == "open" else None)
    runner = RecordingTaskRunner(events, run_error=error if failure_stage == "run" else None)
    platform = RecordingPlatformRuntime(
        events,
        runner,
        build_error=error if failure_stage == "build" else None,
        prepare_error=error if failure_stage == "prepare" else None,
    )
    application = _application(
        events=events,
        browser=browser,
        llm=FakeLLM(),
        platform=platform,
    )

    with pytest.raises(RuntimeError, match=f"{failure_stage} failed") as exc_info:
        application.run()

    assert exc_info.value is error
    assert events[-1] == "browser.close"
    assert events.count("browser.close") == 1


def test_stop_is_observed_by_runner_without_closing_browser_directly() -> None:
    events: list[str] = []
    browser = RecordingBrowser(events)
    runner = RecordingTaskRunner(events)
    platform = RecordingPlatformRuntime(events, runner)
    application = _application(
        events=events,
        browser=browser,
        llm=FakeLLM(),
        platform=platform,
    )

    application.stop()

    assert events == []

    application.run()

    assert runner.should_stop is not None
    assert runner.should_stop() is True
    assert events[-1] == "browser.close"


def test_stop_during_preparation_closes_browser_without_building_tasks() -> None:
    events: list[str] = []
    browser = RecordingBrowser(events)
    runner = RecordingTaskRunner(events)
    platform = RecordingPlatformRuntime(events, runner)
    application = _application(events=events, browser=browser, llm=FakeLLM(), platform=platform)
    platform.stop_during_prepare = application.stop

    application.run()

    assert "platform.prepare" in events
    assert "platform.build_runner" not in events
    assert "runner.run" not in events
    assert events[-1] == "browser.close"


@pytest.mark.parametrize("course_url", ["", " ", "\t"])
def test_application_config_rejects_empty_course_url(course_url: str) -> None:
    with pytest.raises(ValueError, match="course_url must not be empty"):
        _config(course_url)


def test_application_runtime_has_no_platform_or_playwright_dependency() -> None:
    syntax_tree = ast.parse(inspect.getsource(runtime_module))
    imported_modules = {
        node.module
        for node in ast.walk(syntax_tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    imported_modules.update(
        alias.name for node in ast.walk(syntax_tree) if isinstance(node, ast.Import) for alias in node.names
    )

    assert not any(
        module == "playwright" or module.startswith("playwright.") for module in imported_modules
    )
    assert not any(module.startswith("linkforge.platforms") for module in imported_modules)
