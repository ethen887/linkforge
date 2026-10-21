"""独立作业适配：复用逐题截图和回读，只通过正常 UI 提交。"""

import logging
from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext

from linkforge.application.task_runner import TaskDetector, TaskType
from linkforge.browser.base import Browser
from linkforge.browser.element import BrowserElement
from linkforge.browser.exceptions import BrowserClosedError, BrowserError
from linkforge.browser.models import BrowserJSONResponse
from linkforge.platforms.chaoxing.assignment_page import (
    ASSIGNMENT_QUESTION_SELECTOR,
    ASSIGNMENT_SUBMIT_PATH,
    assignment_identity,
    inspect_assignment_page,
)
from linkforge.platforms.chaoxing.exceptions import (
    ChaoxingQuizCompletionError,
    ChaoxingQuizStateError,
    ChaoxingQuizSubmissionError,
)
from linkforge.platforms.chaoxing.quiz_draft import DRAFT_CONTROL_SELECTOR
from linkforge.platforms.chaoxing.quiz_handler import ChaoxingQuizTaskHandler, _QuizDraftClickedError
from linkforge.platforms.chaoxing.quiz_submitter import _CONTROL_SELECTOR, ChaoxingQuizSubmitter

logger = logging.getLogger(__name__)


class AssignmentDetector(TaskDetector):
    """单份独立作业的生命周期，不推断整门课程的完成状态。"""

    def __init__(self, browser: Browser) -> None:
        self._browser = browser
        self.completed = False

    def detect(self) -> TaskType:
        if self.completed:
            return TaskType.COMPLETE
        state = inspect_assignment_page(self._browser)
        if state.submitted:
            self.completed = True
            return TaskType.COMPLETE
        return TaskType.QUIZ if state.ready else TaskType.UNKNOWN


class AssignmentSubmitter(ChaoxingQuizSubmitter):
    """支持观察到的主页面链接式 Submit 和 workpop 确认。"""

    check_stop: Callable[[], None] | None = None

    def _before_click(self) -> None:
        if self.check_stop is not None:
            self.check_stop()

    def _control_scope(
        self, browser: Browser, module_url: str
    ) -> AbstractContextManager[tuple[BrowserElement, ...]]:
        if browser.current_url() != module_url:
            raise ChaoxingQuizSubmissionError("Standalone assignment changed before submission.")
        return browser.page_element_scope(_CONTROL_SELECTOR + ", #workpop #popok")

    def _top_controls(self, browser: Browser) -> AbstractContextManager[tuple[BrowserElement, ...]]:
        # 主页面作用域已包括确认控件，避免重复计数同一 popok。
        return nullcontext(())


class StandaloneAssignmentHandler(ChaoxingQuizTaskHandler):
    """复用已有作答流程，使用当前主页面代替嵌套的章节测验 frame。"""

    _form_fields: dict[str, str] | None = None

    def _answer_all(self) -> tuple[str, str]:
        self._form_fields = None
        return super()._answer_all()

    def _target(self) -> tuple[str, str]:
        state = inspect_assignment_page(self._browser)
        if not state.ready or state.submitted:
            raise ChaoxingQuizStateError("Standalone assignment is not ready for answering.")
        if state.submit_path != ASSIGNMENT_SUBMIT_PATH:
            raise ChaoxingQuizStateError("Standalone assignment has an unsupported submit form.")
        if not all(state.submit_fields.values()):
            raise ChaoxingQuizStateError("Standalone assignment form identity is missing.")
        identity = assignment_identity(state.url)
        if (
            identity is None
            or (state.submit_fields["courseId"], state.submit_fields["classId"]) != identity[1:3]
        ):
            raise ChaoxingQuizStateError("Standalone assignment course identity is inconsistent.")
        if self._form_fields is None:
            self._form_fields = state.submit_fields
        elif self._form_fields != state.submit_fields:
            raise ChaoxingQuizStateError("Standalone assignment form identity changed.")
        return state.url, state.url

    def _question_scope(self, module_url: str) -> AbstractContextManager[tuple[BrowserElement, ...]]:
        if self._browser.current_url() != module_url:
            raise ChaoxingQuizStateError("Standalone assignment changed while answering.")
        return self._browser.page_element_scope(ASSIGNMENT_QUESTION_SELECTOR)

    def _draft_scope(self, module_url: str) -> AbstractContextManager[tuple[BrowserElement, ...]]:
        if self._browser.current_url() != module_url:
            raise ChaoxingQuizStateError("Standalone assignment changed before draft save.")
        return self._browser.page_element_scope(DRAFT_CONTROL_SELECTOR)

    def _save_after_click(
        self, content_url: str, module_url: str, index: int, selected: frozenset[str]
    ) -> None:
        if self._form_fields is None:
            raise ChaoxingQuizStateError("Assignment form identity has not been verified before saving.")
        # 保存和提交共享端点，但 pyFlag 不同；仅被动观察普通 UI 产生的保存响应。
        with self._browser.capture_json_responses(
            ASSIGNMENT_SUBMIT_PATH, form_fields={"pyFlag": "1", **self._form_fields}
        ) as responses:
            try:
                super()._save_after_click(content_url, module_url, index, selected)
            except _QuizDraftClickedError:
                self._wait_for_draft_receipt(module_url, responses)
                raise

    def _wait_for_draft_receipt(self, module_url: str, responses: list[BrowserJSONResponse]) -> None:
        deadline = self._monotonic() + min(3.0, self._config.completion_timeout_seconds)
        while True:
            self._check_stop()
            if responses:
                try:
                    self._submission_confirmed(responses)
                except (ChaoxingQuizCompletionError, ChaoxingQuizSubmissionError) as exc:
                    raise ChaoxingQuizStateError(
                        "暂存响应未通过校验，已停止作答，请检查保存结果。"
                    ) from exc
                logger.info("作业暂存响应已确认")
                return
            if self._monotonic() >= deadline:
                logger.warning("已点击作业暂存，但未收到保存确认，请检查页面上的保存状态")
                return
            # 浏览器操作驱动同步 Playwright 的事件分发，让响应监听器收到结果。
            self._with_questions(module_url, lambda _elements: None)
            self._sleep(self._config.poll_interval_seconds)

    def _prepare_pending_quiz(self, content_url: str, module_url: str) -> None:
        # 独立作业已直接展示题目，没有章节入口需要点击。
        pass

    def _run(self) -> None:
        page_url, _ = self._answer_all()
        self._check_stop()
        if self._submitter is None:
            raise ChaoxingQuizSubmissionError("Assignment answers verified; no submitter configured.")
        if self._target() != (page_url, page_url):
            raise ChaoxingQuizSubmissionError("Standalone assignment changed before submission.")
        if self._form_fields is None:
            raise ChaoxingQuizSubmissionError("Assignment form identity has not been verified.")
        if isinstance(self._submitter, AssignmentSubmitter):
            self._submitter.check_stop = self._check_stop
        logger.info("Standalone assignment answers verified; submitting through normal UI")
        # 被动观察正常提交按钮发起的响应；不直接调用站点端点。
        # 观察到的 Save 会带 pyFlag=1；Submit 将该字段清空，保存成功不能作为完成证据。
        with self._browser.capture_json_responses(
            ASSIGNMENT_SUBMIT_PATH, form_fields={"pyFlag": "", **self._form_fields}
        ) as responses:
            try:
                self._submitter.submit(self._browser, module_url=page_url)
            except (BrowserError, ChaoxingQuizSubmissionError):
                # 成功响应后页面可能立即关闭，导致最后的控件句柄失效。
                if self._submission_confirmed(responses):
                    self._complete()
                    return
                raise
            deadline = self._monotonic() + self._config.completion_timeout_seconds
            while True:
                if self._submission_confirmed(responses):
                    self._complete()
                    return
                self._check_stop()
                try:
                    state = inspect_assignment_page(self._browser)
                    if assignment_identity(state.url) != assignment_identity(page_url):
                        raise ChaoxingQuizCompletionError("Assignment identity changed after submission.")
                    if state.submitted:
                        if responses:
                            self._submission_confirmed(responses)
                        self._complete()
                        return
                except BrowserClosedError as exc:
                    # 当前浏览器调用可能刚好派发成功响应，然后才观察到页面关闭。
                    if self._submission_confirmed(responses):
                        self._complete()
                        return
                    # 未观察到明确成功响应时，窗口关闭不算提交完成。
                    raise ChaoxingQuizCompletionError(
                        "Assignment closed without confirmed submission."
                    ) from exc
                except (BrowserError, ChaoxingQuizStateError):
                    pass
                if self._monotonic() >= deadline:
                    raise ChaoxingQuizCompletionError("Assignment submission could not be confirmed.")
                self._sleep(self._config.poll_interval_seconds)

    @staticmethod
    def _submission_confirmed(responses: list[BrowserJSONResponse]) -> bool:
        if len(responses) > 1:
            raise ChaoxingQuizCompletionError("Standalone submission result is ambiguous.")
        if not responses:
            return False
        response = responses[0]
        status = response.data.get("status") if isinstance(response.data, dict) else None
        if not 200 <= response.status < 300 or not (
            status is True or (type(status) is int and status == 1)
        ):
            raise ChaoxingQuizSubmissionError("Platform rejected the assignment submission.")
        return True

    def _complete(self) -> None:
        if not isinstance(self._detector, AssignmentDetector):
            raise ChaoxingQuizCompletionError("Assignment detector is not configured.")
        self._detector.completed = True
        logger.info("Standalone assignment submission confirmed")
