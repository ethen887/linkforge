"""Verify iframe-only navigation checkpoints using local intercepted HTML."""

import time
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import Route

from linkforge.browser.playwright import PlaywrightBrowser
from linkforge.platforms.chaoxing.content_handler import (
    ChaoxingContentHandlerConfig,
    ChaoxingContentTaskHandler,
)
from linkforge.platforms.chaoxing.dom import inspect_chaoxing_page
from linkforge.platforms.chaoxing.exceptions import ChaoxingInspectionError

_PAGE = "https://course.example.test/mycourse/studentstudy?courseId=test&chapterId=100&num=0"
_CARDS = "https://course.example.test/mooc-ans/knowledge/cards"


def _route(route: Route) -> None:
    parsed = urlsplit(route.request.url)
    query = parse_qs(parsed.query)
    if parsed.path == "/mycourse/studentstudy":
        chapter = query["chapterId"][0]
        number = query["num"][0]
        body = f"""
            <ul id="prev_tab">
                <li class="{"active" if number == "0" else ""}">First</li>
                <li class="{"active" if number == "1" else ""}" onclick="
                    this.previousElementSibling.className='';this.className='active';
                    document.getElementById('content').src='{_CARDS}?knowledgeid={chapter}&num=1';
                ">Second</li>
            </ul>
            <iframe id="content" src="{_CARDS}?knowledgeid={chapter}&num={number}"></iframe>
        """
    elif parsed.path == "/mooc-ans/knowledge/cards":
        body = "<p>Local ordinary content</p>"
    else:
        raise AssertionError("Unexpected local test request")
    route.fulfill(content_type="text/html", body=body)


def _wait_for_card(browser: PlaywrightBrowser, number: int) -> None:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        try:
            state = inspect_chaoxing_page(browser)
            if state.active_tab_index == number:
                return
        except ChaoxingInspectionError:
            pass
        time.sleep(0.02)
    raise AssertionError("Local course did not become ready")


def test_iframe_navigation_saves_outer_url_and_can_reopen_same_card() -> None:
    updates: list[str] = []
    with PlaywrightBrowser(headless=True, timeout_ms=3_000) as browser:
        browser._require_page().context.route("**/*", _route)
        browser.open(_PAGE)
        _wait_for_card(browser, 0)
        handler = ChaoxingContentTaskHandler(
            browser,
            config=ChaoxingContentHandlerConfig(poll_interval_seconds=0.05, navigation_timeout_seconds=2),
            on_course_url_changed=updates.append,
        )
        handler.run()
        assert browser.current_url() == _PAGE
        assert updates == [_PAGE.replace("num=0", "num=1")]
        browser.open(updates[0])
        _wait_for_card(browser, 1)
        assert inspect_chaoxing_page(browser).content_frame_url == _CARDS + "?knowledgeid=100&num=1"
