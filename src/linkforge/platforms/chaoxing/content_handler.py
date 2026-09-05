"""Advance ordinary Chaoxing content to the next evidenced card tab."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from linkforge.application.task_runner import TaskHandler
from linkforge.browser.base import Browser
from linkforge.browser.exceptions import BrowserError
from linkforge.platforms.chaoxing.dom import first_pending_module, inspect_chaoxing_page
from linkforge.platforms.chaoxing.exceptions import (
    ChaoxingInspectionError,
    ContentNavigationError,
)

_NEXT_CARD_SELECTOR = "#prev_tab li.active + li"


@dataclass(frozen=True, slots=True)
class ChaoxingContentHandlerConfig:
    """Bounded wait used to verify a card-tab transition."""

    poll_interval_seconds: float = 0.25
    navigation_timeout_seconds: float = 15.0

    def __post_init__(self) -> None:
        if self.poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be greater than 0")
        if self.navigation_timeout_seconds <= 0:
            raise ValueError("navigation_timeout_seconds must be greater than 0")


class ChaoxingContentTaskHandler(TaskHandler):
    """Move from CONTENT to the next sibling in the verified Chaoxing card tab list."""

    def __init__(
        self,
        browser: Browser,
        *,
        config: ChaoxingContentHandlerConfig | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._browser = browser
        self._config = config or ChaoxingContentHandlerConfig()
        self._sleep = sleep
        self._monotonic = monotonic

    def run(self) -> None:
        """Click the next evidenced card tab and wait until the active tab changes."""
        try:
            initial_state = inspect_chaoxing_page(self._browser)
        except ChaoxingInspectionError as exc:
            raise ContentNavigationError("Unable to inspect the current Chaoxing content.") from exc

        if first_pending_module(initial_state) is not None:
            raise ContentNavigationError(
                "A pending Chaoxing module appeared before CONTENT navigation could start."
            )

        if not initial_state.has_next_tab:
            raise ContentNavigationError(
                "No next #prev_tab card is available; cross-chapter navigation is not evidenced."
            )

        try:
            self._browser.click(_NEXT_CARD_SELECTOR)
        except BrowserError as exc:
            raise ContentNavigationError("Failed to click the next Chaoxing card tab.") from exc

        deadline = self._monotonic() + self._config.navigation_timeout_seconds
        while self._monotonic() < deadline:
            self._sleep(self._config.poll_interval_seconds)
            try:
                current_state = inspect_chaoxing_page(self._browser)
            except ChaoxingInspectionError:
                # Card iframe replacement is transient; the bounded deadline remains authoritative.
                continue

            if current_state.active_tab_index != initial_state.active_tab_index:
                return

        raise ContentNavigationError(
            "The Chaoxing active card did not change before the navigation deadline."
        )
