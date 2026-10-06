"""Deterministic task detection for Chaoxing course cards."""

import logging
from urllib.parse import urljoin, urlsplit

from linkforge.application.task_runner import TaskDetector, TaskType
from linkforge.browser.base import Browser
from linkforge.browser.exceptions import BrowserError
from linkforge.platforms.chaoxing.catalog import knowledge_is_completed
from linkforge.platforms.chaoxing.comment_state import (
    COMMENT_MODULE_PATH,
    CommentIdentityError,
    CommentSession,
    comment_identity,
)
from linkforge.platforms.chaoxing.document_inspection import (
    document_viewer_is_ready,
    inspect_innerbook_viewers,
    parse_document_inspection,
    parse_module_basics,
)
from linkforge.platforms.chaoxing.dom import CHAOXING_CARD_STATE_SCRIPT, inspect_chaoxing_page
from linkforge.platforms.chaoxing.exceptions import ChaoxingInspectionError
from linkforge.platforms.chaoxing.innerbook import InnerbookSession, find_innerbook_viewer, is_innerbook
from linkforge.platforms.chaoxing.models import ChaoxingDocumentModuleState
from linkforge.platforms.chaoxing.video_state import VideoSession

_PDF_MODULE_PATH = "/ananas/modules/pdf/"

logger = logging.getLogger(__name__)

_MODULE_TASK_TYPES = {
    "/ananas/modules/video/": TaskType.VIDEO,
    _PDF_MODULE_PATH: TaskType.DOCUMENT,
    "/ananas/modules/work/": TaskType.QUIZ,
    "/ananas/modules/insertbbs/": TaskType.COMMENT,
}

# Diagnostic vocabulary only; inclusion does not make a module supported.
_DIAGNOSTIC_MODULE_KINDS = frozenset(
    {"video", "pdf", "work", "insertbbs", "audio", "ppt", "read", "flash", "img", "book", "innerbook"}
)


def _diagnostic_module_kind(module_url: str) -> str:
    """Return an allowlisted route label without logging arbitrary URL data."""
    path = urlsplit(module_url).path
    _, separator, suffix = path.partition("/ananas/modules/")
    if not separator:
        return "unrecognized_route"
    kind = suffix.partition("/")[0]
    return kind if kind in _DIAGNOSTIC_MODULE_KINDS else "unrecognized_kind"


class ChaoxingTaskDetector(TaskDetector):
    """Detect the first pending module in the current Chaoxing content frame."""

    def __init__(
        self,
        browser: Browser,
        *,
        comment_session: CommentSession | None = None,
        video_session: VideoSession | None = None,
        innerbook_session: InnerbookSession | None = None,
    ) -> None:
        self._browser = browser
        self._comment_session = comment_session
        self._video_session = video_session
        self._innerbook_session = innerbook_session or InnerbookSession()

    def detect(self) -> TaskType:
        """Return a deterministic task type from the current Chaoxing card."""
        stage = "frame_evaluation"
        module_index: int | None = None
        try:
            frame_results = self._browser.evaluate_in_frames(CHAOXING_CARD_STATE_SCRIPT)

            stage = "card_parsing"
            inspection = parse_document_inspection(frame_results)

            if inspection is None:
                return self._unknown("course_state_unavailable", stage=stage)

            stage = "catalog_completion"
            if knowledge_is_completed(frame_results, inspection.content_frame_url):
                logger.debug("Chaoxing completed knowledge: source=catalog_check; advancing to next node")
                return TaskType.CONTENT

            book_inspected = False
            for module_index, raw_module in enumerate(inspection.modules):
                stage = "module_parsing"
                module_url, has_job_icon, finished = parse_module_basics(raw_module)

                # PDF / Document uses LinkForge's real viewer state in
                # addition to Chaoxing's task-point marker.
                if _PDF_MODULE_PATH in module_url:
                    stage = "document_parsing"
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

                if is_innerbook(module_url):
                    stage = "innerbook_inspection"
                    if not book_inspected:
                        inspection = inspect_innerbook_viewers(self._browser, inspection)
                        book_inspected = True
                    book_viewer = find_innerbook_viewer(raw_module, inspection.innerbook_viewers)
                    if not has_job_icon and self._innerbook_session.is_handled(
                        inspection.content_frame_url, module_index, module_url, book_viewer
                    ):
                        continue
                    # A known book is a document; its handler owns readiness and completion checks.
                    return TaskType.DOCUMENT

                if "/ananas/modules/video/" in module_url and self._video_session is not None:
                    stage = "video_session_inspection"
                    state = inspect_chaoxing_page(self._browser)
                    if module_index >= len(state.modules):
                        return self._unknown("module_missing_between_observations", stage, module_index)
                    # The card may change between the two frame observations.
                    if state.modules[module_index].url != urljoin(state.content_frame_url, module_url):
                        return self._unknown("module_changed_between_observations", stage, module_index)
                    if self._video_session.is_handled(state, module_index):
                        continue

                if COMMENT_MODULE_PATH in module_url and self._comment_session is not None:
                    stage = "comment_session_inspection"
                    state = inspect_chaoxing_page(self._browser)
                    if module_index >= len(state.modules) or state.modules[module_index].url != module_url:
                        return self._unknown("module_changed_between_observations", stage, module_index)
                    stage = "comment_identity"
                    identity = comment_identity(self._browser.current_url(), state, module_index)
                    if self._comment_session.is_handled(identity):
                        continue

                task_type = self._classify_module(module_url)
                if task_type is TaskType.UNKNOWN:
                    logger.debug(
                        "Chaoxing unsupported module: module_kind=%s module_index=%d "
                        "module_count=%d has_job_icon=%s finished=%s",
                        _diagnostic_module_kind(module_url),
                        module_index,
                        len(inspection.modules),
                        has_job_icon,
                        finished,
                    )
                    return self._unknown("unsupported_module_type", "module_classification", module_index)
                return task_type

        except BrowserError:
            return self._unknown("dom_inspection_failed", stage, module_index)
        except ChaoxingInspectionError:
            return self._unknown("page_state_inspection_failed", stage, module_index)
        except CommentIdentityError:
            return self._unknown("comment_identity_unavailable", stage, module_index)
        except ValueError:
            return self._unknown("malformed_state", stage, module_index)

        # No remaining pending module in the current Card.
        return TaskType.CONTENT

    @staticmethod
    def _unknown(reason: str, stage: str, module_index: int | None = None) -> TaskType:
        """Log only controlled labels and counts, never raw DOM or exception text."""
        logger.debug(
            "Chaoxing UNKNOWN: reason=%s stage=%s module_index=%s",
            reason,
            stage,
            module_index,
        )
        return TaskType.UNKNOWN

    @staticmethod
    def _classify_module(module_url: str) -> TaskType:
        """Map one Chaoxing module URL to its provider-neutral task type."""
        for module_path, task_type in _MODULE_TASK_TYPES.items():
            if module_path in module_url:
                return task_type

        return TaskType.UNKNOWN
