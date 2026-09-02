"""Unit tests for browser-backed action execution."""

import pytest

from linkforge.action.browser import BrowserActionExecutor
from linkforge.action.exceptions import ActionExecutionError
from linkforge.action.models import Action, ClickAction, FillAction, OpenAction, PressAction, ScrollAction
from linkforge.browser.base import Browser
from linkforge.browser.exceptions import BrowserElementError, BrowserError
from linkforge.browser.models import InteractiveElement
from tests.fakes import FakeBrowser

_INTERACTIVE_ELEMENTS = (
    InteractiveElement(target_id=1, role="textbox", name="Search"),
    InteractiveElement(target_id=2, role="button", name="Submit"),
)


@pytest.mark.parametrize(
    ("action", "expected_call"),
    [
        (OpenAction(url="https://example.com"), ("open", "https://example.com")),
        (ClickAction(target_id=2), ("click_target", 2)),
        (FillAction(target_id=1, text="LinkForge"), ("fill_target", 1, "LinkForge")),
        (PressAction(target_id=1, key="Enter"), ("press_target", 1, "Enter")),
        (ScrollAction(delta_y=500), ("scroll", 500)),
    ],
)
def test_browser_action_executor_maps_action_to_browser_call(
    action: Action,
    expected_call: tuple[object, ...],
) -> None:
    browser: Browser = FakeBrowser(interactive_elements=_INTERACTIVE_ELEMENTS)
    browser.interactive_elements()

    BrowserActionExecutor(browser).execute(action)

    assert isinstance(browser, FakeBrowser)
    assert browser.action_calls == [expected_call]


def test_browser_action_executor_converts_browser_error() -> None:
    browser_error = BrowserError("Browser action failed.")
    browser = FakeBrowser(
        interactive_elements=_INTERACTIVE_ELEMENTS,
        action_error=browser_error,
    )
    browser.interactive_elements()

    with pytest.raises(ActionExecutionError) as exc_info:
        BrowserActionExecutor(browser).execute(ClickAction(target_id=2))

    assert exc_info.value.__cause__ is browser_error


@pytest.mark.parametrize("target_id", [0, 999])
def test_browser_action_executor_rejects_unknown_target(target_id: int) -> None:
    browser = FakeBrowser(interactive_elements=_INTERACTIVE_ELEMENTS)
    browser.interactive_elements()

    with pytest.raises(ActionExecutionError) as exc_info:
        BrowserActionExecutor(browser).execute(ClickAction(target_id=target_id))

    assert isinstance(exc_info.value.__cause__, BrowserElementError)
