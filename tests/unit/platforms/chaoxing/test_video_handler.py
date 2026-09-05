"""Unit tests for the deterministic Chaoxing video lifecycle."""

from typing import Any

import pytest

from linkforge.application.task_runner import TaskHandler
from linkforge.browser.exceptions import BrowserError
from linkforge.platforms.chaoxing.exceptions import (
    VideoPlaybackError,
    VideoTaskError,
    VideoTimeoutError,
)
from linkforge.platforms.chaoxing.video_handler import (
    ChaoxingVideoHandlerConfig,
    ChaoxingVideoTaskHandler,
)
from tests.fakes import FakeBrowser

_PAGE_URL = "https://mooc1.chaoxing.com/mycourse/studentstudy"
_CONTENT_URL = "https://mooc1.chaoxing.com/mooc-ans/knowledge/cards?num=1"
_VIDEO_URL = "https://mooc1.chaoxing.com/ananas/modules/video/index.html?objectid=one"
_OTHER_VIDEO_URL = "https://mooc1.chaoxing.com/ananas/modules/video/index.html?objectid=done"


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleep_calls: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleep_calls.append(seconds)
        self.now += seconds


class ScriptedFrameBrowser(FakeBrowser):
    """Return separate state and playback results for frame expressions."""

    def __init__(
        self,
        states: list[tuple[object, ...]],
        *,
        play_results: tuple[object, ...] | None = None,
        observation_error: BrowserError | None = None,
    ) -> None:
        super().__init__(observation_error=observation_error)
        self._states = states
        self._state_index = 0
        self.play_results = play_results or (
            {
                "frame_url": _VIDEO_URL,
                "matched": True,
                "video_count": 1,
                "paused": False,
                "ended": False,
                "error": None,
            },
        )

    def evaluate_in_frames(self, expression: str) -> tuple[object, ...]:
        self._raise_observation_error()
        self.frame_evaluation_calls.append(expression)
        if "const playRequest = video.play()" in expression:
            return self.play_results
        if not self._states:
            raise AssertionError("No scripted frame state exists.")
        index = min(self._state_index, len(self._states) - 1)
        self._state_index += 1
        return self._states[index]


def _module(
    url: str = _VIDEO_URL,
    *,
    has_job_icon: bool = True,
    finished: bool = False,
) -> dict[str, object]:
    return {
        "module_url": url,
        "has_job_icon": has_job_icon,
        "finished": finished,
    }


def _page_state(
    *modules: dict[str, object],
    video: dict[str, object] | None = None,
    video_url: str = _VIDEO_URL,
) -> tuple[object, ...]:
    frames: list[object] = [
        {
            "frame_url": _PAGE_URL,
            "active_tab_count": 1,
            "active_tab_index": 0,
            "has_next_tab": True,
            "modules": [],
            "video_count": 0,
            "video": None,
        },
        {
            "frame_url": _CONTENT_URL,
            "active_tab_count": 0,
            "active_tab_index": None,
            "has_next_tab": False,
            "modules": list(modules),
            "video_count": 0,
            "video": None,
        },
    ]
    if video is not None:
        frames.append(
            {
                "frame_url": video_url,
                "active_tab_count": 0,
                "active_tab_index": None,
                "has_next_tab": False,
                "modules": [],
                "video_count": 1,
                "video": video,
            }
        )
    return tuple(frames)


def _video(
    *,
    paused: bool = False,
    ended: bool = False,
    current_time: float = 0.0,
    duration: float | None = 10.0,
) -> dict[str, object]:
    return {
        "paused": paused,
        "ended": ended,
        "current_time": current_time,
        "duration": duration,
        "ready_state": 4,
    }


def _handler(
    browser: FakeBrowser,
    clock: FakeClock,
    **config_overrides: Any,
) -> ChaoxingVideoTaskHandler:
    values = {
        "poll_interval_seconds": 1.0,
        "overall_timeout_seconds": 20.0,
        "video_available_timeout_seconds": 3.0,
        "playback_start_timeout_seconds": 2.0,
        "progress_timeout_seconds": 3.0,
        "platform_finished_timeout_seconds": 2.0,
    }
    values.update(config_overrides)
    return ChaoxingVideoTaskHandler(
        browser,
        config=ChaoxingVideoHandlerConfig(**values),
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )


def test_paused_pending_video_is_played_then_platform_completion_returns() -> None:
    states = [
        _page_state(_module(), video=_video(paused=True)),
        _page_state(_module(), video=_video(paused=True)),
        _page_state(_module(), video=_video(current_time=1.0)),
        _page_state(_module(finished=True), video=_video(ended=True, current_time=10.0)),
    ]
    browser = ScriptedFrameBrowser(states)
    clock = FakeClock()

    _handler(browser, clock).run()

    play_calls = [
        call for call in browser.frame_evaluation_calls if "const playRequest = video.play()" in call
    ]
    assert len(play_calls) == 1


def test_already_playing_video_is_not_reinitialized() -> None:
    browser = ScriptedFrameBrowser(
        [
            _page_state(_module(), video=_video(current_time=1.0)),
            _page_state(_module(), video=_video(current_time=1.0)),
            _page_state(_module(finished=True), video=_video(ended=True, current_time=10.0)),
        ]
    )
    clock = FakeClock()

    _handler(browser, clock).run()

    assert all("const playRequest = video.play()" not in call for call in browser.frame_evaluation_calls)


def test_finished_video_race_returns_idempotently_without_playback() -> None:
    browser = ScriptedFrameBrowser([_page_state(_module(finished=True))])
    clock = FakeClock()

    _handler(browser, clock).run()

    assert len(browser.frame_evaluation_calls) == 1


def test_first_pending_video_is_selected_after_a_finished_video() -> None:
    browser = ScriptedFrameBrowser(
        [
            _page_state(
                _module(_OTHER_VIDEO_URL, finished=True),
                _module(),
                video=_video(paused=True),
            ),
            _page_state(
                _module(_OTHER_VIDEO_URL, finished=True),
                _module(),
                video=_video(paused=True),
            ),
            _page_state(
                _module(_OTHER_VIDEO_URL, finished=True),
                _module(finished=True),
            ),
        ]
    )
    clock = FakeClock()

    _handler(browser, clock).run()

    play_call = next(
        call for call in browser.frame_evaluation_calls if "const playRequest = video.play()" in call
    )
    assert _VIDEO_URL in play_call
    assert _OTHER_VIDEO_URL not in play_call


def test_media_ended_waits_for_platform_finished_marker() -> None:
    browser = ScriptedFrameBrowser(
        [
            _page_state(_module(), video=_video(ended=True, paused=True, current_time=10.0)),
            _page_state(_module(), video=_video(ended=True, paused=True, current_time=10.0)),
            _page_state(_module(finished=True)),
        ]
    )
    clock = FakeClock()

    _handler(browser, clock).run()

    assert clock.sleep_calls == [1.0]


def test_media_ended_without_platform_finished_times_out() -> None:
    ended_state = _page_state(
        _module(),
        video=_video(ended=True, paused=True, current_time=10.0),
    )
    browser = ScriptedFrameBrowser([ended_state])
    clock = FakeClock()

    with pytest.raises(VideoTimeoutError, match="media ended"):
        _handler(browser, clock).run()


def test_video_without_progress_fails_at_stuck_deadline() -> None:
    playing_state = _page_state(_module(), video=_video(current_time=1.0))
    browser = ScriptedFrameBrowser([playing_state])
    clock = FakeClock()

    with pytest.raises(VideoTimeoutError, match="no playback progress"):
        _handler(browser, clock, progress_timeout_seconds=2.0).run()


def test_video_frame_can_be_reacquired_after_dynamic_replacement() -> None:
    browser = ScriptedFrameBrowser(
        [
            _page_state(_module()),
            _page_state(_module()),
            _page_state(_module(), video=_video(current_time=1.0)),
            _page_state(_module(finished=True)),
        ]
    )
    clock = FakeClock()

    _handler(browser, clock).run()

    assert len(browser.frame_evaluation_calls) == 4


def test_browser_inspection_error_is_converted_to_video_task_error() -> None:
    browser = ScriptedFrameBrowser([], observation_error=BrowserError("frame failure"))
    clock = FakeClock()

    with pytest.raises(VideoTaskError, match="Unable to inspect") as exc_info:
        _handler(browser, clock).run()

    assert isinstance(exc_info.value.__cause__, Exception)


def test_browser_playback_error_is_converted_to_video_playback_error() -> None:
    paused_state = _page_state(_module(), video=_video(paused=True))
    browser = ScriptedFrameBrowser(
        [paused_state],
        play_results=(
            {
                "frame_url": _VIDEO_URL,
                "matched": True,
                "video_count": 1,
                "paused": True,
                "ended": False,
                "error": "NotAllowedError: user activation is required",
            },
        ),
    )
    clock = FakeClock()

    with pytest.raises(VideoPlaybackError, match="NotAllowedError"):
        _handler(browser, clock).run()


def test_video_that_remains_paused_fails_at_playback_start_deadline() -> None:
    paused_state = _page_state(_module(), video=_video(paused=True))
    browser = ScriptedFrameBrowser([paused_state])
    clock = FakeClock()

    with pytest.raises(VideoPlaybackError, match="remained paused"):
        _handler(browser, clock, playback_start_timeout_seconds=2.0).run()


def test_handler_implements_platform_neutral_application_contract() -> None:
    handler = _handler(ScriptedFrameBrowser([]), FakeClock())

    assert isinstance(handler, TaskHandler)
