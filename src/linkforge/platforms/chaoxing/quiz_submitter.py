"""Fail-closed normal-UI submission for Chaoxing Quiz tasks."""

import logging
import time
from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import dataclass
from math import isfinite

from linkforge.browser.base import Browser
from linkforge.browser.element import BrowserElement
from linkforge.browser.exceptions import BrowserError
from linkforge.platforms.chaoxing.exceptions import ChaoxingQuizSubmissionError
from linkforge.platforms.chaoxing.quiz_dom import QUESTION_FRAME_PATH

_CONTROL_SELECTOR = 'button, input[type="button"], input[type="submit"], [role="button"]'
_TOP_CONFIRM_SELECTOR = "#workpop #popok"
logger = logging.getLogger(__name__)
_CONTROL_STATE_EXPRESSION = r"""element => {
    const style = window.getComputedStyle(element);
    const popup = element.closest('#workpop');
    const popupBody = popup?.querySelector('#popcontent');
    const dialog = popup || element.closest('.popDiv, [role="dialog"]');
    return {
        top_confirmation: !!popupBody && element.id === 'popok'
            && popup.querySelectorAll('#popok').length === 1
            && popup.querySelectorAll('#popno').length === 1,
        unfinished_warning: /未完成|未答|未作答|未做|unfinished|unanswered|incomplete/i.test(
            (popupBody || dialog)?.textContent || ''
        ),
        tag: element.tagName.toLowerCase(),
        id: element.id || "",
        type: element.getAttribute("type") || "",
        class:
            typeof element.className === "string"
                ? element.className
                : element.getAttribute("class") || "",
        text: (element.innerText || element.textContent || "").replace(/\s+/g, " ").trim(),
        value: "value" in element ? String(element.value || "").trim() : "",
        title: element.getAttribute("title") || "",
        aria_label: element.getAttribute("aria-label") || "",
        visible:
            style.display !== "none"
            && style.visibility !== "hidden"
            && element.getClientRects().length > 0,
        enabled:
            !element.disabled
            && element.getAttribute("aria-disabled") !== "true",
    };
}"""

_SUBMIT_EXCLUDED_IDS = {"submitBackOk", "submitBackCancel", "nextFocusButton"}
_SUBMIT_EXACT_LABELS = {
    "提交",
    "交卷",
    "提交答案",
    "提交作业",
    "完成答题",
    "完成测试",
}
_SUBMIT_LABEL_TERMS = ("提交", "交卷", "submit", "finish", "hand in", "handin")
_SUBMIT_FORBIDDEN_TERMS = ("取消", "返回", "下一", "保存", "cancel", "back", "next", "save")
_CONFIRM_EXACT_LABELS = {
    "确定",
    "确认",
    "确认提交",
    "确定提交",
    "是",
    "ok",
    "confirm",
}


@dataclass(frozen=True, slots=True)
class _Control:
    element: BrowserElement
    element_id: str
    element_type: str
    class_name: str
    label: str
    visible: bool
    enabled: bool
    top_confirmation: bool
    unfinished_warning: bool


class ChaoxingQuizSubmitter:
    """Submit one answered Quiz through unique visible controls, without retries."""

    def __init__(
        self,
        *,
        confirmation_timeout_seconds: float = 3.0,
        poll_interval_seconds: float = 0.1,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if any(not isfinite(v) or v <= 0 for v in (confirmation_timeout_seconds, poll_interval_seconds)):
            raise ValueError("Confirmation timing values must be finite and positive")
        self._confirmation_timeout = confirmation_timeout_seconds
        self._poll_interval = poll_interval_seconds
        self._sleep = sleep
        self._monotonic = monotonic

    def submit(self, browser: Browser, *, module_url: str) -> None:
        """Click one submit control and its unique DOM confirmation exactly once."""
        self._click_unique_submit(browser, module_url=module_url)
        self._click_unique_confirmation(browser, module_url=module_url)

    def _click_unique_submit(self, browser: Browser, *, module_url: str) -> None:
        try:
            with browser.element_scope(
                QUESTION_FRAME_PATH,
                _CONTROL_SELECTOR,
                ancestor_url=module_url,
            ) as elements:
                controls = tuple(self._inspect(element, phase="submit") for element in elements)
                target = _unique_best(controls, _submit_score, phase="submit")
                target.element.click()
        except ChaoxingQuizSubmissionError:
            raise
        except BrowserError as exc:
            raise ChaoxingQuizSubmissionError(
                "Quiz submit control could not be inspected or clicked; submission will not be retried."
            ) from exc

    def _click_unique_confirmation(self, browser: Browser, *, module_url: str) -> None:
        try:
            deadline = self._monotonic() + self._confirmation_timeout
            while True:
                with ExitStack() as stack:
                    local = stack.enter_context(
                        browser.element_scope(
                            QUESTION_FRAME_PATH,
                            _CONTROL_SELECTOR,
                            ancestor_url=module_url,
                        )
                    )
                    top = stack.enter_context(browser.page_element_scope(_TOP_CONFIRM_SELECTOR))
                    controls = tuple(self._inspect(e, phase="confirmation") for e in (*local, *top))
                    if any(c.visible and c.unfinished_warning for c in controls):
                        logger.debug("Chaoxing quiz confirmation blocked: reason=unfinished_questions")
                        raise ChaoxingQuizSubmissionError(
                            "Platform reports unfinished questions; confirmation was not clicked."
                        )
                    if any(_confirmation_score(c) > 0 for c in controls):
                        target = _unique_best(controls, _confirmation_score, phase="confirmation")
                        target.element.click()
                        return
                    logger.debug(
                        "Chaoxing quiz confirmation pending: local_count=%d top_count=%d visible_count=%d",
                        len(local),
                        len(top),
                        sum(c.visible for c in controls),
                    )
                if self._monotonic() >= deadline:
                    raise ChaoxingQuizSubmissionError(
                        "No trustworthy Quiz confirmation control was found within the bounded wait."
                    )
                self._sleep(self._poll_interval)
        except ChaoxingQuizSubmissionError:
            raise
        except BrowserError as exc:
            raise ChaoxingQuizSubmissionError(
                "Quiz confirmation control could not be inspected or clicked."
            ) from exc

    @staticmethod
    def _inspect(element: BrowserElement, *, phase: str) -> _Control:
        raw = element.evaluate(_CONTROL_STATE_EXPRESSION)
        if not isinstance(raw, dict):
            raise ChaoxingQuizSubmissionError(f"Quiz {phase} control state is malformed.")

        visible = raw.get("visible")
        enabled = raw.get("enabled")
        if not isinstance(visible, bool) or not isinstance(enabled, bool):
            raise ChaoxingQuizSubmissionError(f"Quiz {phase} control state is malformed.")
        if any(type(raw.get(key, False)) is not bool for key in ("top_confirmation", "unfinished_warning")):
            raise ChaoxingQuizSubmissionError(f"Quiz {phase} dialog state is malformed.")

        return _Control(
            element=element,
            element_id=_text(raw, "id", phase=phase),
            element_type=_text(raw, "type", phase=phase).lower(),
            class_name=_text(raw, "class", phase=phase),
            label=" ".join(
                value
                for key in ("text", "value", "title", "aria_label")
                if (value := _text(raw, key, phase=phase))
            ).strip(),
            visible=visible,
            enabled=enabled,
            top_confirmation=raw.get("top_confirmation", False),
            unfinished_warning=raw.get("unfinished_warning", False),
        )


def _text(raw: dict[object, object], key: str, *, phase: str) -> str:
    value = raw.get(key)
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ChaoxingQuizSubmissionError(f"Quiz {phase} control state is malformed.")
    return " ".join(value.split())


def _unique_best(
    controls: tuple[_Control, ...],
    score_control: Callable[[_Control], int],
    *,
    phase: str,
) -> _Control:
    scores = tuple((control, score_control(control)) for control in controls)
    candidates = tuple((control, score) for control, score in scores if score > 0)
    if not candidates:
        raise ChaoxingQuizSubmissionError(f"No trustworthy Quiz {phase} control was found.")

    best_score = max(score for _, score in candidates)
    best = tuple(control for control, score in candidates if score == best_score)
    if len(best) != 1:
        raise ChaoxingQuizSubmissionError(f"Quiz {phase} control is ambiguous.")
    return best[0]


def _submit_score(control: _Control) -> int:
    if not control.visible or not control.enabled or control.element_id in _SUBMIT_EXCLUDED_IDS:
        return -1

    label = control.label.lower()
    if any(term in label for term in _SUBMIT_FORBIDDEN_TERMS):
        return -1

    score = 0
    if control.element_type == "submit":
        score += 50
    identifier = f"{control.element_id} {control.class_name}".lower()
    if any(term in identifier for term in ("submit", "finish", "handin")):
        score += 50
    if control.label in _SUBMIT_EXACT_LABELS:
        score += 120
    elif any(term in label for term in _SUBMIT_LABEL_TERMS):
        score += 80
    return score


def _confirmation_score(control: _Control) -> int:
    if not control.visible or not control.enabled or control.element_id == "submitBackCancel":
        return -1
    if control.element_id == "submitBackOk":
        return 200
    if control.top_confirmation and control.element_id == "popok":
        return 200
    if control.label.lower() in _CONFIRM_EXACT_LABELS:
        return 120
    return -1
