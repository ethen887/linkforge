"""推进普通学习通课内内容，而无需猜测课程是否完成。"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, replace

from linkforge.application.task_runner import TaskHandler, TaskType
from linkforge.browser.base import Browser
from linkforge.browser.exceptions import BrowserError
from linkforge.platforms.chaoxing.dom import inspect_chaoxing_page
from linkforge.platforms.chaoxing.exceptions import (
    ChaoxingInspectionError,
    ContentNavigationError,
)
from linkforge.platforms.chaoxing.models import ChaoxingPageState
from linkforge.platforms.chaoxing.progress import course_resume_url
from linkforge.platforms.chaoxing.task_detector import ChaoxingTaskDetector

_NEXT_CARD_SELECTOR = "#prev_tab li.active + li"
_KNOWLEDGE_NODE_SELECTOR = '.posCatalog_select[id^="cur"]'
_KNOWLEDGE_TARGET_SELECTOR = ".posCatalog_name"

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ChaoxingContentHandlerConfig:
    """用于验证内容导航的有界等待参数。"""

    poll_interval_seconds: float = 0.25
    navigation_timeout_seconds: float = 15.0

    def __post_init__(self) -> None:
        if self.poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be greater than 0")

        if self.navigation_timeout_seconds <= 0:
            raise ValueError("navigation_timeout_seconds must be greater than 0")


@dataclass(frozen=True, slots=True)
class _NextKnowledgeTarget:
    frame_url: str
    node_id: str
    require_completed: bool = False


class ChaoxingContentTaskHandler(TaskHandler):
    """推进到下一个卡片，或按 DOM 顺序的下一个知识节点。"""

    def __init__(
        self,
        browser: Browser,
        *,
        detector: ChaoxingTaskDetector | None = None,
        config: ChaoxingContentHandlerConfig | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        on_course_url_changed: Callable[[str], None] | None = None,
    ) -> None:
        self._browser = browser
        self._detector = detector or ChaoxingTaskDetector(browser)
        self._config = config or ChaoxingContentHandlerConfig()
        self._sleep = sleep
        self._monotonic = monotonic
        self._skipped_knowledge_ids: set[str] = set()
        self._on_course_url_changed = on_course_url_changed

    def run(self) -> None:
        """推进一个 CONTENT 步骤，并将控制权交还给 TaskRunner。"""
        logger.info("Content handler started")
        try:
            self._run()
        except BaseException:
            logger.error("Content handler failed")
            raise
        logger.info("Content handler completed")

    def _run(self) -> None:
        """
        推进一个 CONTENT 步骤，并将控制权交还给 TaskRunner。

        初始快照提供了导航元数据以及明确的目录完成证据。一个已完成的
        知识节点只有在重新验证（包括最终点击动作内部）之后，才会跳过
        剩余的卡片。

        导航是否仍然安全，是通过 ChaoxingTaskDetector 单独判定的，
        这样 ContentHandler 与 TaskRunner 就共享完全相同的任务语义。

        这对普通 PDF 模块至关重要：

            PDF viewer at real bottom
                    ↓
            Detector = CONTENT
                    ↓
            ContentHandler may navigate

        而仍未阅读的 PDF、VIDEO、QUIZ、COMMENT 或未知状态仍会阻止
        CONTENT 导航。
        """
        initial_state = self._inspect_initial_state()

        self._assert_content_navigation_is_safe()

        if initial_state.knowledge_completed:
            fresh = self._inspect_initial_state()
            if fresh.knowledge_id != initial_state.knowledge_id or not fresh.knowledge_completed:
                raise ContentNavigationError("Catalog completion changed before navigation.")
            knowledge_id = fresh.knowledge_id
            if knowledge_id is None or knowledge_id in self._skipped_knowledge_ids:
                raise ContentNavigationError(
                    "Completed knowledge navigation repeated or lost its identity."
                )
            self._skipped_knowledge_ids.add(knowledge_id)
            logger.info("Skipping completed Chaoxing knowledge node")
            self._navigate_to_next_knowledge(fresh)
            return

        if initial_state.has_next_tab:
            self._navigate_to_next_card(initial_state)
            return

        self._navigate_to_next_knowledge(initial_state)

    def skip_failed_card(
        self, expected: ChaoxingPageState, *, should_stop: Callable[[], bool] | None = None
    ) -> bool:
        """明确保留当前卡片待补做，验证身份后推进；不修改平台完成状态。"""
        fresh = self._inspect_initial_state()
        if (
            fresh.content_frame_url != expected.content_frame_url
            or fresh.active_tab_index != expected.active_tab_index
            or tuple((m.url, m.frame_path) for m in fresh.modules)
            != tuple((m.url, m.frame_path) for m in expected.modules)
        ):
            raise ContentNavigationError("The failed card changed before recovery.")
        if should_stop is not None and should_stop():
            return False
        if fresh.has_next_tab:
            self._navigate_to_next_card(fresh)
        else:
            # 跳过是本次运行的显式恢复动作，不使用目录完成标记作为依据。
            self._navigate_to_next_knowledge(replace(fresh, knowledge_completed=False))
        return True

    def _inspect_initial_state(
        self,
    ) -> ChaoxingPageState:
        """读取当前卡片状态，用于确定性导航。"""
        try:
            return inspect_chaoxing_page(self._browser)

        except ChaoxingInspectionError as exc:
            raise ContentNavigationError("Unable to inspect the current Chaoxing content.") from exc

    def _assert_content_navigation_is_safe(
        self,
    ) -> None:
        """
        使用权威的 Chaoxing 检测器验证当前任务。

        TaskRunner 通常只在检测到 CONTENT 之后才调用此处理器。然而，
        在派发与处理器执行之间浏览器可能发生变化，因此处理器会在
        导航之前立即执行一次新的有界检测。

        检测器也是 Document V1 完成语义的权威来源。特别是，没有平台
        任务标记的 PDF，只有在真实阅读器到达底部之后才被视为已完成。
        """
        deadline = self._monotonic() + self._config.navigation_timeout_seconds

        while self._monotonic() < deadline:
            try:
                task_type = self._detector.detect()

            except ChaoxingInspectionError:
                task_type = TaskType.UNKNOWN

            if task_type is TaskType.CONTENT:
                return

            if task_type is not TaskType.UNKNOWN:
                raise ContentNavigationError(
                    "A pending Chaoxing module appeared before "
                    "CONTENT navigation could start: "
                    f"{task_type.name}."
                )

            remaining = deadline - self._monotonic()

            if remaining > 0:
                self._sleep(
                    min(
                        self._config.poll_interval_seconds,
                        remaining,
                    )
                )

        raise ContentNavigationError(
            "Unable to verify that the current Chaoxing card "
            "is safe for CONTENT navigation before the deadline."
        )

    def _navigate_to_next_card(
        self,
        initial_state: ChaoxingPageState,
    ) -> None:
        """点击下一个卡片，并验证当前激活的卡片发生变化。"""
        try:
            self._browser.click(_NEXT_CARD_SELECTOR)

        except BrowserError as exc:
            raise ContentNavigationError("Failed to click the next Chaoxing card tab.") from exc

        deadline = self._monotonic() + self._config.navigation_timeout_seconds

        while self._monotonic() < deadline:
            current_state = self._poll_page_state()

            if (
                current_state is not None
                and current_state.active_tab_index != initial_state.active_tab_index
                and current_state.knowledge_id == initial_state.knowledge_id
                and current_state.content_frame_url != initial_state.content_frame_url
            ):
                self._report_course_progress(current_state)
                return

        raise ContentNavigationError(
            "The Chaoxing active card did not change before the navigation deadline."
        )

    def _navigate_to_next_knowledge(
        self,
        initial_state: ChaoxingPageState,
    ) -> None:
        """从最后一个卡片推进到下一个知识节点。"""
        knowledge_id = initial_state.knowledge_id

        if knowledge_id is None:
            raise ContentNavigationError("The current Chaoxing content frame has no valid knowledgeId.")

        target = self._inspect_next_knowledge(knowledge_id)
        target = replace(target, require_completed=initial_state.knowledge_completed)

        self._click_next_knowledge(
            knowledge_id,
            target,
        )

        deadline = self._monotonic() + self._config.navigation_timeout_seconds

        while self._monotonic() < deadline:
            current_state = self._poll_page_state()

            if (
                current_state is not None
                and current_state.knowledge_id is not None
                and f"cur{current_state.knowledge_id}" == target.node_id
            ):
                self._report_course_progress(current_state)
                return

        raise ContentNavigationError(
            "The Chaoxing knowledgeId did not change before the navigation deadline."
        )

    def _report_course_progress(self, state: ChaoxingPageState) -> None:
        """仅发布经过验证的课程导航，且不记录路由相关的敏感信息。"""
        if self._on_course_url_changed is None:
            return
        try:
            url = course_resume_url(self._browser.current_url(), state)
            if url is not None:
                self._on_course_url_changed(url)
        except Exception:
            logger.warning("Course progress could not be reported; this run can continue.")

    def _poll_page_state(
        self,
    ) -> ChaoxingPageState | None:
        """
        在导航期间轮询当前卡片状态。

        在 Chaoxing 导航过程中会出现 iframe 替换，因此一次瞬时的
        检查失败不会立即终止处理器。调用方的有界导航截止时间仍然是
        权威依据。
        """
        self._sleep(self._config.poll_interval_seconds)

        try:
            return inspect_chaoxing_page(self._browser)

        except ChaoxingInspectionError:
            return None

    def _inspect_next_knowledge(
        self,
        knowledge_id: str,
    ) -> _NextKnowledgeTarget:
        """按真实 DOM 文档顺序找到下一个知识节点。"""
        try:
            results = self._browser.evaluate_in_frames(_inspect_next_knowledge_script(knowledge_id))

        except BrowserError as exc:
            raise ContentNavigationError("Failed to inspect the Chaoxing knowledge tree.") from exc

        result = _unique_current_knowledge_result(
            results,
            phase="inspection",
        )

        has_next = result.get("has_next")
        target_found = result.get("target_found")
        next_id = result.get("next_id")
        frame_url = result.get("frame_url")

        if not isinstance(
            has_next,
            bool,
        ) or not isinstance(
            target_found,
            bool,
        ):
            raise ContentNavigationError("Chaoxing knowledge-tree inspection was malformed.")

        if not has_next:
            raise ContentNavigationError(
                "No next Chaoxing knowledge node "
                "is available; whole-course "
                "completion is not yet evidenced."
            )

        if not target_found:
            raise ContentNavigationError(
                "The next Chaoxing knowledge node has no .posCatalog_name click target."
            )

        if (
            not isinstance(
                next_id,
                str,
            )
            or not next_id.strip()
            or not isinstance(
                frame_url,
                str,
            )
            or not frame_url.strip()
        ):
            raise ContentNavigationError("Chaoxing knowledge-tree inspection was malformed.")

        return _NextKnowledgeTarget(
            frame_url=frame_url,
            node_id=next_id,
        )

    def _click_next_knowledge(
        self,
        knowledge_id: str,
        target: _NextKnowledgeTarget,
    ) -> None:
        """点击之前已确认的下一个知识目标。"""
        try:
            results = self._browser.evaluate_in_frames(
                _click_next_knowledge_script(
                    knowledge_id,
                    target,
                )
            )

        except BrowserError as exc:
            raise ContentNavigationError("Failed to click the next Chaoxing knowledge node.") from exc

        result = _unique_current_knowledge_result(
            results,
            phase="click",
        )

        clicked = result.get("clicked")
        next_id = result.get("next_id")

        if (
            not isinstance(
                clicked,
                bool,
            )
            or next_id != target.node_id
        ):
            raise ContentNavigationError("Chaoxing knowledge-tree click result was malformed.")

        if not clicked:
            reason = result.get("reason")

            suffix = (
                f": {reason}"
                if (
                    isinstance(
                        reason,
                        str,
                    )
                    and reason
                )
                else ""
            )

            raise ContentNavigationError(f"The next Chaoxing knowledge node was not clicked{suffix}.")


def _unique_current_knowledge_result(
    results: tuple[object, ...],
    *,
    phase: str,
) -> dict[object, object]:
    """要求恰好有一个 frame 包含当前知识节点。"""
    matches: list[dict[object, object]] = []

    for result in results:
        if not isinstance(
            result,
            dict,
        ) or not isinstance(
            result.get("matched"),
            bool,
        ):
            raise ContentNavigationError(f"Chaoxing knowledge-tree {phase} result was malformed.")

        if result["matched"]:
            matches.append(result)

    if not matches:
        raise ContentNavigationError("The current Chaoxing knowledge node was not found.")

    if len(matches) != 1:
        raise ContentNavigationError("The current Chaoxing knowledge node is ambiguous across frames.")

    return matches[0]


def _inspect_next_knowledge_script(
    knowledge_id: str,
) -> str:
    """构建确定性的知识树检查脚本。"""
    current_id = json.dumps(f"cur{knowledge_id}")

    return f"""() => {{
        const frameUrl = window.location.href;
        const nodes = Array.from(
            document.querySelectorAll(
                {_js_string(_KNOWLEDGE_NODE_SELECTOR)}
            )
        );

        const currentIndex = nodes.findIndex(
            node => node.id === {current_id}
        );

        if (currentIndex < 0) {{
            return {{
                frame_url: frameUrl,
                matched: false
            }};
        }}

        const next =
            nodes[currentIndex + 1] || null;

        const target =
            next
                ? next.querySelector(
                    {_js_string(_KNOWLEDGE_TARGET_SELECTOR)}
                )
                : null;

        return {{
            frame_url: frameUrl,
            matched: true,
            has_next: next !== null,
            target_found: target !== null,
            next_id: next ? next.id : null,
        }};
    }}"""


def _click_next_knowledge_script(
    knowledge_id: str,
    target: _NextKnowledgeTarget,
) -> str:
    """构建确定性的真实 DOM 点击脚本。"""
    current_id = json.dumps(f"cur{knowledge_id}")

    frame_url = _js_string(target.frame_url)

    expected_next_id = _js_string(target.node_id)
    require_completed = json.dumps(target.require_completed)

    return f"""() => {{
        const currentFrameUrl =
            window.location.href;

        if (
            currentFrameUrl !== {frame_url}
        ) {{
            return {{
                frame_url: currentFrameUrl,
                matched: false
            }};
        }}

        const nodes = Array.from(
            document.querySelectorAll(
                {_js_string(_KNOWLEDGE_NODE_SELECTOR)}
            )
        );

        const currentIndex = nodes.findIndex(
            node => node.id === {current_id}
        );

        if (currentIndex < 0) {{
            return {{
                frame_url: currentFrameUrl,
                matched: false
            }};
        }}

        const next =
            nodes[currentIndex + 1] || null;

        const target =
            next
                ? next.querySelector(
                    {_js_string(_KNOWLEDGE_TARGET_SELECTOR)}
                )
                : null;

        if (
            !next
            || next.id !== {expected_next_id}
            || !target
            || nodes.filter(node => node.id === {current_id}).length !== 1
            || nodes.filter(node => node.id === {expected_next_id}).length !== 1
            || ({require_completed} && (
                nodes.filter(node => node.classList.contains("posCatalog_active")).length !== 1
                || !nodes[currentIndex].classList.contains("posCatalog_active")
                || nodes[currentIndex].querySelectorAll(":scope > .icon_Completed").length !== 1
                || !Array.from(nodes[currentIndex].querySelectorAll(":scope > .icon_Completed"))
                    .every(marker => marker.getClientRects().length > 0
                        && getComputedStyle(marker).visibility !== "hidden")
                || nodes[currentIndex].querySelectorAll(":scope > .catalog_points_yi").length !== 0
            ))
        ) {{
            return {{
                frame_url: currentFrameUrl,
                matched: true,
                clicked: false,
                next_id:
                    next ? next.id : null,
                reason:
                    "knowledge-tree-changed",
            }};
        }}

        target.click();

        return {{
            frame_url: currentFrameUrl,
            matched: true,
            clicked: true,
            next_id: next.id,
            reason: null,
        }};
    }}"""


def _js_string(
    value: str,
) -> str:
    """安全地将 Python 字符串序列化，以便嵌入到 JavaScript 中。"""
    return json.dumps(value)
