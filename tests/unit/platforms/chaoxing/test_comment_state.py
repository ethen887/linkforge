"""Session record and detector tests for optimistic Chaoxing comments."""

from typing import Any

import pytest

from linkforge.application.task_runner import TaskType
from linkforge.platforms.chaoxing.comment_state import (
    CommentAccountChangedError,
    CommentOutcome,
    CommentSession,
    comment_identity,
)
from linkforge.platforms.chaoxing.dom import inspect_chaoxing_page
from linkforge.platforms.chaoxing.task_detector import ChaoxingTaskDetector
from tests.fakes import FakeBrowser

_COURSE = "https://mooc1.chaoxing.com/mycourse/studentstudy?courseId=course-1&clazzid=class-1&cpi=account-1"
_CONTENT = "https://mooc1.chaoxing.com/mooc-ans/knowledge/cards?knowledgeid=k1&num=0"


def _module(path: str, *, finished: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {
        "module_url": path,
        "has_job_icon": finished,
        "finished": finished,
    }
    if "/pdf/" in path:
        result.update(object_id="pdf-1", declared_page_count=2)
    return result


def _browser(*modules: dict[str, Any], course_url: str = _COURSE) -> FakeBrowser:
    return FakeBrowser(
        url=course_url,
        frame_evaluation_results=(
            {
                "frame_url": course_url,
                "active_tab_count": 1,
                "active_tab_index": 0,
                "has_next_tab": True,
                "modules": [],
                "viewer": None,
                "video_count": 0,
                "video": None,
            },
            {
                "frame_url": _CONTENT,
                "active_tab_count": 0,
                "modules": list(modules),
                "viewer": None,
                "video_count": 0,
                "video": None,
            },
        ),
    )


def test_discussion_words_without_insertbbs_are_ordinary_content() -> None:
    browser = _browser()

    assert ChaoxingTaskDetector(browser, comment_session=CommentSession()).detect() is TaskType.CONTENT


@pytest.mark.parametrize(
    "outcome",
    [CommentOutcome.ATTEMPTED_UNVERIFIED, CommentOutcome.SUBMISSION_UNKNOWN, CommentOutcome.SKIPPED],
)
def test_handled_comment_outcomes_are_not_dispatched_again(outcome: CommentOutcome) -> None:
    browser = _browser(_module("/ananas/modules/insertbbs/index.html"))
    session = CommentSession()
    state = inspect_chaoxing_page(browser)
    identity = comment_identity(browser.current_url(), state, 0)
    session.record(identity, outcome, stage="test")

    assert ChaoxingTaskDetector(browser, comment_session=session).detect() is TaskType.CONTENT


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/ananas/modules/video/index.html", TaskType.VIDEO),
        ("/ananas/modules/pdf/index.html", TaskType.DOCUMENT),
        ("/ananas/modules/work/index.html", TaskType.QUIZ),
    ],
)
def test_handled_comment_does_not_hide_later_modules(path: str, expected: TaskType) -> None:
    first = _module("/ananas/modules/insertbbs/index.html")
    browser = _browser(first, _module(path))
    session = CommentSession()
    session.record(
        comment_identity(browser.current_url(), inspect_chaoxing_page(browser), 0),
        CommentOutcome.ATTEMPTED_UNVERIFIED,
        stage="test",
    )

    assert ChaoxingTaskDetector(browser, comment_session=session).detect() is expected


def test_handled_discussion_a_does_not_hide_discussion_b() -> None:
    comment = _module("/ananas/modules/insertbbs/index.html")
    browser = _browser(comment, comment)
    session = CommentSession()
    session.record(
        comment_identity(browser.current_url(), inspect_chaoxing_page(browser), 0),
        CommentOutcome.SKIPPED,
        stage="test",
    )

    assert ChaoxingTaskDetector(browser, comment_session=session).detect() is TaskType.COMMENT


def test_comment_sessions_do_not_share_records() -> None:
    browser = _browser(_module("/ananas/modules/insertbbs/index.html"))
    state = inspect_chaoxing_page(browser)
    first = CommentSession()
    first.record(comment_identity(browser.current_url(), state, 0), CommentOutcome.SKIPPED, stage="test")

    assert ChaoxingTaskDetector(browser, comment_session=CommentSession()).detect() is TaskType.COMMENT


def test_session_rejects_account_context_change() -> None:
    browser = _browser(_module("/ananas/modules/insertbbs/index.html"))
    session = CommentSession()
    first = comment_identity(browser.current_url(), inspect_chaoxing_page(browser), 0)
    session.record(first, CommentOutcome.SKIPPED, stage="test")
    changed = _browser(
        _module("/ananas/modules/insertbbs/index.html"),
        course_url=_COURSE.replace("account-1", "account-2"),
    )

    with pytest.raises(CommentAccountChangedError):
        session.is_handled(comment_identity(changed.current_url(), inspect_chaoxing_page(changed), 0))

    assert ChaoxingTaskDetector(changed, comment_session=session).detect() is TaskType.UNKNOWN
