"""Production quiz answering with an explicit, fail-closed submission boundary."""

import time
from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import dataclass
from math import isfinite
from typing import Protocol

from linkforge.application.task_runner import TaskDetector, TaskHandler, TaskType
from linkforge.browser.base import Browser
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
from linkforge.platforms.chaoxing.quiz_models import QuizAnswer, validate_answer
from linkforge.platforms.chaoxing.quiz_solver import QuizSolver
from linkforge.platforms.chaoxing.task_detector import ChaoxingTaskDetector


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

    def __post_init__(self) -> None:
        for value in (
            self.readiness_timeout_seconds,
            self.selection_timeout_seconds,
            self.completion_timeout_seconds,
            self.poll_interval_seconds,
        ):
            if not isfinite(value) or value <= 0:
                raise ValueError("Quiz timing values must be finite and positive")


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

    def _answer_all(self) -> tuple[str, str]:
        self.last_answers = ()
        try:
            content_url, module_url = self._target()
            deadline = self._monotonic() + self._config.readiness_timeout_seconds
            with ExitStack() as stack:
                while True:
                    attempt = ExitStack()
                    try:
                        elements = attempt.enter_context(
                            self._browser.element_scope(
                                QUESTION_FRAME_PATH,
                                QUESTION_SELECTOR,
                                ancestor_url=module_url,
                            )
                        )
                        if not elements:
                            raise ChaoxingQuizStateError("Quiz question frame contains no questions.")
                    except (BrowserError, ChaoxingQuizStateError) as exc:
                        attempt.close()
                        if self._monotonic() >= deadline:
                            raise ChaoxingQuizStateError(
                                "Quiz/question frame missing, ambiguous, or contains no questions."
                            ) from exc
                        self._sleep(self._config.poll_interval_seconds)
                        continue
                    stack.enter_context(attempt)
                    break
                # Preflight every structure before the first model call or click.
                questions = [QuizDOMQuestion(element, i) for i, element in enumerate(elements)]
                answers = []
                for dom in questions:
                    if self._target() != (content_url, module_url):
                        raise ChaoxingQuizStateError("Active Quiz changed while answering.")
                    question = dom.capture()
                    try:
                        answer = self._solver.solve(question)
                    except ChaoxingQuizError:
                        raise
                    except Exception as exc:
                        raise ChaoxingQuizSolverError(f"Question {dom.index + 1}: solver failed.") from exc
                    validate_answer(question, answer)
                    if self._target() != (content_url, module_url):
                        raise ChaoxingQuizStateError("Active Quiz changed during vision request.")
                    dom.reconcile(
                        question,
                        answer,
                        timeout_seconds=self._config.selection_timeout_seconds,
                        poll_interval_seconds=self._config.poll_interval_seconds,
                        sleep=self._sleep,
                        monotonic=self._monotonic,
                    )
                    answers.append(answer)
                    self.last_answers = tuple(answers)
                # Re-read all selections before handing off to submission.
                for dom, answer in zip(questions, answers):
                    if dom.selected(answer.question_type) != set(answer.choices):
                        raise ChaoxingQuizStateError("An earlier question selection changed.")
            return content_url, module_url
        except (BrowserError, ChaoxingInspectionError) as exc:
            raise ChaoxingQuizStateError("Quiz DOM operation failed.") from exc

    def run(self) -> None:
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
