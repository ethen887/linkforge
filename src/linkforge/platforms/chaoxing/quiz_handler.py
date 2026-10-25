"""生产环境做题，带显式、失败即关闭的提交流水边界。"""

import logging
import time
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from math import isfinite
from typing import Protocol, TypeVar

from linkforge.application.task_runner import TaskDetector, TaskHandler, TaskReviewRequiredError, TaskType
from linkforge.browser.base import Browser
from linkforge.browser.element import BrowserElement
from linkforge.browser.exceptions import BrowserError
from linkforge.llm.errors import ModelRequestCancelledError
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
from linkforge.platforms.chaoxing.quiz_draft import DRAFT_CONTROL_SELECTOR, click_draft_save
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
        """通过已验证的正常 UI 提交一次，包含其确认流程。

        不得直接 POST、调用站点私有 API 或伪造已完成。
        返回意味着已尝试 UI 提交；Handler 会另行等待同一模块的
        真实任务点完成标记。
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
    """两次全新检查之间，未提交的 quiz DOM 发生了变化。"""


class QuizStoppedError(Exception):
    """协作停止，避免后续选项点击或提交。"""


class _QuizDraftClickedError(Exception):
    """已点击暂存，释放旧题目句柄后再检查页面。"""

    def __init__(self, selected: frozenset[str]) -> None:
        self.selected = selected


class ChaoxingQuizTaskHandler(TaskHandler):
    """作答一道 quiz；run() 仅在平台完成被校验后返回。

    answer_all() 是用于校验的显式不提交入口。在没有已验证提交器时，
    run() 作答完所有题目后抛出提交错误，防止 TaskRunner 把未提交的
    quiz 当作已完成。
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
        self._should_stop: Callable[[], bool] | None = None

    def _check_stop(self) -> None:
        if self._should_stop is not None and self._should_stop():
            raise QuizStoppedError

    def _question_scope(self, module_url: str) -> AbstractContextManager[tuple[BrowserElement, ...]]:
        return self._browser.element_scope(QUESTION_FRAME_PATH, QUESTION_SELECTOR, ancestor_url=module_url)

    def _draft_scope(self, module_url: str) -> AbstractContextManager[tuple[BrowserElement, ...]]:
        return self._browser.element_scope(
            QUESTION_FRAME_PATH, DRAFT_CONTROL_SELECTOR, ancestor_url=module_url
        )

    def _save_after_click(
        self, content_url: str, module_url: str, index: int, selected: frozenset[str]
    ) -> None:
        self._check_stop()
        if self._target() != (content_url, module_url):
            raise ChaoxingQuizStateError("Active Quiz changed before draft save.")
        try:
            with self._draft_scope(module_url) as elements:
                clicked = click_draft_save(elements, check_stop=self._check_stop)
        except BrowserError as exc:
            raise ChaoxingQuizStateError("Cannot inspect draft save controls.") from exc
        if clicked:
            logger.info("第 %d 题：已点击暂时保存，正在重新核验选项", index + 1)
            raise _QuizDraftClickedError(selected)

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
        """在全新的题目 frame 作用域内运行一个有界的操作。

        Chaoxing 可能随时替换嵌套的 work iframe。因此元素句柄在跨模型请求
        时从不复用；瞬时浏览器失败会重新打开作用域，而语义状态失败保持
        失败即关闭。
        """
        if deadline is None:
            deadline = self._monotonic() + self._config.readiness_timeout_seconds
        last_error: BrowserError | None = None
        while True:
            self._check_stop()
            try:
                with self._question_scope(module_url) as elements:
                    if not elements:
                        raise BrowserError("Quiz question frame contains no questions.")
                    return operation(elements)
            except BrowserError as exc:
                last_error = exc
                if on_unavailable is not None:
                    # 有些课程页面会先暴露可见的“章节测验（Chapter Quiz）”入口，
                    # 而不是直接加载嵌套的题目 iframe。先激活一次该正常 UI 入口，
                    # 然后继续同样的有界等待以获取真正的题目文档。
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
        """把待处理的 quiz 卡片滚动到视野内，好让 Chaoxing 能懒加载它。"""
        try:
            if any(
                result is True for result in self._browser.evaluate_in_frames(_REVEAL_PENDING_QUIZ_SCRIPT)
            ):
                logger.info("Revealed pending quiz card before waiting for questions")
        except BrowserError:
            logger.debug("Pending quiz card could not be revealed while the page is redrawing")

    def _open_quiz_entry(self, content_url: str, module_url: str) -> None:
        """若该模块存在唯一可见的 quiz 入口，则打开它。

        课程可能只有在“章节测验”卡片被进入视野并激活后，才懒加载 work
        iframe。这里使用站点的普通 UI；既不改完成状态，也不调用私有端点。
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
            # 下面的标准题目 frame 等待会处理最终的有界错误；
            # 若卡片在本段尝试期间重绘，也是安全的。
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
        """等待渐进渲染的题目列表达到稳定。"""
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
    ) -> QuizQuestion | QuizAnswer:
        dom = self._questions(elements, expected_count=question_count)[index]
        return dom.resumable_answer() or dom.capture()

    def _reconcile_question(
        self,
        elements: tuple[BrowserElement, ...],
        question: QuizQuestion,
        answer: QuizAnswer,
        question_count: int,
        *,
        on_selection_changed: Callable[[frozenset[str]], None] | None = None,
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
            before_click=self._check_stop,
            on_selection_changed=on_selection_changed,
        )

    def _reconcile_and_save(
        self,
        content_url: str,
        module_url: str,
        question: QuizQuestion,
        answer: QuizAnswer,
        question_count: int,
    ) -> None:
        expected_after_save: frozenset[str] | None = None

        def save(selected: frozenset[str]) -> None:
            self._save_after_click(content_url, module_url, question.index, selected)

        def reconcile(elements: tuple[BrowserElement, ...]) -> None:
            if expected_after_save is not None:
                if self._target() != (content_url, module_url):
                    raise ChaoxingQuizStateError("Active Quiz changed after draft save.")
                questions = self._questions(elements, expected_count=question_count)
                if questions[question.index].selected(answer.question_type) != expected_after_save:
                    raise ChaoxingQuizStateError("暂存后当前题目的选项发生变化，已停止继续作答。")
                for dom, previous in zip(questions[: question.index], self.last_answers, strict=True):
                    if dom.selected(previous.question_type) != set(previous.choices):
                        raise ChaoxingQuizStateError("暂存后此前题目的选项发生变化，已停止继续作答。")
            self._reconcile_question(elements, question, answer, question_count, on_selection_changed=save)

        # 一次选项变化后若点击了暂存，就退出旧作用域，用新句柄继续。
        # 每个选项最多变更一次，额外一次用于最终回读，避免保存后重绘造成循环。
        for _ in range(len(question.option_letters) + 1):
            try:
                self._with_questions(module_url, reconcile)
                return
            except _QuizDraftClickedError as saved:
                expected_after_save = saved.selected
                self._check_stop()
            except _QuizSnapshotChangedError as exc:
                if expected_after_save is not None:
                    raise ChaoxingQuizStateError("Quiz changed after draft save.") from exc
                raise
        raise ChaoxingQuizStateError("Quiz draft save did not reach a stable selection.")

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
        self._check_stop()
        try:
            content_url, module_url = self._target()
            deadline = self._monotonic() + self._config.readiness_timeout_seconds
            question_count = self._wait_for_stable_question_count(
                content_url, module_url, deadline=deadline
            )
            answers: list[QuizAnswer] = []
            index = 0
            while index < question_count:
                self._check_stop()
                if self._target() != (content_url, module_url):
                    raise ChaoxingQuizStateError("Active Quiz changed while answering.")

                def capture(elements: tuple[BrowserElement, ...]) -> QuizQuestion | QuizAnswer:
                    return self._capture_question(elements, index, question_count)

                try:
                    captured = self._with_questions(module_url, capture, deadline=deadline)
                except _QuizSnapshotChangedError as exc:
                    if answers:
                        raise ChaoxingQuizStateError("Quiz changed after answer selection.") from exc
                    question_count = self._wait_for_stable_question_count(
                        content_url, module_url, deadline=deadline
                    )
                    index = 0
                    continue
                self._check_stop()
                if isinstance(captured, QuizAnswer):
                    answers.append(captured)
                    self.last_answers = tuple(answers)
                    logger.info("第 %d 题：检测到已有答案，保留选项并跳过模型请求", index + 1)
                    index += 1
                    continue
                question = captured
                try:
                    self._check_stop()
                    answer = self._solver.solve(question)
                except ChaoxingQuizError:
                    raise
                except (QuizStoppedError, ModelRequestCancelledError):
                    raise
                except Exception as exc:
                    raise ChaoxingQuizSolverError(f"Question {question.index + 1}: solver failed.") from exc
                self._check_stop()
                validate_answer(question, answer)
                if self._target() != (content_url, module_url):
                    raise ChaoxingQuizStateError("Active Quiz changed during vision request.")

                try:
                    self._reconcile_and_save(content_url, module_url, question, answer, question_count)
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
            # 在提交之前，用另一个全新作用域重新读取全部选中项。

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
        """作答并提交一道 quiz，然后校验平台的完成状态。"""
        self.run_interruptibly()

    def run_interruptibly(self, *, should_stop: Callable[[], bool] | None = None) -> None:
        """在题目处理和提交前响应停止请求。"""
        self._should_stop = should_stop
        logger.info("Quiz handler started")
        try:
            self._run()
        except ModelRequestCancelledError:
            if self._should_stop is None or not self._should_stop():
                raise
            logger.info("Quiz handler stopped")
            return
        except QuizStoppedError:
            logger.info("Quiz handler stopped")
            return
        except TaskReviewRequiredError:
            logger.info("草稿处理已交给人工检查")
            raise
        except BaseException:
            logger.error("Quiz handler failed")
            raise
        logger.info("Quiz handler completed")

    def _run(self) -> None:
        content_url, module_url = self._answer_all()
        self._check_stop()
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
            self._check_stop()
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
