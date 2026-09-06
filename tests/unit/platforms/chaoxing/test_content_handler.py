"""Unit tests for evidence-bounded Chaoxing content navigation."""

import pytest

from linkforge.application.task_runner import TaskHandler, TaskType
from linkforge.platforms.chaoxing.content_handler import (
    ChaoxingContentHandlerConfig,
    ChaoxingContentTaskHandler,
)
from linkforge.platforms.chaoxing.exceptions import (
    ChaoxingInspectionError,
    ContentNavigationError,
)
from tests.fakes import FakeBrowser

_PAGE_URL = "https://mooc1.chaoxing.com/mycourse/studentstudy"
_CONTENT_BASE_URL = "https://mooc1.chaoxing.com/mooc-ans/knowledge/cards"


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class ScriptedContentBrowser(FakeBrowser):
    def __init__(
        self,
        states: list[tuple[object, ...] | ChaoxingInspectionError],
        *,
        tree_inspection_results: tuple[object, ...] | None = None,
        tree_click_results: tuple[object, ...] | None = None,
    ) -> None:
        super().__init__()
        self._states = states
        self._state_index = 0
        self.tree_inspection_results = tree_inspection_results
        self.tree_click_results = tree_click_results
        self.tree_calls: list[str] = []

    def evaluate_in_frames(self, expression: str) -> tuple[object, ...]:
        self.frame_evaluation_calls.append(expression)
        if '.posCatalog_select[id^=\\"cur\\"]' in expression:
            self.tree_calls.append(expression)
            if "target.click()" in expression:
                if self.tree_click_results is None:
                    raise AssertionError("Unexpected knowledge-tree click.")
                return self.tree_click_results
            if self.tree_inspection_results is None:
                raise AssertionError("Unexpected knowledge-tree inspection.")
            return self.tree_inspection_results

        if not self._states:
            raise AssertionError("No scripted Chaoxing page state exists.")
        index = min(self._state_index, len(self._states) - 1)
        self._state_index += 1
        result = self._states[index]
        if isinstance(result, ChaoxingInspectionError):
            raise result
        return result


def _content_url(knowledge_id: str | None, *, card_number: int = 0) -> str:
    knowledge_query = f"&knowledgeid={knowledge_id}" if knowledge_id is not None else ""
    return f"{_CONTENT_BASE_URL}?num={card_number}{knowledge_query}"


def _state(
    *,
    knowledge_id: str | None = "100",
    card_number: int = 0,
    active_index: int = 0,
    has_next: bool = False,
    modules: list[dict[str, object]] | None = None,
    viewers: tuple[dict[str, object], ...] = (),
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
            "frame_url": _content_url(knowledge_id, card_number=card_number),
            "active_tab_count": 0,
            "active_tab_index": None,
            "has_next_tab": False,
            "modules": list(modules or []),
            "video_count": 0,
            "video": None,
        },
        *viewers,
    )


def _document_module(
    *,
    object_id: str = "141755adf0d07a601e4027b3878aca2b",
) -> dict[str, object]:
    return {
        "module_url": "/ananas/modules/pdf/index.html",
        "object_id": object_id,
        "declared_page_count": 2,
        "has_job_icon": False,
        "finished": False,
    }


def _document_viewer(
    *,
    object_id: str = "141755adf0d07a601e4027b3878aca2b",
    scroll_y: float,
) -> dict[str, object]:
    inner_height = 546.0
    scroll_height = 1_230.0
    bottom_distance = scroll_height - (scroll_y + inner_height)
    return {
        "frame_url": f"https://pan-yz.chaoxing.com/screen/v2/file_{object_id}",
        "active_tab_count": 0,
        "active_tab_index": None,
        "has_next_tab": False,
        "modules": [],
        "video_count": 0,
        "video": None,
        "viewer": {
            "object_id": object_id,
            "page_count": 2,
            "visible_pages": [1, 2],
            "scroll_y": scroll_y,
            "inner_height": inner_height,
            "scroll_height": scroll_height,
            "bottom_distance": bottom_distance,
            "at_bottom": bottom_distance <= 8,
        },
    }


def _tree_inspection(
    *,
    matched: bool = True,
    has_next: bool = True,
    target_found: bool = True,
    next_id: str | None = "cur200",
    frame_url: str = _PAGE_URL,
) -> dict[str, object]:
    return {
        "frame_url": frame_url,
        "matched": matched,
        "has_next": has_next,
        "target_found": target_found,
        "next_id": next_id,
    }


def _tree_click(
    *,
    matched: bool = True,
    clicked: bool = True,
    next_id: str | None = "cur200",
    frame_url: str = _PAGE_URL,
) -> dict[str, object]:
    return {
        "frame_url": frame_url,
        "matched": matched,
        "clicked": clicked,
        "next_id": next_id,
        "reason": None,
    }


def _cross_knowledge_browser(
    states: list[tuple[object, ...] | ChaoxingInspectionError],
    *,
    inspection_results: tuple[object, ...] | None = None,
    click_results: tuple[object, ...] | None = None,
) -> ScriptedContentBrowser:
    return ScriptedContentBrowser(
        states,
        tree_inspection_results=inspection_results or (_tree_inspection(),),
        tree_click_results=click_results or (_tree_click(),),
    )


def _handler(browser: FakeBrowser, clock: FakeClock) -> ChaoxingContentTaskHandler:
    return ChaoxingContentTaskHandler(
        browser,
        config=ChaoxingContentHandlerConfig(
            poll_interval_seconds=1.0,
            navigation_timeout_seconds=3.0,
        ),
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )


def test_content_clicks_next_card_without_inspecting_knowledge_tree() -> None:
    browser = ScriptedContentBrowser(
        [
            _state(active_index=0, has_next=True),
            _state(active_index=1, has_next=False, card_number=1),
        ]
    )
    clock = FakeClock()

    _handler(browser, clock).run()

    assert browser.action_calls == [("click", "#prev_tab li.active + li")]
    assert browser.tree_calls == []


def test_next_card_waits_until_old_content_document_route_is_replaced() -> None:
    initial = _state(active_index=0, has_next=True)
    browser = ScriptedContentBrowser(
        [
            initial,
            initial,
            _state(active_index=1, card_number=0),
            _state(active_index=1, card_number=1),
        ]
    )

    _handler(browser, FakeClock()).run()

    assert browser.action_calls == [("click", "#prev_tab li.active + li")]
    assert len(browser.frame_evaluation_calls) == 4


def test_content_navigation_accepts_ordinary_pdf_at_viewer_bottom() -> None:
    handled_pdf_state = _state(
        active_index=0,
        has_next=True,
        modules=[_document_module()],
        viewers=(_document_viewer(scroll_y=684),),
    )
    browser = ScriptedContentBrowser(
        [
            handled_pdf_state,
            handled_pdf_state,
            _state(active_index=1, card_number=1),
        ]
    )

    _handler(browser, FakeClock()).run()

    assert browser.action_calls == [("click", "#prev_tab li.active + li")]


def test_content_navigation_rejects_unread_ordinary_pdf() -> None:
    unread_pdf_state = _state(
        has_next=True,
        modules=[_document_module()],
        viewers=(_document_viewer(scroll_y=0),),
    )
    browser = ScriptedContentBrowser([unread_pdf_state])

    with pytest.raises(
        ContentNavigationError,
        match="pending Chaoxing module appeared.*DOCUMENT",
    ):
        _handler(browser, FakeClock()).run()

    assert browser.action_calls == []


def test_last_card_clicks_next_knowledge_and_waits_for_knowledge_id_change() -> None:
    browser = _cross_knowledge_browser([_state(knowledge_id="100"), _state(knowledge_id="200")])
    clock = FakeClock()

    _handler(browser, clock).run()

    assert browser.action_calls == []
    assert len(browser.tree_calls) == 2
    assert ".posCatalog_name" in browser.tree_calls[0]
    assert "target.click()" in browser.tree_calls[1]
    assert "getTeacherAjax" not in browser.tree_calls[1]


def test_content_frame_url_change_without_knowledge_id_change_times_out() -> None:
    browser = _cross_knowledge_browser(
        [
            _state(knowledge_id="100", card_number=0),
            _state(knowledge_id="100", card_number=1),
        ]
    )
    clock = FakeClock()

    with pytest.raises(ContentNavigationError, match="knowledgeId did not change"):
        _handler(browser, clock).run()


def test_missing_current_knowledge_node_fails() -> None:
    browser = _cross_knowledge_browser(
        [_state()],
        inspection_results=(_tree_inspection(matched=False),),
    )

    with pytest.raises(ContentNavigationError, match="was not found"):
        _handler(browser, FakeClock()).run()


def test_current_knowledge_node_in_multiple_frames_is_ambiguous() -> None:
    browser = _cross_knowledge_browser(
        [_state()],
        inspection_results=(
            _tree_inspection(frame_url=_PAGE_URL),
            _tree_inspection(frame_url="https://mooc1.chaoxing.com/duplicate"),
        ),
    )

    with pytest.raises(ContentNavigationError, match="ambiguous across frames"):
        _handler(browser, FakeClock()).run()


def test_last_knowledge_node_does_not_guess_whole_course_complete() -> None:
    browser = _cross_knowledge_browser(
        [_state()],
        inspection_results=(_tree_inspection(has_next=False, target_found=False, next_id=None),),
    )

    with pytest.raises(ContentNavigationError, match="whole-course completion is not yet evidenced"):
        _handler(browser, FakeClock()).run()


def test_next_knowledge_without_click_target_fails() -> None:
    browser = _cross_knowledge_browser(
        [_state()],
        inspection_results=(_tree_inspection(target_found=False),),
    )

    with pytest.raises(ContentNavigationError, match="no .posCatalog_name"):
        _handler(browser, FakeClock()).run()


@pytest.mark.parametrize(
    "click_results",
    [
        ("malformed",),
        (_tree_click(), _tree_click(frame_url="https://mooc1.chaoxing.com/duplicate")),
        (_tree_click(clicked=False),),
    ],
)
def test_malformed_ambiguous_or_unsuccessful_click_result_fails(
    click_results: tuple[object, ...],
) -> None:
    browser = _cross_knowledge_browser([_state()], click_results=click_results)

    with pytest.raises(ContentNavigationError):
        _handler(browser, FakeClock()).run()


def test_transient_frame_replacement_recovers_before_knowledge_changes() -> None:
    browser = _cross_knowledge_browser(
        [
            _state(knowledge_id="100"),
            ChaoxingInspectionError("detached once"),
            ChaoxingInspectionError("detached twice"),
            _state(knowledge_id="200"),
        ]
    )

    _handler(browser, FakeClock()).run()


@pytest.mark.parametrize(
    "transient_state",
    [
        ChaoxingInspectionError("detached repeatedly"),
        (),
    ],
)
def test_authoritative_safety_check_times_out_when_state_stays_unknown(
    transient_state: tuple[object, ...] | ChaoxingInspectionError,
) -> None:
    browser = ScriptedContentBrowser(
        [
            _state(has_next=True),
            transient_state,
        ]
    )
    clock = FakeClock()

    with pytest.raises(ContentNavigationError, match="safe for CONTENT navigation"):
        _handler(browser, clock).run()

    assert clock.now == 3.0
    assert browser.action_calls == []


def test_page_without_knowledge_id_fails_before_tree_navigation() -> None:
    browser = ScriptedContentBrowser([_state(knowledge_id=None)])

    with pytest.raises(ContentNavigationError, match="no valid knowledgeId"):
        _handler(browser, FakeClock()).run()

    assert browser.tree_calls == []


@pytest.mark.parametrize(
    ("module", "expected_task"),
    [
        (
            {
                "module_url": "/ananas/modules/video/index.html",
                "has_job_icon": True,
                "finished": False,
            },
            TaskType.VIDEO,
        ),
        (
            {
                "module_url": "/ananas/modules/work/index.html",
                "has_job_icon": True,
                "finished": False,
            },
            TaskType.QUIZ,
        ),
        (
            {
                "module_url": "/ananas/modules/insertbbs/index.html",
                "has_job_icon": True,
                "finished": False,
            },
            TaskType.COMMENT,
        ),
    ],
)
def test_pending_module_race_prevents_content_from_skipping_work(
    module: dict[str, object],
    expected_task: TaskType,
) -> None:
    browser = ScriptedContentBrowser(
        [
            _state(
                has_next=True,
                modules=[module],
            )
        ]
    )

    with pytest.raises(
        ContentNavigationError,
        match=rf"pending Chaoxing module appeared.*{expected_task.name}",
    ):
        _handler(browser, FakeClock()).run()

    assert browser.action_calls == []


def test_unchanged_active_card_fails_at_navigation_deadline() -> None:
    browser = ScriptedContentBrowser([_state(active_index=0, has_next=True)])

    with pytest.raises(ContentNavigationError, match="active card did not change"):
        _handler(browser, FakeClock()).run()


def test_handler_implements_platform_neutral_application_contract() -> None:
    handler = _handler(ScriptedContentBrowser([_state(has_next=True)]), FakeClock())

    assert isinstance(handler, TaskHandler)
