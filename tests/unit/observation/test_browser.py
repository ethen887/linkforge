"""Unit tests for browser-backed observations."""

import pytest

from linkforge.browser.base import Browser
from linkforge.browser.exceptions import BrowserError
from linkforge.observation.browser import BrowserObserver
from linkforge.observation.exceptions import ObservationCaptureError
from linkforge.observation.models import Observation
from tests.fakes import FakeBrowser


def test_browser_observer_captures_browser_state() -> None:
    browser: Browser = FakeBrowser(
        url="https://example.com/page",
        title="Example Page",
        text="Page content",
    )

    observation = BrowserObserver(browser).observe()

    assert observation == Observation(
        url="https://example.com/page",
        title="Example Page",
        text="Page content",
    )


def test_browser_observer_converts_browser_error() -> None:
    browser_error = BrowserError("Browser state is unavailable.")
    browser = FakeBrowser(observation_error=browser_error)

    with pytest.raises(ObservationCaptureError) as exc_info:
        BrowserObserver(browser).observe()

    assert exc_info.value.__cause__ is browser_error
