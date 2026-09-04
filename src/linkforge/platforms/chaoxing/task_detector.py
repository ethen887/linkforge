"""Deterministic task detection for Chaoxing course cards."""

from typing import Any

from linkforge.application.task_runner import TaskDetector, TaskType
from linkforge.browser.base import Browser
from linkforge.browser.exceptions import BrowserError

_CHAOXING_STATE_SCRIPT = """() => {
    const frameUrl = window.location.href;
    const activeTabCount = document.querySelectorAll("#prev_tab li.active").length;
    const modules = [];

    if (frameUrl.includes("/mooc-ans/knowledge/cards")) {
        const moduleFrames = document.querySelectorAll('iframe[src*="/ananas/modules/"]');
        for (const moduleFrame of moduleFrames) {
            const container = moduleFrame.closest(".ans-attach-ct");
            const hasJobIcon = container
                ? container.querySelector(".ans-job-icon") !== null
                : false;

            modules.push({
                module_url: moduleFrame.getAttribute("src"),
                has_job_icon: hasJobIcon,
                finished: hasJobIcon && container.classList.contains("ans-job-finished"),
            });
        }
    }

    return {
        frame_url: frameUrl,
        active_tab_count: activeTabCount,
        modules,
    };
}"""

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
            frame_results = self._browser.evaluate_in_frames(_CHAOXING_STATE_SCRIPT)
        except BrowserError:
            return TaskType.UNKNOWN

        content_frame = self._find_current_content_frame(frame_results)
        if content_frame is None:
            return TaskType.UNKNOWN

        modules = content_frame.get("modules")
        if not isinstance(modules, list):
            return TaskType.UNKNOWN

        for module in modules:
            if not isinstance(module, dict):
                return TaskType.UNKNOWN

            module_url = module.get("module_url")
            has_job_icon = module.get("has_job_icon")
            finished = module.get("finished")
            if (
                not isinstance(module_url, str)
                or not isinstance(has_job_icon, bool)
                or not isinstance(finished, bool)
            ):
                return TaskType.UNKNOWN

            if has_job_icon and finished:
                continue

            return self._classify_module(module_url)

        return TaskType.CONTENT

    @staticmethod
    def _find_current_content_frame(frame_results: tuple[object, ...]) -> dict[str, Any] | None:
        active_tab_count = 0
        content_frames: list[dict[str, Any]] = []

        for result in frame_results:
            if not isinstance(result, dict):
                return None

            frame_url = result.get("frame_url")
            frame_active_tab_count = result.get("active_tab_count")
            if (
                not isinstance(frame_url, str)
                or not isinstance(frame_active_tab_count, int)
                or isinstance(frame_active_tab_count, bool)
                or frame_active_tab_count < 0
            ):
                return None

            active_tab_count += frame_active_tab_count

            if "/mooc-ans/knowledge/cards" in frame_url:
                content_frames.append(result)

        if active_tab_count != 1 or len(content_frames) != 1:
            return None

        return content_frames[0]

    @staticmethod
    def _classify_module(module_url: str) -> TaskType:
        for module_path, task_type in _MODULE_TASK_TYPES.items():
            if module_path in module_url:
                return task_type

        return TaskType.UNKNOWN
