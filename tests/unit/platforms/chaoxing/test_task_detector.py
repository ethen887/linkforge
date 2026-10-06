"""Unit tests for deterministic Chaoxing task detection."""

import logging
from typing import Any

import pytest

from linkforge.application.task_runner import TaskDetector, TaskType
from linkforge.browser.exceptions import BrowserError
from linkforge.platforms.chaoxing.exceptions import ChaoxingInspectionError
from linkforge.platforms.chaoxing.models import ChaoxingModuleState, ChaoxingPageState
from linkforge.platforms.chaoxing.task_detector import ChaoxingTaskDetector
from linkforge.platforms.chaoxing.video_state import VideoSession
from tests.fakes import FakeBrowser

_PAGE_URL = "https://mooc1.chaoxing.com/mycourse/studentstudy"
_CONTENT_URL = "https://mooc1.chaoxing.com/mooc-ans/knowledge/cards?num=1"


def _module(
    module_path: str | None,
    *,
    object_id: str = "pdf-a",
    declared_page_count: int | None = 2,
    has_job_icon: bool = False,
    finished: bool = False,
) -> dict[str, Any]:
    """Build one raw module state returned by the Chaoxing DOM probe."""
    module: dict[str, Any] = {
        "module_url": module_path,
        "has_job_icon": has_job_icon,
        "finished": finished,
    }

    if isinstance(module_path, str) and "/ananas/modules/pdf/" in module_path:
        module["object_id"] = object_id
        module["declared_page_count"] = declared_page_count

    return module


def _viewer(
    object_id: str,
    *,
    scroll_y: float,
    page_count: int = 2,
    inner_height: float = 546,
    scroll_height: float = 1_230,
) -> dict[str, object]:
    """Build one raw continuous-scroll PDF viewer state."""
    bottom_distance = scroll_height - (scroll_y + inner_height)

    return {
        "frame_url": (f"https://pan-yz.chaoxing.com/screen/v2/file_{object_id}"),
        "active_tab_count": 0,
        "modules": [],
        "viewer": {
            "object_id": object_id,
            "page_count": page_count,
            "visible_pages": [1],
            "scroll_y": scroll_y,
            "inner_height": inner_height,
            "scroll_height": scroll_height,
            "bottom_distance": bottom_distance,
            "at_bottom": bottom_distance <= 8,
        },
    }


def _browser_with_modules(
    *modules: dict[str, Any],
    viewers: tuple[dict[str, object], ...] = (),
) -> FakeBrowser:
    """Build a fake Chaoxing frame tree for detector tests."""
    return FakeBrowser(
        frame_evaluation_results=(
            {
                "frame_url": _PAGE_URL,
                "active_tab_count": 1,
                "modules": [],
                "viewer": None,
            },
            {
                "frame_url": _CONTENT_URL,
                "active_tab_count": 0,
                "modules": list(modules),
                "viewer": None,
            },
            *viewers,
        )
    )


@pytest.mark.parametrize(
    ("module", "expected"),
    [
        (
            _module(
                "/ananas/modules/video/index.html",
                has_job_icon=True,
            ),
            TaskType.VIDEO,
        ),
        (
            _module(
                "/ananas/modules/pdf/index.html",
                has_job_icon=True,
            ),
            TaskType.DOCUMENT,
        ),
        (
            _module("/ananas/modules/work/index.html"),
            TaskType.QUIZ,
        ),
        (
            _module("/ananas/modules/insertbbs/index.html"),
            TaskType.COMMENT,
        ),
    ],
)
def test_pending_module_maps_to_task_type(
    module: dict[str, Any],
    expected: TaskType,
) -> None:
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
    detector = ChaoxingTaskDetector(_browser_with_modules())

    assert detector.detect() is TaskType.CONTENT


def test_document_without_job_icon_and_unread_viewer_is_document() -> None:
    browser = _browser_with_modules(_module("/ananas/modules/pdf/index.html"))

    assert ChaoxingTaskDetector(browser).detect() is TaskType.DOCUMENT


def test_document_without_job_icon_at_bottom_is_content() -> None:
    browser = _browser_with_modules(
        _module("/ananas/modules/pdf/index.html"),
        viewers=(
            _viewer(
                "pdf-a",
                scroll_y=684,
            ),
        ),
    )

    assert ChaoxingTaskDetector(browser).detect() is TaskType.CONTENT


def test_incomplete_viewer_mount_is_still_document_even_if_temporarily_at_bottom() -> None:
    browser = _browser_with_modules(
        _module(
            "/ananas/modules/pdf/index.html",
            declared_page_count=2,
        ),
        viewers=(
            _viewer(
                "pdf-a",
                scroll_y=684,
                page_count=1,
            ),
        ),
    )

    assert ChaoxingTaskDetector(browser).detect() is TaskType.DOCUMENT


def test_unread_document_without_job_icon_precedes_later_task_point() -> None:
    browser = _browser_with_modules(
        _module("/ananas/modules/pdf/index.html"),
        _module(
            "/ananas/modules/video/index.html",
            has_job_icon=True,
        ),
    )

    assert ChaoxingTaskDetector(browser).detect() is TaskType.DOCUMENT


@pytest.mark.parametrize(
    ("module_path", "expected"),
    [
        (
            "/ananas/modules/video/index.html",
            TaskType.VIDEO,
        ),
        (
            "/ananas/modules/work/index.html",
            TaskType.QUIZ,
        ),
        (
            "/ananas/modules/insertbbs/index.html",
            TaskType.COMMENT,
        ),
    ],
)
def test_document_at_bottom_reveals_later_task_point(
    module_path: str,
    expected: TaskType,
) -> None:
    browser = _browser_with_modules(
        _module("/ananas/modules/pdf/index.html"),
        _module(
            module_path,
            has_job_icon=True,
        ),
        viewers=(
            _viewer(
                "pdf-a",
                scroll_y=684,
            ),
        ),
    )

    assert ChaoxingTaskDetector(browser).detect() is expected


def test_first_document_at_bottom_reveals_second_unread_document() -> None:
    browser = _browser_with_modules(
        _module(
            "/ananas/modules/pdf/index.html",
            object_id="pdf-a",
        ),
        _module(
            "/ananas/modules/pdf/index.html",
            object_id="pdf-b",
        ),
        viewers=(
            _viewer(
                "pdf-a",
                scroll_y=684,
            ),
            _viewer(
                "pdf-b",
                scroll_y=0,
            ),
        ),
    )

    assert ChaoxingTaskDetector(browser).detect() is TaskType.DOCUMENT


def test_pdf_with_missing_object_id_is_unknown() -> None:
    malformed_pdf = _module("/ananas/modules/pdf/index.html")

    malformed_pdf["object_id"] = None

    detector = ChaoxingTaskDetector(_browser_with_modules(malformed_pdf))

    assert detector.detect() is TaskType.UNKNOWN


def test_all_finished_job_modules_are_content() -> None:
    browser = _browser_with_modules(
        _module(
            "/ananas/modules/video/index.html",
            has_job_icon=True,
            finished=True,
        ),
        _module(
            "/ananas/modules/pdf/index.html",
            has_job_icon=True,
            finished=True,
        ),
        _module(
            "/ananas/modules/insertbbs/index.html",
            has_job_icon=True,
            finished=True,
        ),
    )

    assert ChaoxingTaskDetector(browser).detect() is TaskType.CONTENT


def test_finished_job_video_is_skipped_for_unfinished_document() -> None:
    browser = _browser_with_modules(
        _module(
            "/ananas/modules/video/index.html",
            has_job_icon=True,
            finished=True,
        ),
        _module(
            "/ananas/modules/pdf/index.html",
            has_job_icon=True,
        ),
    )

    assert ChaoxingTaskDetector(browser).detect() is TaskType.DOCUMENT


def test_non_job_module_is_not_skipped() -> None:
    browser = _browser_with_modules(
        _module(
            "/ananas/modules/work/index.html",
            has_job_icon=False,
            finished=True,
        ),
    )

    assert ChaoxingTaskDetector(browser).detect() is TaskType.QUIZ


def test_first_pending_module_wins_when_content_frame_has_multiple_modules() -> None:
    browser = _browser_with_modules(
        _module("/ananas/modules/insertbbs/index.html"),
        _module(
            "/ananas/modules/video/index.html",
            has_job_icon=True,
        ),
        _module("/ananas/modules/work/index.html"),
    )

    assert ChaoxingTaskDetector(browser).detect() is TaskType.COMMENT


def test_unknown_first_pending_module_is_not_skipped() -> None:
    browser = _browser_with_modules(
        _module("/ananas/modules/audio/index.html"),
        _module(
            "/ananas/modules/video/index.html",
            has_job_icon=True,
        ),
    )

    assert ChaoxingTaskDetector(browser).detect() is TaskType.UNKNOWN


@pytest.mark.parametrize(
    "frame_results",
    [
        (),
        (
            {
                "frame_url": _PAGE_URL,
                "active_tab_count": 0,
                "modules": [],
                "viewer": None,
            },
        ),
        (
            {
                "frame_url": _PAGE_URL,
                "active_tab_count": 2,
                "modules": [],
                "viewer": None,
            },
        ),
        (
            {
                "frame_url": _PAGE_URL,
                "active_tab_count": 1,
                "modules": [],
                "viewer": None,
            },
        ),
        (
            {
                "frame_url": _PAGE_URL,
                "active_tab_count": 1,
                "modules": [],
                "viewer": None,
            },
            {
                "frame_url": _CONTENT_URL,
                "active_tab_count": 0,
                "modules": [],
                "viewer": None,
            },
            {
                "frame_url": f"{_CONTENT_URL}&num=2",
                "active_tab_count": 0,
                "modules": [],
                "viewer": None,
            },
        ),
        (
            {
                "frame_url": None,
                "active_tab_count": 1,
                "modules": [],
                "viewer": None,
            },
        ),
        (
            {
                "frame_url": _PAGE_URL,
                "active_tab_count": 1,
                "modules": [],
                "viewer": None,
            },
            {
                "frame_url": _CONTENT_URL,
                "active_tab_count": 0,
                "modules": "invalid",
                "viewer": None,
            },
        ),
        (
            {
                "frame_url": _PAGE_URL,
                "active_tab_count": 1,
                "modules": [],
                "viewer": None,
            },
            {
                "frame_url": _CONTENT_URL,
                "active_tab_count": 0,
                "modules": [_module(None)],
                "viewer": None,
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


@pytest.mark.parametrize(
    ("active_tabs", "content_count", "reason"),
    [
        (0, 0, "incomplete_card_state"),
        (1, 0, "incomplete_card_state"),
        (2, 1, "ambiguous_card_state"),
        (1, 2, "ambiguous_card_state"),
    ],
)
def test_card_unavailability_logs_safe_counts(
    active_tabs: int, content_count: int, reason: str, caplog: pytest.LogCaptureFixture
) -> None:
    frames = (
        {"frame_url": _PAGE_URL, "active_tab_count": active_tabs, "modules": [], "viewer": None},
        *(
            {"frame_url": _CONTENT_URL, "active_tab_count": 0, "modules": [], "viewer": None}
            for _ in range(content_count)
        ),
    )
    caplog.set_level(logging.DEBUG)

    assert ChaoxingTaskDetector(FakeBrowser(frame_evaluation_results=frames)).detect() is TaskType.UNKNOWN

    assert f"reason={reason}" in caplog.text
    assert f"active_tab_count={active_tabs} content_frame_count={content_count}" in caplog.text
    assert "reason=course_state_unavailable" in caplog.text
    assert _PAGE_URL not in caplog.text
    assert _CONTENT_URL not in caplog.text


def test_unsupported_module_diagnostic_does_not_log_url_or_skip(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    browser = _browser_with_modules(
        _module("https://example.test/ananas/modules/audio/index.html?token=PRIVATE"),
        _module("/ananas/modules/video/index.html"),
    )

    assert ChaoxingTaskDetector(browser).detect() is TaskType.UNKNOWN

    assert "reason=unsupported_module_type stage=module_classification module_index=0" in caplog.text
    assert (
        "module_kind=audio module_index=0 module_count=2 has_job_icon=False finished=False" in caplog.text
    )
    assert "example.test" not in caplog.text
    assert "PRIVATE" not in caplog.text


@pytest.mark.parametrize(
    ("module_url", "expected_kind"),
    [
        ("/ananas/modules/ppt/index.html?token=PRIVATE", "ppt"),
        ("/ananas/modules/PRIVATE/index.html", "unrecognized_kind"),
        ("/ananas/modules/PRIVATE_audio/index.html", "unrecognized_kind"),
        ("/ananas/modules/audio?token=PRIVATE", "audio"),
        ("/other/PRIVATE?route=/ananas/modules/audio/", "unrecognized_route"),
    ],
)
def test_unsupported_module_kind_diagnostic_uses_only_allowlisted_path_labels(
    module_url: str, expected_kind: str, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    browser = _browser_with_modules(_module(module_url, has_job_icon=True))

    assert ChaoxingTaskDetector(browser).detect() is TaskType.UNKNOWN

    assert (
        f"module_kind={expected_kind} module_index=0 module_count=1 has_job_icon=True finished=False"
        in caplog.text
    )
    assert "PRIVATE" not in caplog.text


@pytest.mark.parametrize(
    ("module", "stage"),
    [
        (_module(None), "module_parsing"),
        (_module("/ananas/modules/pdf/index.html", object_id=""), "document_parsing"),
    ],
)
def test_malformed_module_logs_parsing_stage(
    module: dict[str, Any], stage: str, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)

    assert ChaoxingTaskDetector(_browser_with_modules(module)).detect() is TaskType.UNKNOWN

    assert f"reason=malformed_state stage={stage} module_index=0" in caplog.text


def test_malformed_frame_logs_card_parsing_stage(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    browser = FakeBrowser(frame_evaluation_results=({"frame_url": None},))

    assert ChaoxingTaskDetector(browser).detect() is TaskType.UNKNOWN

    assert "reason=malformed_state stage=card_parsing" in caplog.text


def test_browser_failure_diagnostic_omits_exception_text(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    browser = FakeBrowser(observation_error=BrowserError("Cookie=PRIVATE api_key=SECRET page body"))

    assert ChaoxingTaskDetector(browser).detect() is TaskType.UNKNOWN

    assert "reason=dom_inspection_failed stage=frame_evaluation" in caplog.text
    assert "PRIVATE" not in caplog.text
    assert "SECRET" not in caplog.text
    assert "page body" not in caplog.text


@pytest.mark.parametrize("missing", [True, False])
def test_video_observation_change_logs_transient_reason(
    missing: bool, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    state = ChaoxingPageState(
        content_frame_url=_CONTENT_URL,
        knowledge_id=None,
        active_tab_index=0,
        has_next_tab=False,
        modules=() if missing else (ChaoxingModuleState("https://example.test/changed", False, False),),
        videos=(),
    )
    monkeypatch.setattr("linkforge.platforms.chaoxing.task_detector.inspect_chaoxing_page", lambda _: state)
    detector = ChaoxingTaskDetector(
        _browser_with_modules(_module("/ananas/modules/video/index.html")), video_session=VideoSession()
    )

    assert detector.detect() is TaskType.UNKNOWN

    reason = "module_missing_between_observations" if missing else "module_changed_between_observations"
    assert f"reason={reason} stage=video_session_inspection module_index=0" in caplog.text
    assert "example.test" not in caplog.text


def test_secondary_inspection_failure_logs_stage_without_exception_details(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)

    def fail_inspection(_: object) -> ChaoxingPageState:
        raise ChaoxingInspectionError("https://example.test/course?token=PRIVATE")

    monkeypatch.setattr("linkforge.platforms.chaoxing.task_detector.inspect_chaoxing_page", fail_inspection)
    detector = ChaoxingTaskDetector(
        _browser_with_modules(_module("/ananas/modules/video/index.html")), video_session=VideoSession()
    )

    assert detector.detect() is TaskType.UNKNOWN

    assert "reason=page_state_inspection_failed stage=video_session_inspection" in caplog.text
    assert "PRIVATE" not in caplog.text


def test_detector_implements_application_contract_without_llm() -> None:
    detector = ChaoxingTaskDetector(_browser_with_modules())

    assert isinstance(
        detector,
        TaskDetector,
    )
