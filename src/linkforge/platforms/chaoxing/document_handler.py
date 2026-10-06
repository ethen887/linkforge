"""Deterministic continuous-scroll handling for Chaoxing PDF and innerbook modules."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import replace
from urllib.parse import urljoin

from linkforge.application.task_runner import TaskHandler
from linkforge.browser.base import Browser
from linkforge.browser.exceptions import BrowserError
from linkforge.platforms.chaoxing.document_inspection import (
    ChaoxingDocumentInspection,
    document_viewer_is_ready,
    inspect_innerbook_viewers,
    parse_document_inspection,
    parse_module_basics,
)
from linkforge.platforms.chaoxing.dom import (
    CHAOXING_CARD_STATE_SCRIPT,
    build_document_scroll_script,
    inspect_chaoxing_page,
)
from linkforge.platforms.chaoxing.exceptions import (
    ChaoxingDocumentInspectionError,
    ChaoxingDocumentNotFoundError,
    ChaoxingDocumentProgressTimeoutError,
    ChaoxingDocumentStateError,
    ChaoxingDocumentTimeoutError,
    ChaoxingDocumentViewerReadyTimeoutError,
    ChaoxingInspectionError,
)
from linkforge.platforms.chaoxing.innerbook import (
    InnerbookSession,
    InnerbookTarget,
    find_innerbook_viewer,
    frame_path,
    is_innerbook,
)
from linkforge.platforms.chaoxing.innerbook_handler import ChaoxingInnerbookReader
from linkforge.platforms.chaoxing.models import ChaoxingDocumentModuleState
from linkforge.platforms.chaoxing.video_state import VideoSession

_PDF_MODULE_PATH = "/ananas/modules/pdf/"
_MIN_PROGRESS_PX = 0.5

logger = logging.getLogger(__name__)


class ChaoxingDocumentTaskHandler(TaskHandler):
    """Handle one pending document, then return to the runner."""

    def __init__(
        self,
        browser: Browser,
        *,
        innerbook_session: InnerbookSession | None = None,
        video_session: VideoSession | None = None,
        viewer_ready_timeout_seconds: float = 10.0,
        timeout_seconds: float | None = None,
        innerbook_timeout_seconds: float | None = None,
        progress_timeout_seconds: float = 5.0,
        poll_interval_seconds: float = 0.1,
        scroll_viewport_fraction: float = 0.75,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        timings = {
            "viewer_ready_timeout_seconds": viewer_ready_timeout_seconds,
            "timeout_seconds": timeout_seconds,
            "innerbook_timeout_seconds": innerbook_timeout_seconds,
            "progress_timeout_seconds": progress_timeout_seconds,
            "poll_interval_seconds": poll_interval_seconds,
            "scroll_viewport_fraction": scroll_viewport_fraction,
        }
        for name, value in timings.items():
            if value is None:
                continue
            if value <= 0:
                raise ValueError(f"{name} must be greater than 0")

        self._browser = browser
        self._innerbook_session = innerbook_session or InnerbookSession()
        self._video_session = video_session
        self._viewer_ready_timeout_seconds = viewer_ready_timeout_seconds
        self._timeout_seconds = timeout_seconds
        self._innerbook_timeout_seconds = innerbook_timeout_seconds
        self._progress_timeout_seconds = progress_timeout_seconds
        self._poll_interval_seconds = poll_interval_seconds
        self._scroll_viewport_fraction = scroll_viewport_fraction
        self._clock = clock
        self._sleeper = sleeper

    def run(self) -> None:
        """Process exactly one document with its supported viewer contract."""
        logger.info("Document handler started")
        try:
            self._run()
        except BaseException:
            logger.exception("Document handler failed")
            raise
        logger.info("Document handler completed")

    def _run(self) -> None:
        started_at = self._clock()
        deadline = started_at + self._timeout_seconds if self._timeout_seconds is not None else None
        inspection = self._inspect()
        if inspection is None:
            raise ChaoxingDocumentStateError(
                "Exactly one active tab and one Chaoxing content frame are required."
            )

        try:
            target = self._find_first_pending_document(inspection)
        except ValueError as exc:
            raise ChaoxingDocumentStateError(f"Malformed Chaoxing document state: {exc}") from exc
        if target is None:
            raise ChaoxingDocumentNotFoundError("No pending Chaoxing PDF is present in the active card.")

        if isinstance(target, InnerbookTarget):
            ChaoxingInnerbookReader(
                self._browser,
                self._innerbook_session,
                timeout_seconds=self._innerbook_timeout_seconds,
                ready_timeout_seconds=self._viewer_ready_timeout_seconds,
                progress_timeout_seconds=self._progress_timeout_seconds,
                poll_interval_seconds=self._poll_interval_seconds,
                clock=self._clock,
                sleeper=self._sleeper,
            ).read(target)
            return

        object_id = target.object_id
        missing_since: float | None = self._clock()
        last_scroll_y: float | None = None
        last_progress_at = self._clock()

        while True:
            now = self._clock()
            if deadline is not None and now >= deadline:
                raise ChaoxingDocumentTimeoutError(
                    f"PDF object_id={object_id!r} did not reach the viewer bottom within "
                    f"{self._timeout_seconds:g} seconds."
                )

            try:
                current_module = self._find_document_by_object_id(inspection, object_id)
            except ValueError as exc:
                raise ChaoxingDocumentStateError(f"Malformed Chaoxing document state: {exc}") from exc
            viewer = inspection.viewers.get(object_id) if inspection is not None else None

            if current_module is not None and current_module.has_job_icon and current_module.finished:
                return

            if (
                current_module is None
                or viewer is None
                or not document_viewer_is_ready(current_module, viewer)
            ):
                if missing_since is None:
                    missing_since = now
                if now - missing_since >= self._viewer_ready_timeout_seconds:
                    raise ChaoxingDocumentViewerReadyTimeoutError(
                        f"PDF viewer object_id={object_id!r} was not ready within "
                        f"{self._viewer_ready_timeout_seconds:g} seconds."
                    )
                self._sleep_until_next_poll(deadline)
                inspection = self._inspect()
                continue

            if missing_since is not None:
                missing_since = None
                last_progress_at = now
                last_scroll_y = viewer.scroll_y

            if viewer.at_bottom:
                return

            if last_scroll_y is None or viewer.scroll_y > last_scroll_y + _MIN_PROGRESS_PX:
                last_scroll_y = viewer.scroll_y
                last_progress_at = now
            elif now - last_progress_at >= self._progress_timeout_seconds:
                raise ChaoxingDocumentProgressTimeoutError(
                    f"PDF viewer object_id={object_id!r} remained at scroll_y={viewer.scroll_y:g} "
                    f"for {self._progress_timeout_seconds:g} seconds."
                )

            delta_y = max(1, round(viewer.inner_height * self._scroll_viewport_fraction))
            self._scroll_viewer(object_id, delta_y)
            self._sleep_until_next_poll(deadline)
            inspection = self._inspect()

    def _inspect(self) -> ChaoxingDocumentInspection | None:
        try:
            frame_results = self._browser.evaluate_in_frames(CHAOXING_CARD_STATE_SCRIPT)
            inspection = parse_document_inspection(frame_results)
            if inspection is not None and self._video_session is not None:
                state = inspect_chaoxing_page(self._browser)
                if state.content_frame_url != inspection.content_frame_url or len(state.modules) != len(
                    inspection.modules
                ):
                    raise ChaoxingDocumentStateError("The card changed between document observations.")
                handled = set()
                for index, module in enumerate(inspection.modules):
                    url, _, _ = parse_module_basics(module)
                    if state.modules[index].url != urljoin(state.content_frame_url, url):
                        raise ChaoxingDocumentStateError(
                            "The module changed between document observations."
                        )
                    if "/ananas/modules/video/" in url and self._video_session.is_handled(state, index):
                        handled.add(index)
                inspection = replace(inspection, handled_video_indices=frozenset(handled))
            return inspect_innerbook_viewers(self._browser, inspection) if inspection is not None else None
        except ChaoxingInspectionError as exc:
            raise ChaoxingDocumentInspectionError(
                "Failed to verify handled videos before document selection."
            ) from exc
        except BrowserError as exc:
            raise ChaoxingDocumentInspectionError("Failed to inspect Chaoxing document state.") from exc
        except ValueError as exc:
            raise ChaoxingDocumentStateError(f"Malformed Chaoxing document state: {exc}") from exc

    def _scroll_viewer(self, object_id: str, delta_y: int) -> None:
        try:
            self._browser.evaluate_in_frames(build_document_scroll_script(object_id, delta_y))
        except BrowserError as exc:
            raise ChaoxingDocumentInspectionError(
                f"Failed to scroll Chaoxing PDF viewer object_id={object_id!r}."
            ) from exc

    def _sleep_until_next_poll(self, deadline: float | None) -> None:
        if deadline is None:
            self._sleeper(self._poll_interval_seconds)
            return
        remaining = deadline - self._clock()
        if remaining > 0:
            self._sleeper(min(self._poll_interval_seconds, remaining))

    def _find_first_pending_document(
        self,
        inspection: ChaoxingDocumentInspection,
    ) -> ChaoxingDocumentModuleState | InnerbookTarget | None:
        for module_index, raw_module in enumerate(inspection.modules):
            module_url, has_job_icon, finished = parse_module_basics(raw_module)
            if module_index in inspection.handled_video_indices:
                continue
            if is_innerbook(module_url):
                if has_job_icon and finished:
                    continue
                book_viewer = find_innerbook_viewer(raw_module, inspection.innerbook_viewers)
                if not has_job_icon and self._innerbook_session.is_handled(
                    inspection.content_frame_url, module_index, module_url, book_viewer
                ):
                    continue
                return InnerbookTarget(
                    inspection.content_frame_url,
                    module_index,
                    module_url,
                    frame_path(raw_module.get("frame_path")),
                )
            if _PDF_MODULE_PATH in module_url:
                document = ChaoxingDocumentModuleState.from_raw(
                    raw_module,
                    module_index=module_index,
                )
                if document.has_job_icon and document.finished:
                    continue
                viewer = inspection.viewers.get(document.object_id)
                if viewer is not None and document_viewer_is_ready(document, viewer) and viewer.at_bottom:
                    continue
                return document

            if has_job_icon and finished:
                continue
            return None
        return None

    @staticmethod
    def _find_document_by_object_id(
        inspection: ChaoxingDocumentInspection | None,
        object_id: str,
    ) -> ChaoxingDocumentModuleState | None:
        if inspection is None:
            return None
        for module_index, raw_module in enumerate(inspection.modules):
            module_url, _, _ = parse_module_basics(raw_module)
            if _PDF_MODULE_PATH not in module_url:
                continue
            document = ChaoxingDocumentModuleState.from_raw(
                raw_module,
                module_index=module_index,
            )
            if document.object_id == object_id:
                return document
        return None
