"""Question-scoped inspection and idempotent normal UI option selection."""

import json
import time
from collections.abc import Callable

from linkforge.browser.element import BrowserElement
from linkforge.browser.exceptions import BrowserError
from linkforge.llm.base import LLMImage
from linkforge.platforms.chaoxing.exceptions import (
    ChaoxingQuizAnswerError,
    ChaoxingQuizCaptureError,
    ChaoxingQuizStateError,
)
from linkforge.platforms.chaoxing.quiz_models import (
    QuizAnswer,
    QuizQuestion,
    QuizQuestionType,
    option_letters,
    parse_question_type,
    validate_answer,
)

QUIZ_MODULE_PATH = "/ananas/modules/work/"
QUESTION_FRAME_PATH = "/mooc-ans/work/doHomeWorkNew"
QUESTION_SELECTOR = ".TiMu.newTiMu"
_CONTROLS = '[role="radio"], [role="checkbox"], input[type="radio"], input[type="checkbox"]'
# A role wrapper with a native input is one option, not two.
OPTION_SELECTOR = f":is({_CONTROLS}):not(:is({_CONTROLS}) :is({_CONTROLS}))"
_QUESTION_SCRIPT = r"""element => ({
    title: element.querySelector('.Zy_TItle')?.textContent || '',
    hidden_answers: Array.from(element.querySelectorAll('input[type="hidden"]'))
        .filter(input => /^answer\d+$/.test(input.id) || /^answer\d+$/.test(input.name))
        .map(input => input.value),
    images_ready: Array.from(element.querySelectorAll('img'))
        .every(image => image.complete && image.naturalWidth > 0)
})"""
_OPTION_SCRIPT = """element => {
    const input = element.matches('input') ? element : element.querySelector(
        'input[type="radio"],input[type="checkbox"]'
    );
    const aria = element.getAttribute('aria-checked');
    const question = element.closest('.TiMu.newTiMu');
    return {
        kind: element.getAttribute('role') || input?.type || '',
        aria: aria,
        checked: input ? input.checked : null,
        index: question ? Array.from(question.querySelectorAll(SELECTOR)).indexOf(element) : -1,
        count: question ? question.querySelectorAll(SELECTOR).length : 0
    };
}""".replace("SELECTOR", json.dumps(OPTION_SELECTOR))


class QuizDOMQuestion:
    """Own a stable question-local letter mapping for the duration of one scope."""

    def __init__(self, element: BrowserElement, index: int) -> None:
        self.element = element
        self.index = index
        self.options = dict(zip(option_letters(len(nodes := element.query_all(OPTION_SELECTOR))), nodes))
        states = self._option_states()
        self.roles = tuple(state["kind"] for state in states)
        self.hint = parse_question_type(self._metadata()["title"], self.roles)

    def _metadata(self) -> dict:
        raw = self.element.evaluate(_QUESTION_SCRIPT)
        if (
            not isinstance(raw, dict)
            or not isinstance(raw.get("title"), str)
            or not isinstance(raw.get("hidden_answers"), list)
            or any(not isinstance(value, str) for value in raw["hidden_answers"])
            or not isinstance(raw.get("images_ready"), bool)
        ):
            raise ChaoxingQuizStateError("Malformed question metadata.")
        if len(raw["hidden_answers"]) > 1:
            raise ChaoxingQuizStateError("Question has ambiguous hidden answer fields.")
        return raw

    def _option_states(self) -> list[dict]:
        states = []
        for index, node in enumerate(self.options.values()):
            raw = node.evaluate(_OPTION_SCRIPT)
            if (
                not isinstance(raw, dict)
                or raw.get("kind") not in ("radio", "checkbox")
                or raw.get("index") != index
                or raw.get("count") != len(self.options)
                or raw.get("aria") not in (None, "true", "false")
                or (raw.get("checked") is not None and type(raw.get("checked")) is not bool)
            ):
                raise ChaoxingQuizStateError("Options changed or have unsupported selection semantics.")
            states.append(raw)
        return states

    def capture(self) -> QuizQuestion:
        try:
            image = LLMImage(self.element.screenshot())
            if not self._metadata()["images_ready"]:
                raise ChaoxingQuizCaptureError("Question contains unloaded or broken images.")
        except (BrowserError, ValueError) as exc:
            raise ChaoxingQuizCaptureError(f"Question {self.index + 1}: screenshot failed.") from exc
        return QuizQuestion(self.index, self.hint, tuple(self.options), image)

    def selected(self, question_type: QuizQuestionType) -> set[str]:
        states = self._option_states()
        if tuple(state["kind"] for state in states) != self.roles:
            raise ChaoxingQuizStateError("Option control types changed during answering.")
        hidden_values = self._metadata()["hidden_answers"]
        hidden = hidden_values[0] if hidden_values else None
        radio = question_type is not QuizQuestionType.MULTIPLE_CHOICE
        # Only the observed single-letter radio encoding is interpreted. Never
        # infer checkbox selections from an undocumented hidden-value encoding.
        hidden_selected = None
        if radio and hidden is not None and (hidden == "" or hidden in self.options):
            hidden_selected = {hidden} if hidden else set()
        selected = set()
        for letter, state in zip(self.options, states):
            signals = []
            if state["aria"] is not None:
                signals.append(state["aria"] == "true")
            if state["checked"] is not None:
                signals.append(state["checked"])
            if hidden_selected is not None:
                signals.append(letter in hidden_selected)
            if not signals or len(set(signals)) != 1:
                raise ChaoxingQuizStateError(f"Option {letter}: missing or conflicting selected state.")
            if signals[0]:
                selected.add(letter)
        if radio and len(selected) > 1:
            raise ChaoxingQuizStateError("Radio question has multiple selected answers.")
        return selected

    def reconcile(
        self,
        question: QuizQuestion,
        answer: QuizAnswer,
        *,
        timeout_seconds: float,
        poll_interval_seconds: float,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        validate_answer(question, answer)
        multiple = answer.question_type is QuizQuestionType.MULTIPLE_CHOICE
        if set(self.roles) != ({"checkbox"} if multiple else {"radio"}):
            raise ChaoxingQuizAnswerError("AI question type conflicts with DOM control semantics.")
        target = set(answer.choices)
        current = self.selected(answer.question_type)

        def verify(expected: set[str]) -> None:
            deadline = monotonic() + timeout_seconds
            last_error = None
            while True:
                try:
                    if self.selected(answer.question_type) == expected:
                        return
                except ChaoxingQuizStateError as exc:
                    last_error = exc
                if monotonic() >= deadline:
                    raise ChaoxingQuizStateError(
                        f"Question {self.index + 1}: option click/selection verification failed."
                    ) from last_error
                sleep(poll_interval_seconds)

        if multiple:
            for letter in self.options:
                if (letter in current) != (letter in target):
                    self.options[letter].click()
                    current.symmetric_difference_update({letter})
                    verify(current)
        elif current != target:
            self.options[answer.choices[0]].click()
        verify(target)
