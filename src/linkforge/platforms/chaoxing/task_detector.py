"""Deterministic task detection for Chaoxing course cards."""

from linkforge.application.task_runner import TaskDetector, TaskType
from linkforge.browser.base import Browser
from linkforge.platforms.chaoxing.dom import first_pending_module, inspect_chaoxing_page
from linkforge.platforms.chaoxing.exceptions import ChaoxingInspectionError

_MODULE_TASK_TYPES = {
    "/ananas/modules/video/": TaskType.VIDEO,
    "/ananas/modules/pdf/": TaskType.DOCUMENT,
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
            state = inspect_chaoxing_page(self._browser)
        except ChaoxingInspectionError:
            return TaskType.UNKNOWN

        module = first_pending_module(state)
        return TaskType.CONTENT if module is None else self._classify_module(module.url)

    @staticmethod
    def _classify_module(module_url: str) -> TaskType:
        for module_path, task_type in _MODULE_TASK_TYPES.items():
            if module_path in module_url:
                return task_type

        return TaskType.UNKNOWN
