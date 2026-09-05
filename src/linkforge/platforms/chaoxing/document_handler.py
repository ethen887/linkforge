"""Deterministic continuous-scroll handling for Chaoxing PDF modules."""

from __future__ import annotations

import time
from collections.abc import Callable

from linkforge.application.task_runner import TaskHandler
from linkforge.browser.base import Browser
from linkforge.browser.exceptions import BrowserError
from linkforge.platforms.chaoxing.document_inspection import (
    ChaoxingDocumentInspection,
    document_viewer_is_ready,
    parse_document_inspection,
    parse_module_basics,
)
from linkforge.platforms.chaoxing.dom import (
    CHAOXING_CARD_STATE_SCRIPT,
    build_document_scroll_script,
)
from linkforge.platforms.chaoxing.exceptions import (
    ChaoxingDocumentInspectionError,
    ChaoxingDocumentNotFoundError,
    ChaoxingDocumentProgressTimeoutError,
    ChaoxingDocumentStateError,
    ChaoxingDocumentTimeoutError,
    ChaoxingDocumentViewerReadyTimeoutError,
)
from linkforge.platforms.chaoxing.models import ChaoxingDocumentModuleState

_PDF_MODULE_PATH = "/ananas/modules/pdf/"
_MIN_PROGRESS_PX = 0.5


class ChaoxingDocumentTaskHandler(TaskHandler):
    """Scroll one pending PDF viewer to its real bottom, then return to the runner."""

    def __init__(
        self,
        browser: Browser,
        *,
        viewer_ready_timeout_seconds: float = 10.0,
        timeout_seconds: float = 60.0,
        progress_timeout_seconds: float = 5.0,
        poll_interval_seconds: float = 0.1,
        scroll_viewport_fraction: float = 0.75,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        timings = {
            "viewer_ready_timeout_seconds": viewer_ready_timeout_seconds,
            "timeout_seconds": timeout_seconds,
            "progress_timeout_seconds": progress_timeout_seconds,
            "poll_interval_seconds": poll_interval_seconds,
            "scroll_viewport_fraction": scroll_viewport_fraction,
        }
        for name, value in timings.items():
            if value <= 0:
                raise ValueError(f"{name} must be greater than 0")

        self._browser = browser
        self._viewer_ready_timeout_seconds = viewer_ready_timeout_seconds
        self._timeout_seconds = timeout_seconds
        self._progress_timeout_seconds = progress_timeout_seconds
        self._poll_interval_seconds = poll_interval_seconds
        self._scroll_viewport_fraction = scroll_viewport_fraction
        self._clock = clock
        self._sleeper = sleeper

    def run(self) -> None:
        """Scroll exactly one PDF from its current position until ``at_bottom``."""
        started_at = self._clock()
        deadline = started_at + self._timeout_seconds
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

        object_id = target.object_id
        missing_since: float | None = self._clock()
        last_scroll_y: float | None = None
        last_progress_at = self._clock()

        while True:
            now = self._clock()
            if now >= deadline:
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
            return parse_document_inspection(frame_results)
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

    def _sleep_until_next_poll(self, deadline: float) -> None:
        remaining = deadline - self._clock()
        if remaining > 0:
            self._sleeper(min(self._poll_interval_seconds, remaining))

    @staticmethod
    def _find_first_pending_document(
        inspection: ChaoxingDocumentInspection,
    ) -> ChaoxingDocumentModuleState | None:
        for module_index, raw_module in enumerate(inspection.modules):
            module_url, has_job_icon, finished = parse_module_basics(raw_module)
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
