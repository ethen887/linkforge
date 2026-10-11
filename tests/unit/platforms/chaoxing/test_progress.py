"""Course checkpoints use the outer course route and verified iframe position."""

from dataclasses import replace

import pytest

from linkforge.platforms.chaoxing.models import ChaoxingPageState
from linkforge.platforms.chaoxing.progress import course_resume_url

_STATE = ChaoxingPageState(
    content_frame_url="https://course.example.test/mooc-ans/knowledge/cards?knowledgeid=200&num=2",
    knowledge_id="200",
    active_tab_index=2,
    has_next_tab=False,
    modules=(),
    videos=(),
)


@pytest.mark.parametrize("path", ["/mycourse/studentstudy", "/mooc-ans/mycourse/studentstudy"])
@pytest.mark.parametrize("chapter_key", ["chapterId", "chapterid", "knowledgeId"])
def test_checkpoint_replaces_stale_outer_position_and_preserves_other_parameters(path, chapter_key):
    page = f"https://course.example.test{path}?courseId=c1&{chapter_key}=100&num=0&enc=a%2fb+z#course"
    assert course_resume_url(page, _STATE) == (
        f"https://course.example.test{path}?courseId=c1&{chapter_key}=200&num=2&enc=a%2fb+z#course"
    )


def test_checkpoint_adds_position_when_address_bar_does_not_track_iframe():
    page = "https://course.example.test/mycourse/studentstudy?courseId=c1"
    assert course_resume_url(page, _STATE) == page + "&chapterId=200&num=2"


@pytest.mark.parametrize(
    "page",
    [
        "https://course.example.test/login?chapterId=100",
        "https://course.example.test/mooc-ans/knowledge/cards?knowledgeid=100&num=0",
        "https://course.example.test/ananas/modules/video/index.html",
        "about:blank",
        "",
    ],
)
def test_checkpoint_rejects_login_and_module_pages(page):
    assert course_resume_url(page, _STATE) is None


@pytest.mark.parametrize("query", ["knowledgeid=200", "num=-1", "num=x", "num=0&num=1"])
def test_checkpoint_rejects_missing_or_ambiguous_card_position(query):
    state = replace(
        _STATE, content_frame_url=f"https://course.example.test/mooc-ans/knowledge/cards?{query}"
    )
    assert course_resume_url("https://course.example.test/mycourse/studentstudy", state) is None


def test_checkpoint_rejects_missing_knowledge_identity():
    assert (
        course_resume_url(
            "https://course.example.test/mycourse/studentstudy", replace(_STATE, knowledge_id=None)
        )
        is None
    )
