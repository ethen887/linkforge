"""Unit tests for production Browser construction."""

import linkforge.browser.factory as factory_module
from linkforge.browser.base import Browser
from linkforge.browser.factory import create_browser
from linkforge.config.settings import BrowserConfig
from tests.fakes import FakeBrowser


def test_create_browser_forwards_all_runtime_configuration(monkeypatch) -> None:
    created = FakeBrowser()
    received: dict[str, object] = {}

    def create_playwright_browser(**kwargs: object) -> Browser:
        received.update(kwargs)
        return created

    monkeypatch.setattr(factory_module, "PlaywrightBrowser", create_playwright_browser)

    result = create_browser(
        BrowserConfig(
            headless=True,
            timeout_ms=7_500,
            profile_dir="browser-profile",
        )
    )

    assert result is created
    assert received == {
        "headless": True,
        "timeout_ms": 7_500,
        "profile_dir": "browser-profile",
    }
