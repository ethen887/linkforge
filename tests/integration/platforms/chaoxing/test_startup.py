"""Startup DOM probes with intercepted local HTML, without Chaoxing access."""

from urllib.parse import urlsplit

import pytest
from playwright.sync_api import sync_playwright

from linkforge.browser.playwright import PlaywrightBrowser
from linkforge.platforms.chaoxing.startup import CHAOXING_STARTUP_SCRIPT, ChaoxingStartupWait


@pytest.mark.parametrize(
    ("url", "login", "home", "content"),
    [
        ("https://passport2.chaoxing.com/login?ticket=unused", True, False, False),
        ("https://cas.chaoxing.com/cas/login", True, False, False),
        ("https://mooc1.chaoxing.com/loginindex", True, False, False),
        ("https://i.chaoxing.com/base", False, True, False),
        ("https://mooc1.chaoxing.com/mycourse/studentstudy", False, False, False),
        ("https://mooc1.chaoxing.com/mooc-ans/knowledge/cards?knowledgeid=1", False, False, True),
        ("https://chaoxing.com.evil.test/mooc-ans/knowledge/cards", False, False, False),
    ],
)
def test_startup_probe_classifies_actual_url_and_dom_without_returning_secrets(
    url: str, login: bool, home: bool, content: bool
) -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.route(
                "**/*",
                lambda route: route.fulfill(
                    content_type="text/html",
                    body='<ul id="prev_tab"><li class="active">Card</li></ul>',
                ),
            )
            page.goto(url)

            assert page.evaluate(CHAOXING_STARTUP_SCRIPT) == {
                "login_page": login,
                "personal_home": home,
                "content_ready": content,
                "active_tab_count": 1,
            }
        finally:
            browser.close()


def test_course_card_frame_is_not_ready_until_loaded() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.route("**/*", lambda route: route.fulfill(content_type="text/html", body="<p>Card</p>"))
            page.goto("https://mooc1.chaoxing.com/mooc-ans/knowledge/cards?knowledgeid=1")
            page.evaluate("Object.defineProperty(document, 'readyState', {value: 'loading'})")

            assert page.evaluate(CHAOXING_STARTUP_SCRIPT)["content_ready"] is False
        finally:
            browser.close()


def test_navigation_and_course_readiness_do_not_wait_for_pending_images() -> None:
    with PlaywrightBrowser(headless=True, timeout_ms=1_000) as browser:
        assert browser._page is not None
        pending = []

        def route_request(route):
            path = urlsplit(route.request.url).path
            if path.endswith(".png"):
                pending.append(route)
                return  # Keep image requests pending through the readiness check.
            body = (
                '<ul id="prev_tab"><li class="active">Card</li></ul>'
                '<img src="/slow-top.png"><iframe src="/mooc-ans/knowledge/cards"></iframe>'
                if path == "/mycourse/studentstudy"
                else '<div class="ans-attach-ct">Card</div><img src="/slow-card.png">'
            )
            route.fulfill(content_type="text/html", body=body)

        browser._page.route("**/*", route_request)
        url = "https://mooc1.chaoxing.com/mycourse/studentstudy"
        browser.open_for_readiness(url)
        assert ChaoxingStartupWait(page_timeout_seconds=2, poll_interval_seconds=0.05).wait(
            browser=browser,
            course_url=url,
            should_stop=lambda: False,
        )
        assert pending
        assert "interactive" in browser.evaluate_in_frames("() => document.readyState")
