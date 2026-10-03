"""Startup DOM probes with intercepted local HTML, without Chaoxing access."""

import pytest
from playwright.sync_api import sync_playwright

from linkforge.platforms.chaoxing.startup import CHAOXING_STARTUP_SCRIPT


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
