"""Composition root for one Chaoxing application run."""

import logging

from linkforge.application.runtime import PlatformRuntime
from linkforge.application.task_runner import TaskRunner
from linkforge.browser.base import Browser
from linkforge.llm.base import LLM
from linkforge.platforms.chaoxing.comment_handler import (
    ChaoxingCommentTaskHandler,
    LLMCommentBodyGenerator,
)
from linkforge.platforms.chaoxing.comment_state import CommentSession
from linkforge.platforms.chaoxing.content_handler import ChaoxingContentTaskHandler
from linkforge.platforms.chaoxing.document_handler import ChaoxingDocumentTaskHandler
from linkforge.platforms.chaoxing.quiz_handler import ChaoxingQuizTaskHandler, QuizSubmitter
from linkforge.platforms.chaoxing.quiz_solver import LLMQuizSolver
from linkforge.platforms.chaoxing.task_detector import ChaoxingTaskDetector
from linkforge.platforms.chaoxing.video_handler import ChaoxingVideoTaskHandler

logger = logging.getLogger(__name__)


class ChaoxingPlatformRuntime(PlatformRuntime):
    """Build the complete Chaoxing task runner from application-owned resources."""

    def __init__(self, *, quiz_submitter: QuizSubmitter) -> None:
        self._quiz_submitter = quiz_submitter
        logger.debug("Chaoxing platform runtime created")

    def build_runner(self, *, browser: Browser, llm: LLM, model: str) -> TaskRunner:
        """Create run-scoped Chaoxing state, handlers, and task runner."""
        logger.info("Building Chaoxing task workflow")
        comment_session = CommentSession()
        detector = ChaoxingTaskDetector(browser, comment_session=comment_session)
        quiz_solver = LLMQuizSolver(llm=llm, model=model)
        comment_generator = LLMCommentBodyGenerator(llm=llm, model=model)

        runner = TaskRunner(
            detector=detector,
            video_handler=ChaoxingVideoTaskHandler(browser),
            document_handler=ChaoxingDocumentTaskHandler(browser),
            content_handler=ChaoxingContentTaskHandler(browser, detector=detector),
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
            ),
        )
        logger.info("Chaoxing task workflow ready")
        return runner
