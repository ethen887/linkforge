"""Unit tests for the deterministic Chaoxing video lifecycle."""

from typing import Any

import pytest

from linkforge.application.task_runner import TaskHandler, TaskType
from linkforge.browser.exceptions import BrowserError
from linkforge.platforms.chaoxing.dom import inspect_chaoxing_page
from linkforge.platforms.chaoxing.exceptions import (
    VideoPlaybackError,
    VideoTaskError,
    VideoTimeoutError,
)
from linkforge.platforms.chaoxing.task_detector import ChaoxingTaskDetector
from linkforge.platforms.chaoxing.video_handler import (
    ChaoxingVideoHandlerConfig,
    ChaoxingVideoTaskHandler,
)
from linkforge.platforms.chaoxing.video_state import VideoSession
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


def test_ordinary_video_plays_and_is_skipped_on_subsequent_detection() -> None:
    ended = _page_state(
        _module(has_job_icon=False), video=_video(ended=True, paused=True, current_time=10.0)
    )
    browser = ScriptedFrameBrowser(
        [
            _page_state(_module(has_job_icon=False), video=_video(paused=True)),
            _page_state(_module(has_job_icon=False), video=_video(paused=True)),
            ended,
        ]
    )
    clock = FakeClock()
    session = VideoSession()
    handler = ChaoxingVideoTaskHandler(
        browser,
        video_session=session,
        config=ChaoxingVideoHandlerConfig(video_available_timeout_seconds=3.0),
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )
    detector = ChaoxingTaskDetector(browser, video_session=session)

    handler.run()

    assert clock.now == 3.0
    assert detector.detect() is TaskType.CONTENT
    assert sum("const playRequest = video.play()" in call for call in browser.frame_evaluation_calls) == 1
    # Even replacement of the player after completion must not restart the ordinary video.
    browser._states = [_page_state(_module(has_job_icon=False), video=_video(paused=True))]
    browser._state_index = 0
    assert detector.detect() is TaskType.CONTENT
    handler.run()
    assert sum("const playRequest = video.play()" in call for call in browser.frame_evaluation_calls) == 1


def test_late_task_marker_requires_platform_completion_even_when_media_ended() -> None:
    no_marker = _page_state(_module(has_job_icon=False), video=_video(ended=True, current_time=10.0))
    marker = _page_state(_module(), video=_video(ended=True, current_time=10.0))
    browser = ScriptedFrameBrowser([no_marker, no_marker, marker])
    clock = FakeClock()

    with pytest.raises(VideoTimeoutError, match="media ended"):
        _handler(browser, clock).run()


def test_task_marker_disappearance_does_not_turn_task_point_into_ordinary_video() -> None:
    browser = ScriptedFrameBrowser(
        [
            _page_state(_module(), video=_video(current_time=1.0)),
            _page_state(_module(has_job_icon=False), video=_video(ended=True, current_time=10.0)),
        ]
    )

    with pytest.raises(VideoTimeoutError, match="media ended"):
        _handler(browser, FakeClock()).run()


def test_missing_ordinary_video_does_not_count_as_completed() -> None:
    browser = ScriptedFrameBrowser([_page_state(_module(has_job_icon=False))])

    with pytest.raises(VideoTimeoutError, match="did not become available"):
        _handler(browser, FakeClock()).run()


def test_ordinary_video_without_progress_still_times_out() -> None:
    browser = ScriptedFrameBrowser(
        [_page_state(_module(has_job_icon=False), video=_video(current_time=1.0))]
    )

    with pytest.raises(VideoTimeoutError, match="no playback progress"):
        _handler(browser, FakeClock()).run()


def test_handled_ordinary_video_does_not_hide_later_videos_or_new_task_marker() -> None:
    browser = ScriptedFrameBrowser([])
    session = VideoSession()
    browser._states = [_page_state(_module(has_job_icon=False))]
    session.mark_handled(inspect_chaoxing_page(browser), 0)
    detector = ChaoxingTaskDetector(browser, video_session=session)
    browser._states = [_page_state(_module(has_job_icon=False), _module(_OTHER_VIDEO_URL))]
    assert detector.detect() is TaskType.VIDEO
    browser._states = [_page_state(_module())]
    assert detector.detect() is TaskType.VIDEO


def test_ordinary_video_completion_is_scoped_to_card() -> None:
    browser = ScriptedFrameBrowser([_page_state(_module(has_job_icon=False))])
    session = VideoSession()
    session.mark_handled(inspect_chaoxing_page(browser), 0)
    other_card = _page_state(_module(has_job_icon=False))
    assert isinstance(other_card[1], dict)
    other_card[1]["frame_url"] = _CONTENT_URL + "&knowledgeid=other"
    browser._states = [other_card]

    assert ChaoxingTaskDetector(browser, video_session=session).detect() is TaskType.VIDEO


def _duplicate_video_state(*, first_finished: bool, second_finished: bool) -> tuple[object, ...]:
    first = _module(finished=first_finished)
    first["frame_path"] = [0, 0]
    second = _module(finished=second_finished)
    second["frame_path"] = [0, 1]
    frames = _page_state(first, second, video=_video(ended=True, current_time=10.0))
    assert isinstance(frames[-1], dict)
    frames[-1]["frame_path"] = [0, 0]
    second_frame = dict(frames[-1])
    second_frame["frame_path"] = [0, 1]
    second_frame["video"] = _video(ended=True, current_time=10.0)
    return (*frames, second_frame)


def test_same_url_finished_sibling_cannot_complete_pending_task_point() -> None:
    browser = ScriptedFrameBrowser([_duplicate_video_state(first_finished=True, second_finished=False)])

    with pytest.raises(VideoTimeoutError, match="media ended"):
        _handler(browser, FakeClock()).run()


def test_same_url_task_point_completes_only_after_its_own_marker() -> None:
    browser = ScriptedFrameBrowser(
        [
            _duplicate_video_state(first_finished=True, second_finished=False),
            _duplicate_video_state(first_finished=True, second_finished=False),
            _duplicate_video_state(first_finished=True, second_finished=True),
        ]
    )
    clock = FakeClock()

    _handler(browser, clock).run()

    assert clock.sleep_calls == [1.0]


def test_same_url_modules_without_frame_identity_still_fail_closed() -> None:
    browser = ScriptedFrameBrowser([_page_state(_module(), _module())])

    with pytest.raises(VideoTaskError, match="module is ambiguous"):
        _handler(browser, FakeClock()).run()


@pytest.mark.parametrize("frame_path", [[True], [-1], [1.5], "0/1"])
def test_invalid_frame_path_is_rejected(frame_path: object) -> None:
    module = _module()
    module["frame_path"] = frame_path
    browser = ScriptedFrameBrowser([_page_state(module)])

    with pytest.raises(VideoTaskError, match="Unable to inspect"):
        _handler(browser, FakeClock()).run()
