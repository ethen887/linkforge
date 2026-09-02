"""Unit tests for browser-backed action execution."""

import pytest

from linkforge.action.browser import BrowserActionExecutor
from linkforge.action.exceptions import ActionExecutionError
from linkforge.action.models import Action, ClickAction, FillAction, OpenAction, PressAction, ScrollAction
from linkforge.browser.base import Browser
from linkforge.browser.exceptions import BrowserError
from tests.fakes import FakeBrowser


@pytest.mark.parametrize(
    ("action", "expected_call"),
    [
        (OpenAction(url="https://example.com"), ("open", "https://example.com")),
        (ClickAction(selector="#submit"), ("click", "#submit")),
        (FillAction(selector="#name", text="LinkForge"), ("fill", "#name", "LinkForge")),
        (PressAction(selector="#name", key="Enter"), ("press", "#name", "Enter")),
        (ScrollAction(delta_y=500), ("scroll", 500)),
    ],
)
def test_browser_action_executor_maps_action_to_browser_call(
    action: Action,
    expected_call: tuple[object, ...],
) -> None:
    browser: Browser = FakeBrowser()

    BrowserActionExecutor(browser).execute(action)

    assert isinstance(browser, FakeBrowser)
    assert browser.action_calls == [expected_call]


def test_browser_action_executor_converts_browser_error() -> None:
    browser_error = BrowserError("Browser action failed.")
    browser = FakeBrowser(action_error=browser_error)

    with pytest.raises(ActionExecutionError) as exc_info:
        BrowserActionExecutor(browser).execute(ClickAction(selector="#submit"))

    assert exc_info.value.__cause__ is browser_error
