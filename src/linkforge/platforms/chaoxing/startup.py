"""Bounded, cancellable startup readiness before Chaoxing task detection."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from math import isfinite

from linkforge.browser.base import Browser
from linkforge.browser.exceptions import BrowserClosedError, BrowserError

logger = logging.getLogger(__name__)

# Return only readiness flags, never credentials, page text, or full URLs.
CHAOXING_STARTUP_SCRIPT = r"""() => {
    const host = location.hostname.toLowerCase();
    const path = location.pathname.toLowerCase();
    const trusted = host === 'chaoxing.com' || host.endsWith('.chaoxing.com');
    const loaded = document.readyState === 'complete';
    const loginHost = host === 'passport2.chaoxing.com'
        || host === 'passport.chaoxing.com';
    const loginPage = trusted && (loginHost || path.split('/').some(
        segment => segment === 'login' || segment === 'loginindex'));
    const cardPath = path.endsWith('/') ? path.slice(0, -1) : path;
    return {
        login_page: loginPage,
        personal_home: window === window.top && host === 'i.chaoxing.com' && loaded,
        content_ready: trusted && cardPath === '/mooc-ans/knowledge/cards'
            && loaded,
        active_tab_count: document.querySelectorAll('#prev_tab li.active').length,
    };
}"""


class ChaoxingStartupTimeoutError(RuntimeError):
    """Manual login or course readiness did not finish before its deadline."""


class ChaoxingStartupWait:
    """Wait for a loaded course card, allowing the user to log in manually."""

    def __init__(
        self,
        *,
        login_timeout_seconds: float = 600.0,
        page_timeout_seconds: float = 30.0,
        poll_interval_seconds: float = 0.5,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        for value in (login_timeout_seconds, page_timeout_seconds, poll_interval_seconds):
            if not isfinite(value) or value <= 0:
                raise ValueError("Startup timing values must be finite and positive")
        self._login_timeout = login_timeout_seconds
        self._page_timeout = page_timeout_seconds
        self._poll_interval = poll_interval_seconds
        self._sleep = sleep
        self._monotonic = monotonic

    def wait(self, *, browser: Browser, course_url: str, should_stop: Callable[[], bool]) -> bool:
        """Return on course readiness or stop, raising on timeout or browser closure.

        A ready course passes on the first probe without sleeping. Login grants
        a bounded manual-login window; leaving the login page alone is never
        treated as proof that TaskRunner can start.
        """
        deadline = self._monotonic() + self._page_timeout
        login_seen = False
        course_reopened = False
        waiting_announced = False
        while True:
            if should_stop():
                logger.info("Chaoxing startup wait stopped")
                return False
            login_page, course_ready, personal_home = self._probe(browser)
            if should_stop():
                logger.info("Chaoxing startup wait stopped")
                return False
            if course_ready and not login_page:
                logger.info("Chaoxing course page ready")
                return True
            now = self._monotonic()
            if login_page and not login_seen:
                login_seen = True
                deadline = now + self._login_timeout
                logger.info("Chaoxing manual login required")
            elif not waiting_announced and not login_seen:
                logger.info("Waiting for Chaoxing course page")
                waiting_announced = True

            if now >= deadline:
                logger.error("Chaoxing startup readiness timed out")
                if login_seen:
                    raise ChaoxingStartupTimeoutError(
                        "等待学习通登录或课程页面就绪超时，请完成登录后重新开始。"
                    )
                raise ChaoxingStartupTimeoutError("课程页面未能就绪，请检查课程地址和页面加载情况。")

            # Some login flows land in the personal space instead of the course.
            # Navigate once, only after observing login followed by that landing.
            if login_seen and personal_home and not login_page and not course_reopened:
                if should_stop():
                    return False
                logger.info("Returning to requested Chaoxing course after login")
                browser.open(course_url)
                course_reopened = True
                continue
            self._sleep(min(self._poll_interval, deadline - now))

    @staticmethod
    def _probe(browser: Browser) -> tuple[bool, bool, bool]:
        try:
            results = browser.evaluate_in_frames(CHAOXING_STARTUP_SCRIPT)
        except BrowserClosedError:
            raise
        except BrowserError as exc:
            # Navigation may replace frames or their execution contexts.
            logger.debug("Chaoxing startup probe temporarily unavailable (%s)", type(exc).__name__)
            return False, False, False

        login_page = False
        personal_home = False
        content_count = 0
        active_tab_count = 0
        for result in results:
            if not isinstance(result, dict):
                return False, False, False
            if any(
                not isinstance(result.get(key), bool)
                for key in ("login_page", "content_ready", "personal_home")
            ):
                return False, False, False
            count = result.get("active_tab_count")
            if not isinstance(count, int) or isinstance(count, bool) or count < 0:
                return False, False, False
            login_page |= result["login_page"]
            personal_home |= result["personal_home"]
            content_count += int(result["content_ready"])
            active_tab_count += count
        return login_page, content_count == 1 and active_tab_count == 1, personal_home
