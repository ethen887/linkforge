"""确认用户选择的新课程卡片，并同步续播位置。"""

import logging
import time
from collections.abc import Callable

from linkforge.browser.base import Browser
from linkforge.browser.exceptions import BrowserClosedError, BrowserError
from linkforge.platforms.chaoxing.dom import inspect_chaoxing_page
from linkforge.platforms.chaoxing.exceptions import ChaoxingInspectionError
from linkforge.platforms.chaoxing.models import ChaoxingPageState
from linkforge.platforms.chaoxing.progress import course_resume_url

logger = logging.getLogger(__name__)


def card_identity(state: ChaoxingPageState) -> tuple[str, int]:
    """卡片 URL 与选项卡一起标识当前页面，不把模块完成状态当成换页。"""
    return state.content_frame_url, state.active_tab_index


class ChaoxingNavigationMonitor:
    """等待连续一致的可识别快照，避免在换页中途处理或跳过新内容。"""

    def __init__(
        self,
        browser: Browser,
        *,
        on_course_url_changed: Callable[[str], None] | None = None,
        poll_interval_seconds: float = 0.25,
        timeout_seconds: float = 30.0,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if poll_interval_seconds <= 0 or timeout_seconds <= 0:
            raise ValueError("navigation wait intervals must be positive")
        self._browser = browser
        self._on_course_url_changed = on_course_url_changed
        self._poll_interval = poll_interval_seconds
        self._timeout = timeout_seconds
        self._sleep = sleep
        self._monotonic = monotonic

    def follow_if_changed(
        self,
        previous: ChaoxingPageState,
        *,
        observed: ChaoxingPageState | None = None,
        should_stop: Callable[[], bool] | None = None,
    ) -> bool:
        """确认换页后返回 True；原页面、停止、浏览器关闭或超时返回 False。"""
        if should_stop is not None and should_stop():
            return False
        candidate = observed
        if candidate is None:
            try:
                candidate = inspect_chaoxing_page(self._browser)
            except (BrowserError, ChaoxingInspectionError):
                return False
        if card_identity(candidate) == card_identity(previous):
            return False

        deadline = self._monotonic() + self._timeout
        while self._monotonic() < deadline:
            if should_stop is not None and should_stop():
                return False
            self._sleep(max(0, min(self._poll_interval, deadline - self._monotonic())))
            if should_stop is not None and should_stop():
                return False
            try:
                current = inspect_chaoxing_page(self._browser)
            except BrowserClosedError:
                return False
            except (BrowserError, ChaoxingInspectionError):
                candidate = None
                continue
            if candidate is not None and self._same_snapshot(candidate, current):
                logger.info("Following the selected Chaoxing course page")
                self._report_progress(current)
                return True
            candidate = current
        return False

    @staticmethod
    def _same_snapshot(left: ChaoxingPageState, right: ChaoxingPageState) -> bool:
        return card_identity(left) == card_identity(right) and tuple(
            (module.url, module.frame_path) for module in left.modules
        ) == tuple((module.url, module.frame_path) for module in right.modules)

    def _report_progress(self, state: ChaoxingPageState) -> None:
        if self._on_course_url_changed is None:
            return
        try:
            url = course_resume_url(self._browser.current_url(), state)
            if url is not None:
                self._on_course_url_changed(url)
        except Exception:
            logger.warning("Selected course progress could not be reported")
