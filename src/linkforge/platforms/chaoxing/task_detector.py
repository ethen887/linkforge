"""Deterministic task detection for Chaoxing course cards."""

from linkforge.application.task_runner import TaskDetector, TaskType
from linkforge.browser.base import Browser
from linkforge.browser.exceptions import BrowserError
from linkforge.platforms.chaoxing.document_inspection import (
    document_viewer_is_ready,
    parse_document_inspection,
    parse_module_basics,
)
from linkforge.platforms.chaoxing.dom import CHAOXING_CARD_STATE_SCRIPT
from linkforge.platforms.chaoxing.models import ChaoxingDocumentModuleState

_PDF_MODULE_PATH = "/ananas/modules/pdf/"
_MODULE_TASK_TYPES = {
    "/ananas/modules/video/": TaskType.VIDEO,
    _PDF_MODULE_PATH: TaskType.DOCUMENT,
    "/ananas/modules/work/": TaskType.QUIZ,
    "/ananas/modules/insertbbs/": TaskType.COMMENT,
}


class ChaoxingTaskDetector(TaskDetector):
    """Detect the first pending module in the current Chaoxing content frame."""

    def __init__(self, browser: Browser) -> None:
        self._browser = browser

    def detect(self) -> TaskType:
        """Return a deterministic task type from the current Chaoxing card."""
        try:
            frame_results = self._browser.evaluate_in_frames(CHAOXING_CARD_STATE_SCRIPT)
            inspection = parse_document_inspection(frame_results)
            if inspection is None:
                return TaskType.UNKNOWN

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
                    if (
                        viewer is not None
                        and document_viewer_is_ready(document, viewer)
                        and viewer.at_bottom
                    ):
                        continue
                    return TaskType.DOCUMENT

                if has_job_icon and finished:
                    continue
                return self._classify_module(module_url)
        except (BrowserError, ValueError):
            return TaskType.UNKNOWN

        return TaskType.CONTENT

    @staticmethod
    def _classify_module(module_url: str) -> TaskType:
        for module_path, task_type in _MODULE_TASK_TYPES.items():
            if module_path in module_url:
                return task_type
        return TaskType.UNKNOWN
