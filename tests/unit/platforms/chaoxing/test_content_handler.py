"""Unit tests for evidence-bounded Chaoxing content navigation."""

import pytest

from linkforge.application.task_runner import TaskHandler
from linkforge.platforms.chaoxing.content_handler import (
    ChaoxingContentHandlerConfig,
    ChaoxingContentTaskHandler,
)
from linkforge.platforms.chaoxing.exceptions import ContentNavigationError
from tests.fakes import FakeBrowser

_PAGE_URL = "https://mooc1.chaoxing.com/mycourse/studentstudy"
_CONTENT_URL = "https://mooc1.chaoxing.com/mooc-ans/knowledge/cards?num=1"


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class ScriptedContentBrowser(FakeBrowser):
    def __init__(self, states: list[tuple[object, ...]]) -> None:
        super().__init__()
        self._states = states
        self._index = 0

    def evaluate_in_frames(self, expression: str) -> tuple[object, ...]:
        self.frame_evaluation_calls.append(expression)
        index = min(self._index, len(self._states) - 1)
        self._index += 1
        return self._states[index]


def _state(
    *,
    active_index: int,
    has_next: bool,
    modules: list[dict[str, object]] | None = None,
) -> tuple[object, ...]:
    return (
        {
            "frame_url": _PAGE_URL,
            "active_tab_count": 1,
            "active_tab_index": active_index,
            "has_next_tab": has_next,
            "modules": [],
            "video_count": 0,
            "video": None,
        },
        {
            "frame_url": _CONTENT_URL,
            "active_tab_count": 0,
            "active_tab_index": None,
            "has_next_tab": False,
            "modules": list(modules or []),
            "video_count": 0,
            "video": None,
        },
    )


def _handler(browser: FakeBrowser, clock: FakeClock) -> ChaoxingContentTaskHandler:
    return ChaoxingContentTaskHandler(
        browser,
        config=ChaoxingContentHandlerConfig(
            poll_interval_seconds=1.0,
            navigation_timeout_seconds=2.0,
        ),
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )


def test_content_clicks_next_card_and_returns_after_verified_transition() -> None:
    browser = ScriptedContentBrowser(
        [_state(active_index=0, has_next=True), _state(active_index=1, has_next=False)]
    )
    clock = FakeClock()

    _handler(browser, clock).run()

    assert browser.action_calls == [("click", "#prev_tab li.active + li")]


def test_missing_next_card_does_not_forge_navigation_success() -> None:
    browser = ScriptedContentBrowser([_state(active_index=0, has_next=False)])
    clock = FakeClock()

    with pytest.raises(ContentNavigationError, match="cross-chapter navigation is not evidenced"):
        _handler(browser, clock).run()

    assert browser.action_calls == []


def test_new_pending_module_prevents_content_from_skipping_work() -> None:
    browser = ScriptedContentBrowser(
        [
            _state(
                active_index=0,
                has_next=True,
                modules=[
                    {
                        "module_url": "/ananas/modules/video/index.html",
                        "has_job_icon": True,
                        "finished": False,
                    }
                ],
            )
        ]
    )
    clock = FakeClock()

    with pytest.raises(ContentNavigationError, match="pending Chaoxing module appeared"):
        _handler(browser, clock).run()

    assert browser.action_calls == []


def test_unchanged_active_card_fails_at_navigation_deadline() -> None:
    browser = ScriptedContentBrowser([_state(active_index=0, has_next=True)])
    clock = FakeClock()

    with pytest.raises(ContentNavigationError, match="did not change"):
        _handler(browser, clock).run()

    assert browser.action_calls == [("click", "#prev_tab li.active + li")]


def test_handler_implements_platform_neutral_application_contract() -> None:
    handler = _handler(ScriptedContentBrowser([_state(active_index=0, has_next=True)]), FakeClock())

    assert isinstance(handler, TaskHandler)
