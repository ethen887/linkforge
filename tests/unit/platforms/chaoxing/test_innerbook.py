"""Fail-closed tests for actual innerbook scrolling and run-scoped completion."""

from dataclasses import replace

import pytest

from linkforge.application.task_runner import TaskType
from linkforge.platforms.chaoxing.document_handler import ChaoxingDocumentTaskHandler
from linkforge.platforms.chaoxing.exceptions import (
    ChaoxingDocumentProgressTimeoutError,
    ChaoxingDocumentStateError,
    ChaoxingDocumentTimeoutError,
    ChaoxingDocumentViewerReadyTimeoutError,
)
from linkforge.platforms.chaoxing.innerbook import InnerbookSession, InnerbookTarget, InnerbookViewer
from linkforge.platforms.chaoxing.innerbook_handler import ChaoxingInnerbookReader
from linkforge.platforms.chaoxing.task_detector import ChaoxingTaskDetector
from tests.fakes import ManualClock, ScriptedInnerbookBrowser

_CARD = "https://example.test/mooc-ans/knowledge/cards?num=1"
_BOOK = "/ananas/modules/innerbook/index.html"
_READER = "https://example.test/n/readsvr/book/mooc/1/2/3.shtml"
_TARGET = InnerbookTarget(_CARD, 0, _BOOK, (0, 0))


def _snapshot(
    y: float = 0,
    *,
    ready: bool = True,
    missing: bool = False,
    job: bool = False,
    finished: bool = False,
    reader_url: str = _READER,
    card_url: str = _CARD,
    reader_path: list[int] | None = None,
) -> tuple[tuple[object, ...], tuple[object, ...]]:
    card = (
        {"frame_url": "https://example.test/study", "active_tab_count": 1, "modules": []},
        {
            "frame_url": card_url,
            "active_tab_count": 0,
            "modules": [
                {
                    "module_url": _BOOK,
                    "frame_path": [0, 0],
                    "has_job_icon": job,
                    "finished": finished,
                }
            ],
        },
    )
    readers = (
        {
            "innerbook_viewer": None
            if missing
            else {
                "url": reader_url,
                "frame_path": reader_path or [0, 0, 0],
                "scroll_y": y,
                "height": 400,
                "scroll_height": 1000,
                "page_count": 2,
                "visible_pages_ready": ready,
            }
        },
    )
    return card, readers


def _reader(browser: ScriptedInnerbookBrowser, session: InnerbookSession, clock: ManualClock, **options):
    return ChaoxingInnerbookReader(
        browser,
        session,
        ready_timeout_seconds=0.5,
        progress_timeout_seconds=0.5,
        timeout_seconds=2,
        poll_interval_seconds=0.25,
        clock=clock,
        sleeper=clock.sleep,
        **options,
    )


def test_known_innerbook_is_document_before_reading_even_at_bottom() -> None:
    browser = ScriptedInnerbookBrowser([_snapshot(600)])
    assert ChaoxingTaskDetector(browser).detect() is TaskType.DOCUMENT


def test_default_reader_allows_continuous_progress_beyond_former_total_deadline() -> None:
    browser = ScriptedInnerbookBrowser([_snapshot(y) for y in range(601)])
    clock = ManualClock()
    ChaoxingInnerbookReader(
        browser,
        InnerbookSession(),
        poll_interval_seconds=2,
        clock=clock,
        sleeper=clock.sleep,
    ).read(_TARGET)
    assert clock.now > 900


def test_document_handler_scrolls_book_then_detector_reveals_content() -> None:
    session = InnerbookSession()
    browser = ScriptedInnerbookBrowser([_snapshot(), _snapshot(), _snapshot(300), _snapshot(600)])
    clock = ManualClock()
    detector = ChaoxingTaskDetector(browser, innerbook_session=session)
    handler = ChaoxingDocumentTaskHandler(
        browser, innerbook_session=session, clock=clock, sleeper=clock.sleep
    )

    assert detector.detect() is TaskType.DOCUMENT
    handler.run()

    assert detector.detect() is TaskType.CONTENT
    assert any("top: 300" in action for action in browser.actions)


@pytest.mark.parametrize("missing", [False, True])
def test_missing_or_unloaded_reader_times_out_without_completion(missing: bool) -> None:
    browser = ScriptedInnerbookBrowser([_snapshot(600, ready=False, missing=missing)])
    session = InnerbookSession()
    clock = ManualClock()
    with pytest.raises(ChaoxingDocumentViewerReadyTimeoutError):
        _reader(browser, session, clock).read(_TARGET)
    assert clock.now == 0.5
    assert not any("top: 300" in action for action in browser.actions)
    assert ChaoxingTaskDetector(browser, innerbook_session=session).detect() is TaskType.DOCUMENT


def test_reader_waits_for_page_load_before_scrolling_and_recovers() -> None:
    browser = ScriptedInnerbookBrowser([_snapshot(ready=False), _snapshot(), _snapshot(600)])
    clock = ManualClock()
    _reader(browser, InnerbookSession(), clock).read(_TARGET)
    assert sum("top: 300" in action for action in browser.actions) == 1
    assert clock.now == 0.5


def test_stalled_scroll_is_bounded() -> None:
    browser = ScriptedInnerbookBrowser([_snapshot()])
    clock = ManualClock()
    with pytest.raises(ChaoxingDocumentProgressTimeoutError):
        _reader(browser, InnerbookSession(), clock).read(_TARGET)
    assert clock.now == 0.5


def test_task_point_book_at_bottom_requires_platform_marker() -> None:
    session = InnerbookSession()
    browser = ScriptedInnerbookBrowser([_snapshot(600, job=True)])
    clock = ManualClock()
    with pytest.raises(ChaoxingDocumentViewerReadyTimeoutError, match="platform completion"):
        _reader(browser, session, clock).read(_TARGET)
    assert ChaoxingTaskDetector(browser, innerbook_session=session).detect() is TaskType.DOCUMENT


def test_dynamic_task_marker_cannot_be_downgraded_to_ordinary_completion() -> None:
    browser = ScriptedInnerbookBrowser([_snapshot(job=True), _snapshot(600, job=False)])
    with pytest.raises(ChaoxingDocumentViewerReadyTimeoutError):
        _reader(browser, InnerbookSession(), ManualClock()).read(_TARGET)


def test_book_returns_only_after_observing_platform_finished() -> None:
    browser = ScriptedInnerbookBrowser([_snapshot(600, job=True), _snapshot(600, job=True, finished=True)])
    clock = ManualClock()
    _reader(browser, InnerbookSession(), clock).read(_TARGET)
    assert clock.now == 0.25


@pytest.mark.parametrize("change", ["card", "reader"])
def test_identity_change_is_fail_closed(change: str) -> None:
    changed = (
        _snapshot(600, card_url=_CARD + "&num=2")
        if change == "card"
        else _snapshot(600, reader_url=_READER + "?new=1")
    )
    browser = ScriptedInnerbookBrowser([_snapshot(), changed])
    with pytest.raises(ChaoxingDocumentStateError, match="changed"):
        _reader(browser, InnerbookSession(), ManualClock()).read(_TARGET)


def test_overall_deadline_remains_bounded_during_progress() -> None:
    snapshots = [_snapshot(float(y)) for y in range(0, 600, 20)]
    browser = ScriptedInnerbookBrowser(snapshots)
    clock = ManualClock()
    with pytest.raises(ChaoxingDocumentTimeoutError):
        _reader(browser, InnerbookSession(), clock).read(_TARGET)
    assert clock.now == 2


def test_session_isolated_by_card_module_index_and_reader_identity() -> None:
    viewer = InnerbookViewer(_READER, (0, 0, 0), 600, 400, 1000, 2, True)
    session = InnerbookSession()
    session.mark_handled(_CARD, 0, _BOOK, viewer)
    assert session.is_handled(_CARD, 0, _BOOK, viewer)
    assert not session.is_handled(_CARD, 1, _BOOK, viewer)
    assert not session.is_handled(_CARD + "&num=2", 0, _BOOK, viewer)
    assert not session.is_handled(_CARD, 0, _BOOK, replace(viewer, url=_READER + "?new=1"))
    assert not InnerbookSession().is_handled(_CARD, 0, _BOOK, viewer)
    with pytest.raises(ValueError):
        session.mark_handled(_CARD, 0, _BOOK, replace(viewer, visible_pages_ready=False))


def test_unrelated_reader_frame_is_not_used_for_completion() -> None:
    browser = ScriptedInnerbookBrowser([_snapshot(600, reader_path=[0, 1, 0])])
    with pytest.raises(ChaoxingDocumentViewerReadyTimeoutError):
        _reader(browser, InnerbookSession(), ManualClock()).read(_TARGET)


def test_malformed_reader_is_unknown_with_safe_diagnostic(caplog) -> None:
    card, readers = _snapshot(600)
    readers[0]["innerbook_viewer"]["height"] = "PRIVATE"
    browser = ScriptedInnerbookBrowser([(card, readers)])
    caplog.set_level("DEBUG")
    assert ChaoxingTaskDetector(browser).detect() is TaskType.UNKNOWN
    assert "reason=malformed_state stage=innerbook_inspection" in caplog.text
    assert "PRIVATE" not in caplog.text
