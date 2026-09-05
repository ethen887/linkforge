"""Unit tests for Playwright-specific browser behavior."""

from types import SimpleNamespace

import pytest
from playwright.sync_api import Error as PlaywrightError

from linkforge.browser.exceptions import BrowserError
from linkforge.browser.playwright import PlaywrightBrowser


class FakeFrame:
    """Record frame inspection behavior without launching Playwright."""

    def __init__(
        self,
        *,
        result: object = None,
        detached: bool = False,
        error: PlaywrightError | None = None,
    ) -> None:
        self.result = result
        self.detached = detached
        self.error = error
        self.evaluate_calls: list[str] = []

    def is_detached(self) -> bool:
        return self.detached

    def evaluate(self, expression: str) -> object:
        self.evaluate_calls.append(expression)
        if self.error is not None:
            raise self.error
        return self.result


def _browser_with_frames(*frames: FakeFrame) -> PlaywrightBrowser:
    browser = PlaywrightBrowser.__new__(PlaywrightBrowser)
    browser._page = SimpleNamespace(is_closed=lambda: False, frames=list(frames))
    return browser


def test_evaluate_in_frames_skips_frames_detached_before_or_during_evaluation() -> None:
    attached_first = FakeFrame(result={"frame": "first"})
    detached_before = FakeFrame(detached=True)
    detached_during = FakeFrame(error=PlaywrightError("Frame was detached"))
    attached_last = FakeFrame(result={"frame": "last"})
    browser = _browser_with_frames(
        attached_first,
        detached_before,
        detached_during,
        attached_last,
    )

    results = browser.evaluate_in_frames("() => document.title")

    assert results == ({"frame": "first"}, {"frame": "last"})
    assert detached_before.evaluate_calls == []
    assert detached_during.evaluate_calls == ["() => document.title"]


def test_evaluate_in_frames_converts_other_playwright_errors() -> None:
    playwright_error = PlaywrightError("Execution context was destroyed")
    browser = _browser_with_frames(FakeFrame(error=playwright_error))

    with pytest.raises(BrowserError, match="Failed to inspect page frames") as exc_info:
        browser.evaluate_in_frames("() => document.title")

    assert exc_info.value.__cause__ is playwright_error


def test_persistent_profile_path_must_not_be_empty() -> None:
    with pytest.raises(ValueError, match="user_data_dir must not be empty"):
        PlaywrightBrowser(user_data_dir="  ")
