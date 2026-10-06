"""Real scrolling with readiness and progress checks for the innerbook layout."""

import logging
import time
from collections.abc import Callable

from linkforge.browser.base import Browser
from linkforge.browser.exceptions import BrowserError
from linkforge.platforms.chaoxing.document_inspection import (
    inspect_innerbook_viewers,
    parse_document_inspection,
    parse_module_basics,
)
from linkforge.platforms.chaoxing.dom import CHAOXING_CARD_STATE_SCRIPT
from linkforge.platforms.chaoxing.exceptions import (
    ChaoxingDocumentInspectionError,
    ChaoxingDocumentProgressTimeoutError,
    ChaoxingDocumentStateError,
    ChaoxingDocumentTimeoutError,
    ChaoxingDocumentViewerReadyTimeoutError,
)
from linkforge.platforms.chaoxing.innerbook import (
    InnerbookSession,
    InnerbookTarget,
    find_innerbook_viewer,
    frame_path,
)
from linkforge.platforms.chaoxing.innerbook_dom import build_innerbook_action_script

logger = logging.getLogger(__name__)


class ChaoxingInnerbookReader:
    """Process one known book without treating missing markers as completion."""

    def __init__(
        self,
        browser: Browser,
        session: InnerbookSession,
        *,
        timeout_seconds: float | None = None,
        ready_timeout_seconds: float = 10.0,
        progress_timeout_seconds: float = 5.0,
        poll_interval_seconds: float = 0.1,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if min(ready_timeout_seconds, progress_timeout_seconds, poll_interval_seconds) <= 0 or (
            timeout_seconds is not None and timeout_seconds <= 0
        ):
            raise ValueError("innerbook timing values must be positive")
        self._browser = browser
        self._session = session
        self._timeout = timeout_seconds
        self._ready_timeout = ready_timeout_seconds
        self._progress_timeout = progress_timeout_seconds
        self._interval = poll_interval_seconds
        self._clock = clock
        self._sleep = sleeper

    def read(self, target: InnerbookTarget) -> None:
        deadline = self._clock() + self._timeout if self._timeout is not None else None
        unavailable_since: float | None = self._clock()
        last_y: float | None = None
        progress_at = self._clock()
        reader_url: str | None = None
        reader_path: tuple[int, ...] | None = None
        requires_marker = False
        marker_since: float | None = None
        while deadline is None or self._clock() < deadline:
            try:
                inspection = parse_document_inspection(
                    self._browser.evaluate_in_frames(CHAOXING_CARD_STATE_SCRIPT)
                )
                viewer = None
                finished = False
                if inspection is not None:
                    if inspection.content_frame_url != target.card_url or target.index >= len(
                        inspection.modules
                    ):
                        raise ChaoxingDocumentStateError(
                            "The card or target innerbook changed during reading."
                        )
                    raw = inspection.modules[target.index]
                    module_url, has_job_icon, finished = parse_module_basics(raw)
                    if (
                        module_url != target.module_url
                        or frame_path(raw.get("frame_path")) != target.module_path
                    ):
                        raise ChaoxingDocumentStateError(
                            "The target innerbook identity changed during reading."
                        )
                    requires_marker = requires_marker or has_job_icon
                    if has_job_icon and finished:
                        logger.info(
                            "Innerbook completed with platform task marker: module_index=%d", target.index
                        )
                        return
                    inspection = inspect_innerbook_viewers(self._browser, inspection)
                    viewer = find_innerbook_viewer(raw, inspection.innerbook_viewers)
                if viewer is not None:
                    if reader_url is not None and (viewer.url != reader_url or viewer.path != reader_path):
                        raise ChaoxingDocumentStateError(
                            "The innerbook reader identity changed during reading."
                        )
                    reader_url, reader_path = viewer.url, viewer.path
                    self._browser.evaluate_in_frames(
                        build_innerbook_action_script(target.module_path, viewer.path, 0)
                    )
            except BrowserError as exc:
                raise ChaoxingDocumentInspectionError(
                    "Failed to inspect or scroll innerbook reader."
                ) from exc
            except ValueError as exc:
                raise ChaoxingDocumentStateError("Malformed innerbook reader state.") from exc

            now = self._clock()
            if viewer is None or not viewer.visible_pages_ready:
                if unavailable_since is None:
                    unavailable_since = now
                if now - unavailable_since >= self._ready_timeout:
                    raise ChaoxingDocumentViewerReadyTimeoutError("Innerbook pages did not become ready.")
            elif viewer.at_bottom and not requires_marker:
                self._session.mark_handled(target.card_url, target.index, target.module_url, viewer)
                logger.info(
                    "Innerbook completed at loaded reader bottom: module_index=%d page_count=%d",
                    target.index,
                    viewer.page_count,
                )
                return
            elif viewer.at_bottom:
                unavailable_since = None
                if marker_since is None:
                    marker_since = now
                if now - marker_since >= self._ready_timeout:
                    raise ChaoxingDocumentViewerReadyTimeoutError(
                        "Innerbook platform completion was not confirmed."
                    )
            else:
                # Image loading has its own deadline; it is not mistaken for a scroll stall.
                if unavailable_since is not None or last_y is None or viewer.scroll_y > last_y + 0.5:
                    progress_at = now
                    last_y = viewer.scroll_y
                unavailable_since = None
                if now - progress_at >= self._progress_timeout:
                    raise ChaoxingDocumentProgressTimeoutError("Innerbook scrolling made no progress.")
                try:
                    self._browser.evaluate_in_frames(
                        build_innerbook_action_script(
                            target.module_path, viewer.path, max(1, round(viewer.height * 0.75))
                        )
                    )
                except BrowserError as exc:
                    raise ChaoxingDocumentInspectionError("Failed to scroll innerbook reader.") from exc
            self._sleep(
                self._interval
                if deadline is None
                else min(self._interval, max(0, deadline - self._clock()))
            )
        raise ChaoxingDocumentTimeoutError("Innerbook reading exceeded its bounded deadline.")
