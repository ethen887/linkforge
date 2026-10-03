"""Regression coverage for manual login before course task dispatch."""

import logging
from collections.abc import Callable, Sequence

import pytest

from linkforge.application import ApplicationConfig, LinkForgeApplication
from linkforge.application.task_runner import UnknownTaskError
from linkforge.browser.exceptions import BrowserClosedError, BrowserError
from linkforge.config import BrowserConfig, ModelConfig
from linkforge.platforms.chaoxing.runtime import ChaoxingPlatformRuntime
from linkforge.platforms.chaoxing.startup import ChaoxingStartupTimeoutError, ChaoxingStartupWait
from tests.fakes import FakeBrowser
from tests.unit.platforms.chaoxing.test_runtime import FakeLLM, FakeQuizSubmitter


def _frame(
    *, login: bool = False, content: bool = False, active_tabs: int = 0, home: bool = False
) -> dict[str, object]:
    return {
        "login_page": login,
        "content_ready": content,
        "active_tab_count": active_tabs,
        "personal_home": home,
    }


_LOGIN = (_frame(login=True),)
_LOADING = (_frame(),)
_HOME = (_frame(home=True),)
_READY = (_frame(active_tabs=1), _frame(content=True))


class StartupBrowser(FakeBrowser):
    def __init__(self, snapshots: Sequence[tuple[object, ...] | BrowserError]) -> None:
        super().__init__()
        self.snapshots = snapshots
        self.probe_count = 0
        self.closed = False

    def evaluate_in_frames(self, expression: str) -> tuple[object, ...]:
        assert not self.closed
        index = min(self.probe_count, len(self.snapshots) - 1)
        self.probe_count += 1
        result = self.snapshots[index]
        if isinstance(result, BrowserError):
            raise result
        return result

    def close(self) -> None:
        self.closed = True
        super().close()


class Clock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []
        self.on_sleep: Callable[[], None] = lambda: None

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds
        self.sleeps.append(seconds)
        self.on_sleep()


def _wait(clock: Clock) -> ChaoxingStartupWait:
    return ChaoxingStartupWait(
        login_timeout_seconds=10,
        page_timeout_seconds=2,
        poll_interval_seconds=0.5,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )


def test_logged_in_course_starts_without_extra_wait() -> None:
    clock = Clock()
    browser = StartupBrowser([_READY])

    assert _wait(clock).wait(browser=browser, course_url="course", should_stop=lambda: False)

    assert browser.probe_count == 1
    assert clock.sleeps == []
    assert browser.action_calls == []


def test_manual_login_waits_for_course_dom_not_just_leaving_login_page(caplog, monkeypatch) -> None:
    startup_logger = logging.getLogger("linkforge.platforms.chaoxing.startup")
    monkeypatch.setattr(startup_logger, "handlers", [caplog.handler])
    monkeypatch.setattr(startup_logger, "propagate", False)
    clock = Clock()
    browser = StartupBrowser([_LOGIN, _LOGIN, _LOADING, _READY])
    clock.on_sleep = lambda: pytest.fail("Browser closed during login") if browser.closed else None

    with caplog.at_level("INFO", logger=startup_logger.name):
        assert _wait(clock).wait(browser=browser, course_url="course", should_stop=lambda: False)

    assert browser.probe_count == 4
    assert len(clock.sleeps) == 3
    assert caplog.text.count("Chaoxing manual login required") == 1
    assert "Chaoxing course page ready" in caplog.text


def test_login_landing_in_personal_space_reopens_original_course_once(caplog, monkeypatch) -> None:
    startup_logger = logging.getLogger("linkforge.platforms.chaoxing.startup")
    monkeypatch.setattr(startup_logger, "handlers", [caplog.handler])
    monkeypatch.setattr(startup_logger, "propagate", False)
    clock = Clock()
    browser = StartupBrowser([_LOGIN, _HOME, _HOME, _READY])
    sensitive_url = "https://mooc1.chaoxing.com/course?token=private-value"

    with caplog.at_level("DEBUG", logger=startup_logger.name):
        assert _wait(clock).wait(browser=browser, course_url=sensitive_url, should_stop=lambda: False)

    assert browser.action_calls == [("open", sensitive_url)]
    assert sensitive_url not in caplog.text
    assert "private-value" not in caplog.text


def test_wait_stops_without_detecting_tasks() -> None:
    clock = Clock()
    browser = StartupBrowser([_LOGIN])

    assert not _wait(clock).wait(browser=browser, course_url="course", should_stop=lambda: clock.now > 0)

    assert clock.sleeps == [0.5]
    assert browser.probe_count == 1


def test_stop_before_preparation_does_not_probe_or_navigate() -> None:
    clock = Clock()
    browser = StartupBrowser([_LOGIN])

    assert not _wait(clock).wait(browser=browser, course_url="course", should_stop=lambda: True)

    assert browser.probe_count == 0
    assert browser.action_calls == []
    assert clock.sleeps == []


def test_login_wait_deadline_is_not_reset_by_repeated_login_pages() -> None:
    clock = Clock()
    browser = StartupBrowser([_LOADING, _LOGIN])

    with pytest.raises(ChaoxingStartupTimeoutError):
        _wait(clock).wait(browser=browser, course_url="course", should_stop=lambda: False)

    assert clock.now == 10.5


def test_login_page_cannot_start_runner_even_if_course_frames_are_present() -> None:
    clock = Clock()
    browser = StartupBrowser([_LOGIN + _READY])

    with pytest.raises(ChaoxingStartupTimeoutError):
        _wait(clock).wait(browser=browser, course_url="course", should_stop=lambda: False)

    assert clock.now == 10


@pytest.mark.parametrize(
    ("snapshot", "seconds"),
    [(_LOGIN, 10), (_LOADING, 2), ((_frame(content=True),), 2), ((_READY + _READY), 2)],
)
def test_unready_or_ambiguous_page_times_out(snapshot, seconds) -> None:
    clock = Clock()
    browser = StartupBrowser([snapshot])

    with pytest.raises(ChaoxingStartupTimeoutError):
        _wait(clock).wait(browser=browser, course_url="course", should_stop=lambda: False)

    assert clock.now == seconds


def test_transient_navigation_errors_are_retried() -> None:
    clock = Clock()
    browser = StartupBrowser([_LOGIN, BrowserError("navigation context replaced"), _READY])

    assert _wait(clock).wait(browser=browser, course_url="course", should_stop=lambda: False)
    assert len(clock.sleeps) == 2


def test_browser_closed_error_propagates_without_waiting_for_login_timeout() -> None:
    clock = Clock()
    browser = StartupBrowser([BrowserClosedError("closed")])

    with pytest.raises(BrowserClosedError):
        _wait(clock).wait(browser=browser, course_url="course", should_stop=lambda: False)
    assert clock.sleeps == []


@pytest.mark.parametrize("outcome", ["login", "stop", "timeout", "unknown"])
def test_application_prepares_before_building_runner_and_always_cleans_up(monkeypatch, outcome) -> None:
    clock = Clock()
    snapshots = [_LOGIN, _LOADING, _READY] if outcome == "login" else [_LOGIN]
    if outcome == "unknown":
        snapshots = [_READY]
    browser = StartupBrowser(snapshots)
    platform = ChaoxingPlatformRuntime(quiz_submitter=FakeQuizSubmitter(), startup_wait=_wait(clock))
    events: list[str] = []

    class Runner:
        def run(self, *, should_stop: Callable[[], bool]) -> None:
            events.append("run")
            assert not browser.closed
            if outcome == "unknown":
                raise UnknownTaskError("Unable to determine the current course task.")

    def build_runner(**_kwargs: object) -> Runner:
        events.append("build")
        assert browser.probe_count == (3 if outcome == "login" else 1)
        return Runner()

    monkeypatch.setattr(platform, "build_runner", build_runner)
    application = LinkForgeApplication(
        config=ApplicationConfig(
            course_url="https://mooc1.chaoxing.com/mycourse/studentstudy",
            browser_config=BrowserConfig(),
            model_config=ModelConfig(api_key="unused", base_url="unused", model_name="unused"),
        ),
        platform=platform,
        browser_factory=lambda _config: browser,
        llm_factory=lambda _config: FakeLLM(),
    )
    if outcome == "stop":
        clock.on_sleep = application.stop
    if outcome == "timeout":
        with pytest.raises(ChaoxingStartupTimeoutError):
            application.run()
    elif outcome == "unknown":
        with pytest.raises(UnknownTaskError):
            application.run()
    else:
        application.run()

    assert browser.closed
    assert events == (["build", "run"] if outcome in {"login", "unknown"} else [])
