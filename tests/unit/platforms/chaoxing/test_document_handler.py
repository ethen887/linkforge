"""Unit tests for the deterministic Chaoxing document workflow."""

from __future__ import annotations

from collections.abc import Iterable

import pytest

from linkforge.browser.exceptions import BrowserError
from linkforge.platforms.chaoxing.document_handler import ChaoxingDocumentTaskHandler
from linkforge.platforms.chaoxing.exceptions import (
    ChaoxingDocumentInspectionError,
    ChaoxingDocumentNotFoundError,
    ChaoxingDocumentProgressTimeoutError,
    ChaoxingDocumentStateError,
    ChaoxingDocumentTimeoutError,
    ChaoxingDocumentViewerReadyTimeoutError,
)
from tests.fakes import FakeBrowser

_PAGE_URL = "https://mooc1.chaoxing.com/mycourse/studentstudy"
_CONTENT_URL = "https://mooc1.chaoxing.com/mooc-ans/knowledge/cards?num=1"
_PDF_URL = "/ananas/modules/pdf/index.html"


def _module(
    object_id: str = "pdf-a",
    *,
    declared_page_count: int = 2,
    has_job_icon: bool = False,
    finished: bool = False,
) -> dict[str, object]:
    return {
        "module_url": _PDF_URL,
        "object_id": object_id,
        "declared_page_count": declared_page_count,
        "has_job_icon": has_job_icon,
        "finished": finished,
    }


def _viewer(
    object_id: str = "pdf-a",
    *,
    scroll_y: float,
    page_count: int = 2,
    inner_height: float = 546,
    scroll_height: float = 1_230,
) -> dict[str, object]:
    return {
        "object_id": object_id,
        "page_count": page_count,
        "visible_pages": [1],
        "scroll_y": scroll_y,
        "inner_height": inner_height,
        "scroll_height": scroll_height,
        "bottom_distance": scroll_height - (scroll_y + inner_height),
        "at_bottom": scroll_height - (scroll_y + inner_height) <= 8,
    }


def _frames(
    *modules: object,
    viewers: tuple[dict[str, object], ...] = (),
    active: bool = True,
) -> tuple[object, ...]:
    viewer_frames = tuple(
        {
            "frame_url": f"https://pan-yz.chaoxing.com/screen/v2/file_{viewer['object_id']}",
            "active_tab_count": 0,
            "modules": [],
            "viewer": viewer,
        }
        for viewer in viewers
    )
    return (
        {"frame_url": _PAGE_URL, "active_tab_count": int(active), "modules": []},
        {"frame_url": _CONTENT_URL, "active_tab_count": 0, "modules": list(modules)},
        *viewer_frames,
    )


class SequenceBrowser(FakeBrowser):
    """Return scripted inspections while recording scroll expressions separately."""

    def __init__(self, snapshots: Iterable[tuple[object, ...]]) -> None:
        super().__init__()
        self._snapshots = list(snapshots)
        self._snapshot_index = 0
        self.scroll_scripts: list[str] = []

    def evaluate_in_frames(self, expression: str) -> tuple[object, ...]:
        self.frame_evaluation_calls.append(expression)
        if "window.scrollBy" in expression:
            self.scroll_scripts.append(expression)
            return ({"matched": True},)

        index = min(self._snapshot_index, len(self._snapshots) - 1)
        self._snapshot_index += 1
        return self._snapshots[index]


class FakeClock:
    """Advance deterministic time only when the handler sleeps."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def _handler(
    browser: FakeBrowser,
    clock: FakeClock,
    *,
    ready_timeout: float = 1.0,
    timeout: float = 5.0,
    progress_timeout: float = 1.0,
    poll_interval: float = 0.25,
) -> ChaoxingDocumentTaskHandler:
    return ChaoxingDocumentTaskHandler(
        browser,
        viewer_ready_timeout_seconds=ready_timeout,
        timeout_seconds=timeout,
        progress_timeout_seconds=progress_timeout,
        poll_interval_seconds=poll_interval,
        clock=clock,
        sleeper=clock.sleep,
    )


def test_handler_scrolls_from_top_in_steps_until_real_bottom() -> None:
    browser = SequenceBrowser(
        [
            _frames(_module(), viewers=(_viewer(scroll_y=0),)),
            _frames(_module(), viewers=(_viewer(scroll_y=410),)),
            _frames(_module(), viewers=(_viewer(scroll_y=684),)),
        ]
    )
    clock = FakeClock()

    _handler(browser, clock).run()

    assert len(browser.scroll_scripts) == 2
    assert all('const targetObjectId = "pdf-a"' in script for script in browser.scroll_scripts)
    assert all("window.scrollBy" in script for script in browser.scroll_scripts)
    assert all("scrollTo" not in script for script in browser.scroll_scripts)


def test_handler_continues_from_partial_progress_without_resetting_to_zero() -> None:
    browser = SequenceBrowser(
        [
            _frames(
                _module(declared_page_count=13),
                viewers=(_viewer(scroll_y=3_000, page_count=13, scroll_height=6_334),),
            ),
            _frames(
                _module(declared_page_count=13),
                viewers=(_viewer(scroll_y=3_410, page_count=13, scroll_height=6_334),),
            ),
            _frames(
                _module(declared_page_count=13),
                viewers=(_viewer(scroll_y=5_788, page_count=13, scroll_height=6_334),),
            ),
        ]
    )

    _handler(browser, FakeClock()).run()

    assert len(browser.scroll_scripts) == 2
    assert "scrollTo" not in "".join(browser.scroll_scripts)


def test_handler_waits_for_missing_viewer_then_scrolls_when_ready() -> None:
    browser = SequenceBrowser(
        [
            _frames(_module()),
            _frames(_module()),
            _frames(_module(), viewers=(_viewer(scroll_y=0),)),
            _frames(_module(), viewers=(_viewer(scroll_y=684),)),
        ]
    )
    clock = FakeClock()

    _handler(browser, clock).run()

    assert len(browser.scroll_scripts) == 1
    assert clock.sleeps == [0.25, 0.25, 0.25]


def test_handler_times_out_when_viewer_never_becomes_ready() -> None:
    browser = SequenceBrowser([_frames(_module())])

    with pytest.raises(ChaoxingDocumentViewerReadyTimeoutError, match="not ready"):
        _handler(browser, FakeClock(), ready_timeout=0.5).run()


def test_handler_waits_until_viewer_mounts_all_declared_pages() -> None:
    browser = SequenceBrowser(
        [
            _frames(
                _module(declared_page_count=2),
                viewers=(_viewer(scroll_y=0, page_count=1),),
            ),
            _frames(
                _module(declared_page_count=2),
                viewers=(_viewer(scroll_y=0, page_count=2),),
            ),
            _frames(
                _module(declared_page_count=2),
                viewers=(_viewer(scroll_y=684, page_count=2),),
            ),
        ]
    )

    _handler(browser, FakeClock()).run()

    assert len(browser.scroll_scripts) == 1


def test_handler_raises_progress_timeout_when_scroll_y_never_changes() -> None:
    browser = SequenceBrowser([_frames(_module(), viewers=(_viewer(scroll_y=0),))])
    clock = FakeClock()

    with pytest.raises(ChaoxingDocumentProgressTimeoutError, match="remained at scroll_y=0"):
        _handler(browser, clock, progress_timeout=0.5).run()

    assert len(browser.scroll_scripts) == 2


def test_handler_recovers_after_viewer_frame_replacement() -> None:
    browser = SequenceBrowser(
        [
            _frames(_module(), viewers=(_viewer(scroll_y=0),)),
            _frames(_module()),
            ({"frame_url": _PAGE_URL, "active_tab_count": 1, "modules": []},),
            _frames(_module(), viewers=(_viewer(scroll_y=410),)),
            _frames(_module(), viewers=(_viewer(scroll_y=684),)),
        ]
    )

    _handler(browser, FakeClock()).run()

    assert len(browser.scroll_scripts) == 2


def test_handler_selects_second_pdf_when_first_is_already_at_bottom() -> None:
    browser = SequenceBrowser(
        [
            _frames(
                _module("pdf-a"),
                _module("pdf-b"),
                viewers=(_viewer("pdf-a", scroll_y=684), _viewer("pdf-b", scroll_y=0)),
            ),
            _frames(
                _module("pdf-a"),
                _module("pdf-b"),
                viewers=(_viewer("pdf-a", scroll_y=684), _viewer("pdf-b", scroll_y=684)),
            ),
        ]
    )

    _handler(browser, FakeClock()).run()

    assert len(browser.scroll_scripts) == 1
    assert 'const targetObjectId = "pdf-b"' in browser.scroll_scripts[0]


def test_handler_does_not_process_second_pdf_in_same_invocation() -> None:
    browser = SequenceBrowser(
        [
            _frames(
                _module("pdf-a"),
                _module("pdf-b"),
                viewers=(_viewer("pdf-a", scroll_y=0), _viewer("pdf-b", scroll_y=0)),
            ),
            _frames(
                _module("pdf-a"),
                _module("pdf-b"),
                viewers=(_viewer("pdf-a", scroll_y=684), _viewer("pdf-b", scroll_y=0)),
            ),
        ]
    )

    _handler(browser, FakeClock()).run()

    assert len(browser.scroll_scripts) == 1
    assert 'const targetObjectId = "pdf-a"' in browser.scroll_scripts[0]


def test_handler_rejects_missing_pending_document() -> None:
    browser = SequenceBrowser([_frames()])

    with pytest.raises(ChaoxingDocumentNotFoundError, match="No pending"):
        _handler(browser, FakeClock()).run()


def test_handler_rejects_malformed_module_state() -> None:
    malformed = {"module_url": _PDF_URL, "has_job_icon": False, "finished": False}
    browser = SequenceBrowser([_frames(malformed)])

    with pytest.raises(ChaoxingDocumentStateError, match="object_id"):
        _handler(browser, FakeClock()).run()


def test_handler_converts_browser_inspection_failure() -> None:
    browser = FakeBrowser(observation_error=BrowserError("inspection failed"))

    with pytest.raises(ChaoxingDocumentInspectionError, match="Failed to inspect"):
        _handler(browser, FakeClock()).run()


def test_handler_has_bounded_overall_timeout() -> None:
    browser = SequenceBrowser([_frames(_module())])

    with pytest.raises(ChaoxingDocumentTimeoutError, match="within 0.5 seconds"):
        _handler(browser, FakeClock(), ready_timeout=2.0, timeout=0.5).run()


def test_default_handler_allows_progressing_pdf_to_take_longer_than_sixty_seconds() -> None:
    browser = SequenceBrowser(
        _frames(_module(), viewers=(_viewer(scroll_y=y, inner_height=100, scroll_height=10000),))
        for y in range(0, 10000, 100)
    )
    clock = FakeClock()
    ChaoxingDocumentTaskHandler(
        browser,
        poll_interval_seconds=1,
        clock=clock,
        sleeper=clock.sleep,
    ).run()
    assert clock.now > 60
    assert len(browser.scroll_scripts) == 99


@pytest.mark.parametrize(
    "overrides",
    [
        {"viewer_ready_timeout_seconds": 0},
        {"timeout_seconds": 0},
        {"progress_timeout_seconds": 0},
        {"poll_interval_seconds": 0},
        {"scroll_viewport_fraction": 0},
    ],
)
def test_handler_rejects_non_positive_configuration(overrides: dict[str, float]) -> None:
    with pytest.raises(ValueError, match="must be greater than 0"):
        ChaoxingDocumentTaskHandler(FakeBrowser(), **overrides)
