"""Deterministic task detection for Chaoxing course cards."""

from urllib.parse import urljoin

from linkforge.application.task_runner import TaskDetector, TaskType
from linkforge.browser.base import Browser
from linkforge.browser.exceptions import BrowserError
from linkforge.platforms.chaoxing.comment_state import (
    COMMENT_MODULE_PATH,
    CommentIdentityError,
    CommentSession,
    comment_identity,
)
from linkforge.platforms.chaoxing.document_inspection import (
    document_viewer_is_ready,
    parse_document_inspection,
    parse_module_basics,
)
from linkforge.platforms.chaoxing.dom import CHAOXING_CARD_STATE_SCRIPT, inspect_chaoxing_page
from linkforge.platforms.chaoxing.exceptions import ChaoxingInspectionError
from linkforge.platforms.chaoxing.models import ChaoxingDocumentModuleState
from linkforge.platforms.chaoxing.video_state import VideoSession

_PDF_MODULE_PATH = "/ananas/modules/pdf/"

_MODULE_TASK_TYPES = {
    "/ananas/modules/video/": TaskType.VIDEO,
    _PDF_MODULE_PATH: TaskType.DOCUMENT,
    "/ananas/modules/work/": TaskType.QUIZ,
    "/ananas/modules/insertbbs/": TaskType.COMMENT,
}


class ChaoxingTaskDetector(TaskDetector):
    """Detect the first pending module in the current Chaoxing content frame."""

    def __init__(
        self,
        browser: Browser,
        *,
        comment_session: CommentSession | None = None,
        video_session: VideoSession | None = None,
    ) -> None:
        self._browser = browser
        self._comment_session = comment_session
        self._video_session = video_session

    def detect(self) -> TaskType:
        """Return a deterministic task type from the current Chaoxing card."""
        try:
            frame_results = self._browser.evaluate_in_frames(CHAOXING_CARD_STATE_SCRIPT)

            inspection = parse_document_inspection(frame_results)

            if inspection is None:
                return TaskType.UNKNOWN

            for module_index, raw_module in enumerate(inspection.modules):
                module_url, has_job_icon, finished = parse_module_basics(raw_module)

                # PDF / Document uses LinkForge's real viewer state in
                # addition to Chaoxing's task-point marker.
                if _PDF_MODULE_PATH in module_url:
                    document = ChaoxingDocumentModuleState.from_raw(
                        raw_module,
                        module_index=module_index,
                    )

                    # A Chaoxing task-point PDF explicitly marked finished
                    # does not need to be processed again.
                    if document.has_job_icon and document.finished:
                        continue

                    viewer = inspection.viewers.get(document.object_id)

                    # A real viewer that has loaded completely and already
                    # reached the bottom is considered handled by LinkForge.
                    if (
                        viewer is not None
                        and document_viewer_is_ready(document, viewer)
                        and viewer.at_bottom
                    ):
                        continue

                    # Missing/not-ready viewers deliberately remain DOCUMENT.
                    # The handler owns the bounded viewer-readiness wait.
                    return TaskType.DOCUMENT

                # Non-document task points continue to use Chaoxing's
                # finished marker.
                if has_job_icon and finished:
                    continue

                if "/ananas/modules/video/" in module_url and self._video_session is not None:
                    state = inspect_chaoxing_page(self._browser)
                    if module_index >= len(state.modules):
                        return TaskType.UNKNOWN
                    # The card may change between the two frame observations.
                    if state.modules[module_index].url != urljoin(state.content_frame_url, module_url):
                        return TaskType.UNKNOWN
                    if self._video_session.is_handled(state, module_index):
                        continue

                if COMMENT_MODULE_PATH in module_url and self._comment_session is not None:
                    state = inspect_chaoxing_page(self._browser)
                    if module_index >= len(state.modules) or state.modules[module_index].url != module_url:
                        return TaskType.UNKNOWN
                    identity = comment_identity(self._browser.current_url(), state, module_index)
                    if self._comment_session.is_handled(identity):
                        continue

                return self._classify_module(module_url)

        except (BrowserError, ChaoxingInspectionError, CommentIdentityError, ValueError):
            return TaskType.UNKNOWN

        # No remaining pending module in the current Card.
        return TaskType.CONTENT

    @staticmethod
    def _classify_module(module_url: str) -> TaskType:
        """Map one Chaoxing module URL to its provider-neutral task type."""
        for module_path, task_type in _MODULE_TASK_TYPES.items():
            if module_path in module_url:
                return task_type

        return TaskType.UNKNOWN
