"""Production quiz answering with an explicit, fail-closed submission boundary."""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from math import isfinite
from typing import Protocol, TypeVar

from linkforge.application.task_runner import TaskDetector, TaskHandler, TaskType
from linkforge.browser.base import Browser
from linkforge.browser.element import BrowserElement
from linkforge.browser.exceptions import BrowserError
from linkforge.platforms.chaoxing.dom import inspect_chaoxing_page
from linkforge.platforms.chaoxing.exceptions import (
    ChaoxingInspectionError,
    ChaoxingQuizCompletionError,
    ChaoxingQuizError,
    ChaoxingQuizSolverError,
    ChaoxingQuizStateError,
    ChaoxingQuizSubmissionError,
)
from linkforge.platforms.chaoxing.quiz_dom import (
    QUESTION_FRAME_PATH,
    QUESTION_SELECTOR,
    QUIZ_MODULE_PATH,
    QuizDOMQuestion,
)
from linkforge.platforms.chaoxing.quiz_models import (
    QuizAnswer,
    QuizQuestion,
    QuizQuestionType,
    validate_answer,
)
from linkforge.platforms.chaoxing.quiz_solver import QuizSolver
from linkforge.platforms.chaoxing.task_detector import ChaoxingTaskDetector

logger = logging.getLogger(__name__)
_T = TypeVar("_T")

_QUIZ_ENTRY_SELECTOR = (
    'button, a, [role="button"], input[type="button"], input[type="submit"], [onclick], '
    'div[class*="chapter" i], div[class*="quiz" i], div[class*="work" i], div[class*="test" i]'
)
_QUIZ_ENTRY_LABELS = frozenset({"chapter quiz", "章节测试", "章节测验", "课后习题及章节测试"})
_REVEAL_PENDING_QUIZ_SCRIPT = """() => {
    const selectors = [
        'iframe[src*="/ananas/modules/work/"]', '.ans-job-icon',
        '[class*="chapter" i]', '[class*="quiz" i]', '[class*="work" i]', '[class*="test" i]',
    ];
    const terms = ['chapter quiz', '章节测试', '章节测验'];
    const target = [...document.querySelectorAll(selectors.join(','))].find(element => {
        const text = (element.innerText || element.textContent || '').replace(/\\s+/g, ' ').toLowerCase();
        return element.matches('iframe[src*="/ananas/modules/work/"]')
            || terms.some(term => text.includes(term));
    });
    if (!target) return false;
    target.scrollIntoView({block: 'center', inline: 'nearest'});
    return true;
}"""


class QuizSubmitter(Protocol):
    def submit(self, browser: Browser, *, module_url: str) -> None:
        """Submit once through verified normal UI, including its confirmation.

        Must not POST directly, invoke private site APIs, or forge completion.
        Returning means the UI submission was attempted; the handler separately
        waits for the same module's real task-point completion marker.
        """
        ...


@dataclass(frozen=True, slots=True)
class ChaoxingQuizHandlerConfig:
    readiness_timeout_seconds: float = 15.0
    selection_timeout_seconds: float = 3.0
    completion_timeout_seconds: float = 30.0
    poll_interval_seconds: float = 0.1
    stable_question_observations: int = 2

    def __post_init__(self) -> None:
        for value in (
            self.readiness_timeout_seconds,
            self.selection_timeout_seconds,
            self.completion_timeout_seconds,
            self.poll_interval_seconds,
        ):
            if not isfinite(value) or value <= 0:
                raise ValueError("Quiz timing values must be finite and positive")
        if self.stable_question_observations < 2:
            raise ValueError("stable_question_observations must be at least 2")


class _QuizSnapshotChangedError(ChaoxingQuizStateError):
    """The unsubmitted quiz DOM changed between fresh inspections."""


class ChaoxingQuizTaskHandler(TaskHandler):
    """Answer one quiz; run() returns only after verified platform completion.

    answer_all() is the explicit no-submit entry point for validation. Without
    a verified submitter, run() answers all questions then raises a submission
    error, preventing TaskRunner from treating an unsubmitted quiz as finished.
    """

    def __init__(
        self,
        browser: Browser,
        *,
        solver: QuizSolver,
        submitter: QuizSubmitter | None = None,
        detector: TaskDetector | None = None,
        config: ChaoxingQuizHandlerConfig | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._browser = browser
        self._solver = solver
        self._submitter = submitter
        self._detector = detector or ChaoxingTaskDetector(browser)
        self._config = config or ChaoxingQuizHandlerConfig()
        self._sleep = sleep
        self._monotonic = monotonic
        self.last_answers: tuple[QuizAnswer, ...] = ()

    def _target(self) -> tuple[str, str]:
        if self._detector.detect() is not TaskType.QUIZ:
            raise ChaoxingQuizStateError("Current task is not QUIZ.")
        state = inspect_chaoxing_page(self._browser)
        targets = [
            m for m in state.modules if QUIZ_MODULE_PATH in m.url and not (m.has_job_icon and m.finished)
        ]
        if not targets:
            raise ChaoxingQuizStateError("No pending Quiz module frame found.")
        target = targets[0]
        if sum(m.url == target.url for m in state.modules) != 1:
            raise ChaoxingQuizStateError("Quiz module frame identity is ambiguous.")
        return state.content_frame_url, target.url

    def answer_all(self) -> tuple[QuizAnswer, ...]:
        """Capture, solve, select and verify all questions; never submit."""
        self._answer_all()
        return self.last_answers

    def _with_questions(
        self,
        module_url: str,
        operation: Callable[[tuple[BrowserElement, ...]], _T],
        *,
        deadline: float | None = None,
        on_unavailable: Callable[[], None] | None = None,
    ) -> _T:
        """Run one bounded operation in a fresh question-frame scope.

        Chaoxing may replace the nested work iframe at any time. Element
        handles therefore never survive across model requests; transient
        browser failures reopen the scope, while semantic state failures
        remain fail-closed.
        """
        if deadline is None:
            deadline = self._monotonic() + self._config.readiness_timeout_seconds
        last_error: BrowserError | None = None
        while True:
            try:
                with self._browser.element_scope(
                    QUESTION_FRAME_PATH,
                    QUESTION_SELECTOR,
                    ancestor_url=module_url,
                ) as elements:
                    if not elements:
                        raise BrowserError("Quiz question frame contains no questions.")
                    return operation(elements)
            except BrowserError as exc:
                last_error = exc
                if on_unavailable is not None:
                    # Some course pages first expose a visible "Chapter Quiz"
                    # entry rather than loading the nested question iframe.
                    # Activate that normal UI entry once, then keep the same
                    # bounded wait for the actual question document.
                    activate, on_unavailable = on_unavailable, None
                    activate()
                if self._monotonic() >= deadline:
                    raise ChaoxingQuizStateError(
                        "Quiz/question frame missing, ambiguous, detached, or contains no questions."
                    ) from last_error
                self._sleep(self._config.poll_interval_seconds)

    @staticmethod
    def _quiz_entry_label(element: BrowserElement) -> str | None:
        value = element.evaluate(
            """element => {
                const candidates = [
                    element.innerText, element.textContent, element.value,
                    element.getAttribute('aria-label'), element.getAttribute('title'),
                ];
                return candidates
                    .map(candidate => (candidate || '').replace(/\\s+/g, ' ').trim().toLowerCase())
                    .find(Boolean) || '';
            }"""
        )
        return value.strip().lower() if isinstance(value, str) else None

    @staticmethod
    def _is_quiz_entry_label(label: str | None) -> bool:
        return label in _QUIZ_ENTRY_LABELS or (
            label is not None
            and (label.startswith("chapter quiz") or label.startswith("章节测验") or "章节测试" in label)
        )

    def _reveal_pending_quiz(self) -> None:
        """Bring the pending quiz card into view so Chaoxing can lazy-load it."""
        try:
            if any(
                result is True for result in self._browser.evaluate_in_frames(_REVEAL_PENDING_QUIZ_SCRIPT)
            ):
                logger.info("Revealed pending quiz card before waiting for questions")
        except BrowserError:
            logger.debug("Pending quiz card could not be revealed while the page is redrawing")

    def _open_quiz_entry(self, content_url: str, module_url: str) -> None:
        """Open one unambiguous visible quiz entry, if this module has one.

        The course may lazy-load a work iframe only after its Chapter Quiz card
        is brought into view and activated.  This uses the site's ordinary UI;
        it neither changes completion state nor calls private endpoints.
        """
        try:
            with self._browser.element_scope(
                module_url,
                _QUIZ_ENTRY_SELECTOR,
                ancestor_url=content_url,
            ) as elements:
                entries = [
                    element
                    for element in elements
                    if self._is_quiz_entry_label(self._quiz_entry_label(element))
                ]
                if len(entries) == 1:
                    entries[0].click()
                    logger.info("Opened visible Chapter Quiz entry before waiting for questions")
                elif len(entries) > 1:
                    logger.warning("Quiz entry is ambiguous; waiting without clicking")
        except BrowserError:
            # The standard question-frame wait below owns the final bounded
            # error and remains safe if the card redraws during this attempt.
            logger.debug("Visible quiz entry unavailable while question iframe is loading")

    def _prepare_pending_quiz(self, content_url: str, module_url: str) -> None:
        self._reveal_pending_quiz()
        self._open_quiz_entry(content_url, module_url)

    @staticmethod
    def _questions(
        elements: tuple[BrowserElement, ...],
        *,
        expected_count: int | None = None,
    ) -> list[QuizDOMQuestion]:
        if expected_count is not None and len(elements) != expected_count:
            raise _QuizSnapshotChangedError("Quiz question count changed while answering.")
        return [QuizDOMQuestion(element, index) for index, element in enumerate(elements)]

    def _preflight_questions(self, elements: tuple[BrowserElement, ...]) -> int:
        questions = self._questions(elements)
        for dom in questions:
            # Radio state can be checked even when Vision must later
            # distinguish single-choice from true/false.
            dom.selected(dom.hint or QuizQuestionType.SINGLE_CHOICE)
        return len(questions)

    def _wait_for_stable_question_count(
        self,
        content_url: str,
        module_url: str,
        *,
        deadline: float,
    ) -> int:
        """Wait for the progressively rendered question list to stabilize."""
        count: int | None = None
        observations = 0
        while True:
            observed_count = self._with_questions(
                module_url,
                self._preflight_questions,
                deadline=deadline,
                on_unavailable=lambda: self._prepare_pending_quiz(content_url, module_url),
            )
            if observed_count == count:
                observations += 1
            else:
                count = observed_count
                observations = 1
            if observations >= self._config.stable_question_observations:
                return observed_count
            if self._monotonic() >= deadline:
                raise ChaoxingQuizStateError("Quiz question list did not stabilize before the deadline.")
            self._sleep(self._config.poll_interval_seconds)

    def _capture_question(
        self,
        elements: tuple[BrowserElement, ...],
        index: int,
        question_count: int,
    ) -> QuizQuestion:
        return self._questions(elements, expected_count=question_count)[index].capture()

    def _reconcile_question(
        self,
        elements: tuple[BrowserElement, ...],
        question: QuizQuestion,
        answer: QuizAnswer,
        question_count: int,
    ) -> None:
        dom = self._questions(elements, expected_count=question_count)[question.index]
        if dom.hint != question.question_type or tuple(dom.options) != question.option_letters:
            raise _QuizSnapshotChangedError("Quiz question structure changed during model request.")
        dom.reconcile(
            question,
            answer,
            timeout_seconds=self._config.selection_timeout_seconds,
            poll_interval_seconds=self._config.poll_interval_seconds,
            sleep=self._sleep,
            monotonic=self._monotonic,
        )

    def _verify_answers(
        self,
        elements: tuple[BrowserElement, ...],
        answers: list[QuizAnswer],
        question_count: int,
    ) -> None:
        questions = self._questions(elements, expected_count=question_count)
        for dom, answer in zip(questions, answers, strict=True):
            if dom.selected(answer.question_type) != set(answer.choices):
                raise ChaoxingQuizStateError("An earlier question selection changed.")

    def _answer_all(self) -> tuple[str, str]:
        self.last_answers = ()
        try:
            content_url, module_url = self._target()
            deadline = self._monotonic() + self._config.readiness_timeout_seconds
            question_count = self._wait_for_stable_question_count(
                content_url, module_url, deadline=deadline
            )
            answers: list[QuizAnswer] = []
            index = 0
            while index < question_count:
                if self._target() != (content_url, module_url):
                    raise ChaoxingQuizStateError("Active Quiz changed while answering.")

                def capture(elements: tuple[BrowserElement, ...]) -> QuizQuestion:
                    return self._capture_question(elements, index, question_count)

                try:
                    question = self._with_questions(module_url, capture, deadline=deadline)
                except _QuizSnapshotChangedError as exc:
                    if answers:
                        raise ChaoxingQuizStateError("Quiz changed after answer selection.") from exc
                    question_count = self._wait_for_stable_question_count(
                        content_url, module_url, deadline=deadline
                    )
                    index = 0
                    continue
                try:
                    answer = self._solver.solve(question)
                except ChaoxingQuizError:
                    raise
                except Exception as exc:
                    raise ChaoxingQuizSolverError(f"Question {question.index + 1}: solver failed.") from exc
                validate_answer(question, answer)
                if self._target() != (content_url, module_url):
                    raise ChaoxingQuizStateError("Active Quiz changed during vision request.")

                def reconcile(elements: tuple[BrowserElement, ...]) -> None:
                    self._reconcile_question(elements, question, answer, question_count)

                try:
                    self._with_questions(module_url, reconcile, deadline=deadline)
                except _QuizSnapshotChangedError as exc:
                    if answers:
                        raise ChaoxingQuizStateError("Quiz changed after answer selection.") from exc
                    question_count = self._wait_for_stable_question_count(
                        content_url, module_url, deadline=deadline
                    )
                    index = 0
                    continue
                answers.append(answer)
                self.last_answers = tuple(answers)
                index += 1
            # Re-read all selections in another fresh scope before submission.

            def verify(elements: tuple[BrowserElement, ...]) -> None:
                self._verify_answers(elements, answers, question_count)

            try:
                self._with_questions(module_url, verify, deadline=deadline)
            except _QuizSnapshotChangedError as exc:
                raise ChaoxingQuizStateError("Quiz changed after answer selection.") from exc
            return content_url, module_url
        except (BrowserError, ChaoxingInspectionError) as exc:
            raise ChaoxingQuizStateError("Quiz DOM operation failed.") from exc

    def run(self) -> None:
        """Answer and submit one quiz, then verify platform completion."""
        logger.info("Quiz handler started")
        try:
            self._run()
        except BaseException:
            logger.exception("Quiz handler failed")
            raise
        logger.info("Quiz handler completed")

    def _run(self) -> None:
        content_url, module_url = self._answer_all()
        if self._submitter is None:
            raise ChaoxingQuizSubmissionError(
                "All answers verified; stopped before submission. The real visible submit entry, "
                "confirmation transition and resulting completion lifecycle have not been validated."
            )
        try:
            if self._target() != (content_url, module_url):
                raise ChaoxingQuizSubmissionError("Active Quiz changed before submission.")
            self._submitter.submit(self._browser, module_url=module_url)
        except ChaoxingQuizError:
            raise
        except Exception as exc:
            raise ChaoxingQuizSubmissionError("Quiz UI submission failed; it will not be retried.") from exc
        deadline = self._monotonic() + self._config.completion_timeout_seconds
        while True:
            try:
                state = inspect_chaoxing_page(self._browser)
                matches = [m for m in state.modules if m.url == module_url]
                if state.content_frame_url != content_url or len(matches) != 1:
                    raise ChaoxingQuizCompletionError(
                        "Quiz identity changed before completion verification."
                    )
                if matches[0].has_job_icon and matches[0].finished:
                    return
            except ChaoxingInspectionError as exc:
                if self._monotonic() >= deadline:
                    raise ChaoxingQuizCompletionError("Cannot inspect Quiz completion.") from exc
            if self._monotonic() >= deadline:
                raise ChaoxingQuizCompletionError("Timed out waiting for the real Quiz completion marker.")
            self._sleep(self._config.poll_interval_seconds)
