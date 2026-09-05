"""Unit tests for Playwright-specific browser behavior."""

from types import SimpleNamespace

import pytest
from playwright.sync_api import Error as PlaywrightError

import linkforge.browser.playwright as playwright_module
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


class FakePage:
    def __init__(self) -> None:
        self.closed = False
        self.close_calls = 0
        self.default_timeout: int | None = None
        self.default_navigation_timeout: int | None = None

    def is_closed(self) -> bool:
        return self.closed

    def set_default_timeout(self, timeout_ms: int) -> None:
        self.default_timeout = timeout_ms

    def set_default_navigation_timeout(self, timeout_ms: int) -> None:
        self.default_navigation_timeout = timeout_ms

    def close(self) -> None:
        self.close_calls += 1
        self.closed = True


class FakeContext:
    def __init__(self, pages: list[FakePage] | None = None) -> None:
        self.pages = pages if pages is not None else []
        self.new_page_calls = 0
        self.close_calls = 0

    def new_page(self) -> FakePage:
        self.new_page_calls += 1
        page = FakePage()
        self.pages.append(page)
        return page

    def close(self) -> None:
        self.close_calls += 1


class FakeNativeBrowser:
    def __init__(self, context: FakeContext) -> None:
        self.context = context
        self.new_context_calls = 0
        self.close_calls = 0

    def new_context(self) -> FakeContext:
        self.new_context_calls += 1
        return self.context

    def close(self) -> None:
        self.close_calls += 1


class FakeChromium:
    def __init__(
        self,
        *,
        temporary_browser: FakeNativeBrowser,
        persistent_context: FakeContext,
    ) -> None:
        self.temporary_browser = temporary_browser
        self.persistent_context = persistent_context
        self.launch_calls: list[dict[str, object]] = []
        self.persistent_launch_calls: list[dict[str, object]] = []

    def launch(self, **kwargs: object) -> FakeNativeBrowser:
        self.launch_calls.append(kwargs)
        return self.temporary_browser

    def launch_persistent_context(self, **kwargs: object) -> FakeContext:
        self.persistent_launch_calls.append(kwargs)
        return self.persistent_context


class FakePlaywright:
    def __init__(self, chromium: FakeChromium) -> None:
        self.chromium = chromium
        self.stop_calls = 0

    def stop(self) -> None:
        self.stop_calls += 1


class FakePlaywrightStarter:
    def __init__(self, runtime: FakePlaywright) -> None:
        self.runtime = runtime

    def start(self) -> FakePlaywright:
        return self.runtime


def _fake_runtime(
    monkeypatch: pytest.MonkeyPatch,
    *,
    persistent_pages: list[FakePage] | None = None,
) -> tuple[FakeChromium, FakeNativeBrowser, FakeContext, FakePlaywright]:
    temporary_context = FakeContext()
    temporary_browser = FakeNativeBrowser(temporary_context)
    persistent_context = FakeContext(persistent_pages)
    chromium = FakeChromium(
        temporary_browser=temporary_browser,
        persistent_context=persistent_context,
    )
    runtime = FakePlaywright(chromium)
    monkeypatch.setattr(
        playwright_module,
        "sync_playwright",
        lambda: FakePlaywrightStarter(runtime),
    )
    return chromium, temporary_browser, persistent_context, runtime


def _browser_with_frames(*frames: FakeFrame) -> PlaywrightBrowser:
    browser = PlaywrightBrowser.__new__(PlaywrightBrowser)
    browser._page = SimpleNamespace(is_closed=lambda: False, frames=list(frames))
    return browser


def test_evaluate_in_frames_skips_frames_detached_before_or_during_evaluation() -> None:
    attached_first = FakeFrame(result={"frame": "first"})
    detached_before = FakeFrame(detached=True)
    detached_during = FakeFrame(error=PlaywrightError("Frame was detached"))
    navigated_during = FakeFrame(
        error=PlaywrightError("Execution context was destroyed, most likely because of a navigation")
    )
    attached_last = FakeFrame(result={"frame": "last"})
    browser = _browser_with_frames(
        attached_first,
        detached_before,
        detached_during,
        navigated_during,
        attached_last,
    )

    results = browser.evaluate_in_frames("() => document.title")

    assert results == ({"frame": "first"}, {"frame": "last"})
    assert detached_before.evaluate_calls == []
    assert detached_during.evaluate_calls == ["() => document.title"]
    assert navigated_during.evaluate_calls == ["() => document.title"]


def test_evaluate_in_frames_converts_other_playwright_errors() -> None:
    playwright_error = PlaywrightError("SyntaxError: Unexpected token")
    browser = _browser_with_frames(FakeFrame(error=playwright_error))

    with pytest.raises(BrowserError, match="Failed to inspect page frames") as exc_info:
        browser.evaluate_in_frames("() => document.title")

    assert exc_info.value.__cause__ is playwright_error


def test_profile_dir_none_preserves_temporary_browser_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chromium, native_browser, persistent_context, runtime = _fake_runtime(monkeypatch)
    browser = PlaywrightBrowser(headless=True, timeout_ms=2_000, profile_dir=None)

    browser.start()
    browser.close()

    assert chromium.launch_calls == [{"headless": True}]
    assert chromium.persistent_launch_calls == []
    assert native_browser.new_context_calls == 1
    assert native_browser.context.new_page_calls == 1
    assert native_browser.context.pages[0].close_calls == 1
    assert native_browser.context.close_calls == 1
    assert native_browser.close_calls == 1
    assert persistent_context.close_calls == 0
    assert runtime.stop_calls == 1


@pytest.mark.parametrize("profile_dir", ["", " ", "\t"])
def test_empty_profile_dir_is_rejected(profile_dir: str) -> None:
    with pytest.raises(ValueError, match="profile_dir must not be empty"):
        PlaywrightBrowser(profile_dir=profile_dir)


def test_persistent_profile_uses_existing_page_and_context_owned_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    existing_page = FakePage()
    chromium, native_browser, persistent_context, runtime = _fake_runtime(
        monkeypatch,
        persistent_pages=[existing_page],
    )
    browser = PlaywrightBrowser(headless=True, timeout_ms=2_000, profile_dir="profile-dir")

    browser.start()
    browser.close()
    browser.close()

    assert chromium.launch_calls == []
    assert chromium.persistent_launch_calls == [{"user_data_dir": "profile-dir", "headless": True}]
    assert persistent_context.new_page_calls == 0
    assert existing_page.default_timeout == 2_000
    assert existing_page.default_navigation_timeout == 2_000
    assert existing_page.close_calls == 0
    assert persistent_context.close_calls == 1
    assert native_browser.close_calls == 0
    assert runtime.stop_calls == 1


def test_persistent_profile_creates_page_only_when_context_has_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chromium, _, persistent_context, _ = _fake_runtime(monkeypatch)
    browser = PlaywrightBrowser(profile_dir="profile-dir")

    browser.start()
    browser.close()

    assert len(chromium.persistent_launch_calls) == 1
    assert persistent_context.new_page_calls == 1
