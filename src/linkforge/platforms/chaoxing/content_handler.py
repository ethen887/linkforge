"""Advance ordinary Chaoxing content without guessing course completion."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass

from linkforge.application.task_runner import TaskHandler, TaskType
from linkforge.browser.base import Browser
from linkforge.browser.exceptions import BrowserError
from linkforge.platforms.chaoxing.dom import inspect_chaoxing_page
from linkforge.platforms.chaoxing.exceptions import (
    ChaoxingInspectionError,
    ContentNavigationError,
)
from linkforge.platforms.chaoxing.models import ChaoxingPageState
from linkforge.platforms.chaoxing.task_detector import ChaoxingTaskDetector

_NEXT_CARD_SELECTOR = "#prev_tab li.active + li"
_KNOWLEDGE_NODE_SELECTOR = '.posCatalog_select[id^="cur"]'
_KNOWLEDGE_TARGET_SELECTOR = ".posCatalog_name"


@dataclass(frozen=True, slots=True)
class ChaoxingContentHandlerConfig:
    """Bounded wait used to verify a content navigation."""

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


class ChaoxingContentTaskHandler(TaskHandler):
    """Advance to the next card, or the next knowledge node in DOM order."""

    def __init__(
        self,
        browser: Browser,
        *,
        config: ChaoxingContentHandlerConfig | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._browser = browser
        self._config = config or ChaoxingContentHandlerConfig()
        self._sleep = sleep
        self._monotonic = monotonic

    def run(self) -> None:
        """
        Navigate one CONTENT step and return control to TaskRunner.

        The initial page snapshot is used only for navigation metadata such as
        the active card index and knowledgeId.

        Whether navigation is still safe is determined separately through
        ChaoxingTaskDetector so ContentHandler shares exactly the same task
        semantics as TaskRunner.

        This is important for ordinary PDF modules:

            PDF viewer at real bottom
                    ↓
            Detector = CONTENT
                    ↓
            ContentHandler may navigate

        while an unread PDF, VIDEO, QUIZ, COMMENT, or unknown state still
        prevents CONTENT navigation.
        """
        initial_state = self._inspect_initial_state()

        self._assert_content_navigation_is_safe()

        if initial_state.has_next_tab:
            self._navigate_to_next_card(initial_state)
            return

        self._navigate_to_next_knowledge(initial_state)

    def _inspect_initial_state(
        self,
    ) -> ChaoxingPageState:
        """Read the current card state required for deterministic navigation."""
        try:
            return inspect_chaoxing_page(self._browser)

        except ChaoxingInspectionError as exc:
            raise ContentNavigationError("Unable to inspect the current Chaoxing content.") from exc

    def _assert_content_navigation_is_safe(
        self,
    ) -> None:
        """
        Verify the current task using the authoritative Chaoxing detector.

        TaskRunner normally calls this handler only after detecting CONTENT.
        The browser may nevertheless change between dispatch and handler
        execution, so the handler performs fresh bounded detection immediately
        before navigation.

        The detector is also the authoritative source for Document V1
        completion semantics. In particular, PDFs without a platform job
        marker are considered handled only after their real viewer reaches
        the bottom.
        """
        detector = ChaoxingTaskDetector(self._browser)

        deadline = self._monotonic() + self._config.navigation_timeout_seconds

        while self._monotonic() < deadline:
            try:
                task_type = detector.detect()

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
        """Click the next card and verify that the active card changes."""
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
            ):
                return

        raise ContentNavigationError(
            "The Chaoxing active card did not change before the navigation deadline."
        )

    def _navigate_to_next_knowledge(
        self,
        initial_state: ChaoxingPageState,
    ) -> None:
        """Advance from the final card to the next knowledge node."""
        knowledge_id = initial_state.knowledge_id

        if knowledge_id is None:
            raise ContentNavigationError("The current Chaoxing content frame has no valid knowledgeId.")

        target = self._inspect_next_knowledge(knowledge_id)

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
                and current_state.knowledge_id != knowledge_id
            ):
                return

        raise ContentNavigationError(
            "The Chaoxing knowledgeId did not change before the navigation deadline."
        )

    def _poll_page_state(
        self,
    ) -> ChaoxingPageState | None:
        """
        Poll the current card state during navigation.

        iframe replacement is expected during Chaoxing navigation, so a
        transient inspection failure does not immediately fail the handler.
        The caller's bounded navigation deadline remains authoritative.
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
        """Find the next knowledge node in real DOM document order."""
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
        """Click the previously evidenced next knowledge target."""
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
    """Require exactly one frame to contain the current knowledge node."""
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
    """Build the deterministic knowledge-tree inspection script."""
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
    """Build the deterministic real-DOM click script."""
    current_id = json.dumps(f"cur{knowledge_id}")

    frame_url = _js_string(target.frame_url)

    expected_next_id = _js_string(target.node_id)

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
    """Serialize a Python string safely for embedding in JavaScript."""
    return json.dumps(value)
