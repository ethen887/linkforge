"""学习通单次运行的应用装配根（composition root）。"""

import logging
from collections.abc import Callable

from linkforge.application.runtime import PlatformRuntime
from linkforge.application.task_runner import TaskRunner
from linkforge.browser.base import Browser
from linkforge.llm.base import LLM
from linkforge.platforms.chaoxing.assignment_handler import (
    AssignmentDetector,
    AssignmentSubmitter,
)
from linkforge.platforms.chaoxing.assignment_page import assignment_identity
from linkforge.platforms.chaoxing.comment_handler import (
    ChaoxingCommentTaskHandler,
    LLMCommentBodyGenerator,
)
from linkforge.platforms.chaoxing.comment_state import CommentSession
from linkforge.platforms.chaoxing.content_handler import ChaoxingContentTaskHandler
from linkforge.platforms.chaoxing.document_handler import ChaoxingDocumentTaskHandler
from linkforge.platforms.chaoxing.innerbook import InnerbookSession
from linkforge.platforms.chaoxing.navigation import ChaoxingNavigationMonitor
from linkforge.platforms.chaoxing.quiz_handler import ChaoxingQuizTaskHandler, QuizSubmitter
from linkforge.platforms.chaoxing.quiz_solver import LLMQuizSolver
from linkforge.platforms.chaoxing.recovery import ChaoxingTaskRecovery
from linkforge.platforms.chaoxing.startup import ChaoxingStartupWait
from linkforge.platforms.chaoxing.task_detector import ChaoxingTaskDetector
from linkforge.platforms.chaoxing.video_handler import ChaoxingVideoTaskHandler
from linkforge.platforms.chaoxing.video_state import VideoSession
from linkforge.platforms.chaoxing.written_answer import LLMWrittenSolver
from linkforge.platforms.chaoxing.written_assignment import DraftingAssignmentHandler
from linkforge.platforms.chaoxing.written_review import LLMWrittenReviewer

logger = logging.getLogger(__name__)


class ChaoxingPlatformRuntime(PlatformRuntime):
    """基于应用所拥有的资源构建完整的学习通任务运行器。"""

    def __init__(
        self,
        *,
        quiz_submitter: QuizSubmitter,
        startup_wait: ChaoxingStartupWait | None = None,
        on_course_url_changed: Callable[[str], None] | None = None,
    ) -> None:
        """接收测验提交器与可选的启动等待、课程 URL 变化回调，组合本次运行所需依赖。"""
        self._quiz_submitter = quiz_submitter
        self._startup_wait = startup_wait or ChaoxingStartupWait()
        self._on_course_url_changed = on_course_url_changed
        logger.debug("Chaoxing platform runtime created")

    def prepare(self, *, browser: Browser, course_url: str, should_stop: Callable[[], bool]) -> bool:
        """等待手动登录及课程页面就绪后再构建任务。"""
        return self._startup_wait.wait(browser=browser, course_url=course_url, should_stop=should_stop)

    def build_runner(self, *, browser: Browser, llm: LLM, model: str) -> TaskRunner:
        """为本次运行创建学习通状态、处理器与任务运行器。"""
        logger.info("Building Chaoxing task workflow")
        if assignment_identity(browser.current_url()) is not None:
            assignment_detector = AssignmentDetector(browser)
            handler = DraftingAssignmentHandler(
                browser,
                solver=LLMQuizSolver(llm=llm, model=model),
                submitter=AssignmentSubmitter(),
                detector=assignment_detector,
            )
            handler.written_solver = LLMWrittenSolver(llm=llm, model=model)
            handler.written_reviewer = LLMWrittenReviewer(llm=llm, model=model)
            logger.info("Standalone assignment workflow ready")
            return TaskRunner(
                detector=assignment_detector,
                video_handler=handler,
                document_handler=handler,
                content_handler=handler,
                comment_handler=handler,
                quiz_handler=handler,
            )
        comment_session = CommentSession()
        video_session = VideoSession()
        innerbook_session = InnerbookSession()
        navigation = ChaoxingNavigationMonitor(browser, on_course_url_changed=self._on_course_url_changed)
        detector = ChaoxingTaskDetector(
            browser,
            comment_session=comment_session,
            video_session=video_session,
            innerbook_session=innerbook_session,
        )
        quiz_solver = LLMQuizSolver(llm=llm, model=model)
        comment_generator = LLMCommentBodyGenerator(llm=llm, model=model)
        content_handler = ChaoxingContentTaskHandler(
            browser, detector=detector, on_course_url_changed=self._on_course_url_changed
        )

        runner = TaskRunner(
            detector=detector,
            video_handler=ChaoxingVideoTaskHandler(
                browser, video_session=video_session, navigation=navigation
            ),
            document_handler=ChaoxingDocumentTaskHandler(
                browser,
                innerbook_session=innerbook_session,
                video_session=video_session,
            ),
            content_handler=content_handler,
            quiz_handler=ChaoxingQuizTaskHandler(
                browser,
                solver=quiz_solver,
                submitter=self._quiz_submitter,
                detector=detector,
            ),
            comment_handler=ChaoxingCommentTaskHandler(
                browser,
                comment_session=comment_session,
                body_generator=comment_generator,
                detector=detector,
                video_session=video_session,
            ),
            recovery=ChaoxingTaskRecovery(
                browser, content_handler, video_session=video_session, navigation=navigation
            ),
        )
        logger.info("Chaoxing task workflow ready")
        return runner
