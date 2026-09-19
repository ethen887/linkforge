"""Fail-closed normal-UI submission for Chaoxing Quiz tasks."""

from collections.abc import Callable
from dataclasses import dataclass

from linkforge.browser.base import Browser
from linkforge.browser.element import BrowserElement
from linkforge.browser.exceptions import BrowserError
from linkforge.platforms.chaoxing.exceptions import ChaoxingQuizSubmissionError
from linkforge.platforms.chaoxing.quiz_dom import QUESTION_FRAME_PATH

_CONTROL_SELECTOR = 'button, input[type="button"], input[type="submit"], [role="button"]'
_CONTROL_STATE_EXPRESSION = r"""element => {
    const style = window.getComputedStyle(element);
    return {
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


class ChaoxingQuizSubmitter:
    """Submit one answered Quiz through unique visible controls, without retries."""

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
            with browser.element_scope(
                QUESTION_FRAME_PATH,
                _CONTROL_SELECTOR,
                ancestor_url=module_url,
            ) as elements:
                controls = tuple(self._inspect(element, phase="confirmation") for element in elements)
                target = _unique_best(controls, _confirmation_score, phase="confirmation")
                target.element.click()
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
    if control.label.lower() in _CONFIRM_EXACT_LABELS:
        return 120
    return -1
