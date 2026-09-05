"""Unit tests for deterministic Chaoxing task detection."""

from typing import Any

import pytest

from linkforge.application.task_runner import TaskDetector, TaskType
from linkforge.browser.exceptions import BrowserError
from linkforge.platforms.chaoxing.task_detector import ChaoxingTaskDetector
from tests.fakes import FakeBrowser

_PAGE_URL = "https://mooc1.chaoxing.com/mycourse/studentstudy"
_CONTENT_URL = "https://mooc1.chaoxing.com/mooc-ans/knowledge/cards?num=1"


def _module(
    module_path: str | None,
    *,
    has_job_icon: bool = False,
    finished: bool = False,
) -> dict[str, Any]:
    return {
        "module_url": module_path,
        "has_job_icon": has_job_icon,
        "finished": finished,
    }


def _browser_with_modules(*modules: dict[str, Any]) -> FakeBrowser:
    return FakeBrowser(
        frame_evaluation_results=(
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
        )
    )


@pytest.mark.parametrize(
    ("module", "expected"),
    [
        (_module("/ananas/modules/video/index.html", has_job_icon=True), TaskType.VIDEO),
        (_module("/ananas/modules/pdf/index.html"), TaskType.DOCUMENT),
        (_module("/ananas/modules/work/index.html"), TaskType.QUIZ),
        (_module("/ananas/modules/insertbbs/index.html"), TaskType.COMMENT),
    ],
)
def test_pending_module_maps_to_task_type(module: dict[str, Any], expected: TaskType) -> None:
    browser = _browser_with_modules(module)
    detector = ChaoxingTaskDetector(browser)

    assert detector.detect() is expected
    assert len(browser.frame_evaluation_calls) == 1
    inspection_script = browser.frame_evaluation_calls[0]
    assert "#prev_tab li.active" in inspection_script
    assert "/mooc-ans/knowledge/cards" in inspection_script
    assert 'iframe[src*="/ananas/modules/"]' in inspection_script
    assert '.closest(".ans-attach-ct")' in inspection_script
    assert ".card.active" not in inspection_script


def test_content_frame_without_modules_is_content() -> None:
    assert ChaoxingTaskDetector(_browser_with_modules()).detect() is TaskType.CONTENT


def test_all_finished_job_modules_are_content() -> None:
    browser = _browser_with_modules(
        _module("/ananas/modules/video/index.html", has_job_icon=True, finished=True),
        _module("/ananas/modules/pdf/index.html", has_job_icon=True, finished=True),
        _module("/ananas/modules/insertbbs/index.html", has_job_icon=True, finished=True),
    )

    assert ChaoxingTaskDetector(browser).detect() is TaskType.CONTENT


def test_finished_job_video_is_skipped_for_unfinished_document() -> None:
    browser = _browser_with_modules(
        _module("/ananas/modules/video/index.html", has_job_icon=True, finished=True),
        _module("/ananas/modules/pdf/index.html"),
    )

    assert ChaoxingTaskDetector(browser).detect() is TaskType.DOCUMENT


def test_non_job_module_is_not_skipped() -> None:
    browser = _browser_with_modules(
        _module("/ananas/modules/work/index.html", has_job_icon=False, finished=True),
    )

    assert ChaoxingTaskDetector(browser).detect() is TaskType.QUIZ


def test_first_pending_module_wins_when_content_frame_has_multiple_modules() -> None:
    browser = _browser_with_modules(
        _module("/ananas/modules/insertbbs/index.html"),
        _module("/ananas/modules/video/index.html", has_job_icon=True),
        _module("/ananas/modules/work/index.html"),
    )

    assert ChaoxingTaskDetector(browser).detect() is TaskType.COMMENT


def test_unknown_first_pending_module_is_not_skipped() -> None:
    browser = _browser_with_modules(
        _module("/ananas/modules/audio/index.html"),
        _module("/ananas/modules/video/index.html", has_job_icon=True),
    )

    assert ChaoxingTaskDetector(browser).detect() is TaskType.UNKNOWN


@pytest.mark.parametrize(
    "frame_results",
    [
        (),
        ({"frame_url": _PAGE_URL, "active_tab_count": 0, "modules": []},),
        ({"frame_url": _PAGE_URL, "active_tab_count": 2, "modules": []},),
        ({"frame_url": _PAGE_URL, "active_tab_count": 1, "modules": []},),
        (
            {"frame_url": _PAGE_URL, "active_tab_count": 1, "modules": []},
            {"frame_url": _CONTENT_URL, "active_tab_count": 0, "modules": []},
            {"frame_url": f"{_CONTENT_URL}&num=2", "active_tab_count": 0, "modules": []},
        ),
        ({"frame_url": None, "active_tab_count": 1, "modules": []},),
        (
            {"frame_url": _PAGE_URL, "active_tab_count": 1, "modules": []},
            {"frame_url": _CONTENT_URL, "active_tab_count": 0, "modules": "invalid"},
        ),
        (
            {"frame_url": _PAGE_URL, "active_tab_count": 1, "modules": []},
            {
                "frame_url": _CONTENT_URL,
                "active_tab_count": 0,
                "modules": [_module(None)],
            },
        ),
    ],
)
def test_malformed_or_ambiguous_current_state_is_unknown(
    frame_results: tuple[object, ...],
) -> None:
    browser = FakeBrowser(frame_evaluation_results=frame_results)

    assert ChaoxingTaskDetector(browser).detect() is TaskType.UNKNOWN


def test_browser_inspection_failure_is_unknown() -> None:
    browser = FakeBrowser(observation_error=BrowserError("inspection failed"))

    assert ChaoxingTaskDetector(browser).detect() is TaskType.UNKNOWN


def test_detector_implements_application_contract_without_llm() -> None:
    detector = ChaoxingTaskDetector(_browser_with_modules())

    assert isinstance(detector, TaskDetector)
