"""Local Playwright integration for the optimistic Chaoxing comment workflow."""

import time
from typing import Any
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import Route

from linkforge.application.task_runner import TaskHandler, TaskRunner
from linkforge.browser.playwright import PlaywrightBrowser
from linkforge.platforms.chaoxing.comment_handler import (
    ChaoxingCommentHandlerConfig,
    ChaoxingCommentTaskHandler,
)
from linkforge.platforms.chaoxing.comment_state import CommentOutcome, CommentSession
from linkforge.platforms.chaoxing.content_handler import (
    ChaoxingContentHandlerConfig,
    ChaoxingContentTaskHandler,
)
from linkforge.platforms.chaoxing.dom import inspect_chaoxing_page
from linkforge.platforms.chaoxing.exceptions import (
    ChaoxingCommentGenerationError,
    ChaoxingCommentRecoveryError,
)
from linkforge.platforms.chaoxing.task_detector import ChaoxingTaskDetector

_SOURCE = "https://mooc1.chaoxing.com/mycourse/studentstudy?courseId=course-1&clazzid=class-1&cpi=account-1"
_CONTENT = "https://mooc1.chaoxing.com/mooc-ans/knowledge/cards"
_TOPIC = (
    "https://groupweb.chaoxing.com/course/topic/v3/bbs/topic-1/replysList?courseId=course-1&classId=class-1"
)


class _BodyGenerator:
    def __init__(self, body: str = "这是自动化测试评论。") -> None:
        self.body = body
        self.calls: list[tuple[str, str]] = []

    def generate(self, *, title: str, prompt: str) -> str:
        self.calls.append((title, prompt))
        return self.body


class _FailingGenerator(_BodyGenerator):
    def generate(self, *, title: str, prompt: str) -> str:
        self.calls.append((title, prompt))
        raise ChaoxingCommentGenerationError("local model failure")


class _NoopHandler(TaskHandler):
    def run(self) -> None:
        raise AssertionError("Unexpected task handler dispatch.")


class _RecordingBrowser(PlaywrightBrowser):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.submit_calls = 0
        self.fills: list[tuple[str, str]] = []

    def fill(self, selector: str, text: str) -> None:
        self.fills.append((selector, text))
        super().fill(selector, text)

    def click(self, selector: str) -> None:
        if selector.endswith(".addReply"):
            self.submit_calls += 1
        super().click(selector)


class _LostSourceBrowser(_RecordingBrowser):
    def close_page(self, page: Any) -> None:
        for page_id, managed in self._pages.items():
            if page_id != page.page_id and not managed.is_closed():
                managed.close()
                break
        super().close_page(page)


def _route(route: Route, *, block_submit: bool = False, duplicate_entry: bool = False) -> None:
    html_headers = {"content-type": "text/html; charset=utf-8"}
    parsed = urlparse(route.request.url)
    if parsed.path == "/mycourse/studentstudy":
        route.fulfill(
            headers=html_headers,
            body=f"""
                <ul id="prev_tab">
                  <li class="active">讨论</li>
                  <li onclick="document.querySelector('#content').src=
                    '{_CONTENT}?knowledgeid=k1&num=1';
                    this.previousElementSibling.className='';this.className='active'">下一卡片</li>
                </ul>
                <iframe id="content" src="{_CONTENT}?knowledgeid=k1&num=0"></iframe>
            """,
        )
    elif parsed.path == "/mooc-ans/knowledge/cards":
        number = parse_qs(parsed.query).get("num", [""])[0]
        body = (
            '<div class="ans-attach-ct">'
            '<iframe src="https://mooc1.chaoxing.com/ananas/modules/insertbbs/index.html"></iframe>'
            "</div>"
            if number == "0"
            else "<p>ordinary next Card</p>"
        )
        route.fulfill(headers=html_headers, body=body)
    elif parsed.path == "/ananas/modules/insertbbs/index.html":
        route.fulfill(
            headers=html_headers,
            body='<iframe src="https://mooc1.chaoxing.com/mooc-ans/bbscircle/chapter"></iframe>',
        )
    elif parsed.path == "/mooc-ans/bbscircle/chapter":
        entry = f"""
          <div id="topicMainDiv" class="PublicCardBox" onclick="window.open('{_TOPIC}')">
            <p class="cardRightTit">本地讨论标题</p>
            <span class="Booksspan">教师提出的本地测试问题是什么？</span>
          </div>
        """
        route.fulfill(
            headers=html_headers,
            body=entry + (entry if duplicate_entry else ""),
        )
    elif parsed.hostname == "groupweb.chaoxing.com":
        submit_style = 'style="pointer-events:none"' if block_submit else ""
        route.fulfill(
            headers=html_headers,
            body=f"""
              <section id="bbsTopicDetail">
                <div class="topicDetail_title">本地讨论标题 置顶</div>
                <div class="topicDetail_title_right"><div class="replyBtn">回复</div></div>
                <div class="topicDetail_editContainer"><div class="replyEdit">
                  <textarea placeholder="回复话题"></textarea>
                  <div class="addReply" {submit_style}
                    onclick="document.body.dataset.submitted='true'">回复</div>
                </div></div>
              </section>
            """,
        )
    else:
        route.fulfill(status=204, body="")


def _wait_ready(browser: PlaywrightBrowser) -> None:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        try:
            inspect_chaoxing_page(browser)
            return
        except Exception:
            time.sleep(0.01)
    raise AssertionError("Local Chaoxing fixture did not become ready.")


def _start_fixture(
    browser: _RecordingBrowser, *, block_submit: bool = False, duplicate_entry: bool = False
) -> None:
    browser.start()
    browser._require_page().context.route(
        "**/*", lambda route: _route(route, block_submit=block_submit, duplicate_entry=duplicate_entry)
    )
    browser.open(_SOURCE)
    _wait_ready(browser)


def _build_comment_handler(
    browser: _RecordingBrowser, generator: _BodyGenerator
) -> tuple[ChaoxingCommentTaskHandler, ChaoxingTaskDetector]:
    session = CommentSession()
    detector = ChaoxingTaskDetector(browser, comment_session=session)
    handler = ChaoxingCommentTaskHandler(
        browser,
        comment_session=session,
        body_generator=generator,
        detector=detector,
        config=ChaoxingCommentHandlerConfig(readiness_timeout_seconds=3, poll_interval_seconds=0.01),
    )
    return handler, detector


def test_task_runner_comments_once_then_content_handler_advances_with_insertbbs_still_present() -> None:
    browser = _RecordingBrowser(headless=True, timeout_ms=3_000)
    _start_fixture(browser)
    try:
        generator = _BodyGenerator()
        comment, detector = _build_comment_handler(browser, generator)
        content = ChaoxingContentTaskHandler(
            browser,
            detector=detector,
            config=ChaoxingContentHandlerConfig(navigation_timeout_seconds=3, poll_interval_seconds=0.01),
        )
        unused = _NoopHandler()
        runner = TaskRunner(
            detector=detector,
            video_handler=unused,
            document_handler=unused,
            content_handler=content,
            comment_handler=comment,
            quiz_handler=unused,
        )

        def advanced() -> bool:
            return inspect_chaoxing_page(browser).active_tab_index == 1

        runner.run(should_stop=advanced)

        assert generator.calls == [("本地讨论标题", "教师提出的本地测试问题是什么？")]
        assert browser.fills == [
            (
                '.topicDetail_editContainer .replyEdit textarea[placeholder="回复话题"]',
                "这是自动化测试评论。",
            )
        ]
        assert browser.submit_calls == 1
        assert comment.last_record is not None
        assert comment.last_record.outcome is CommentOutcome.ATTEMPTED_UNVERIFIED
        assert inspect_chaoxing_page(browser).active_tab_index == 1
    finally:
        browser.close()


def test_model_failure_and_empty_body_skip_without_submission_and_restore_course() -> None:
    for generator in (_FailingGenerator(), _BodyGenerator("   ")):
        browser = _RecordingBrowser(headless=True, timeout_ms=3_000)
        _start_fixture(browser)
        try:
            handler, _ = _build_comment_handler(browser, generator)

            handler.run()

            assert browser.submit_calls == 0
            assert handler.last_record is not None
            assert handler.last_record.outcome is CommentOutcome.SKIPPED
            assert browser.current_url() == _SOURCE
            assert len(generator.calls) == 1
        finally:
            browser.close()


def test_submit_timeout_is_recorded_unknown_and_never_retried() -> None:
    browser = _RecordingBrowser(headless=True, timeout_ms=200)
    _start_fixture(browser, block_submit=True)
    try:
        generator = _BodyGenerator()
        handler, detector = _build_comment_handler(browser, generator)

        handler.run()

        assert browser.submit_calls == 1
        assert handler.last_record is not None
        assert handler.last_record.outcome is CommentOutcome.SUBMISSION_UNKNOWN
        assert detector.detect().name == "CONTENT"
        handler.run()
        assert browser.submit_calls == 1
        assert len(generator.calls) == 1
    finally:
        browser.close()


def test_multiple_discussion_entries_are_skipped_without_clicking() -> None:
    browser = _RecordingBrowser(headless=True, timeout_ms=3_000)
    _start_fixture(browser, duplicate_entry=True)
    try:
        handler, _ = _build_comment_handler(browser, _BodyGenerator())

        handler.run()

        assert browser.submit_calls == 0
        assert handler.last_record is not None
        assert handler.last_record.outcome is CommentOutcome.SKIPPED
    finally:
        browser.close()


def test_lost_source_page_stops_instead_of_continuing() -> None:
    browser = _LostSourceBrowser(headless=True, timeout_ms=3_000)
    _start_fixture(browser)
    try:
        handler, _ = _build_comment_handler(browser, _BodyGenerator())

        try:
            handler.run()
        except ChaoxingCommentRecoveryError:
            pass
        else:
            raise AssertionError("Lost source page must stop the workflow.")
    finally:
        browser.close()
