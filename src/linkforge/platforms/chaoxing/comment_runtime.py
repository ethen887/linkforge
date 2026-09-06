"""Composition helpers for one Chaoxing comment-handling application run."""

from dataclasses import dataclass

from linkforge.browser.base import Browser
from linkforge.config.settings import ModelConfig
from linkforge.llm.factory import create_model_client
from linkforge.platforms.chaoxing.comment_handler import (
    ChaoxingCommentTaskHandler,
    LLMCommentBodyGenerator,
)
from linkforge.platforms.chaoxing.comment_state import CommentSession
from linkforge.platforms.chaoxing.content_handler import ChaoxingContentTaskHandler
from linkforge.platforms.chaoxing.task_detector import ChaoxingTaskDetector


@dataclass(frozen=True, slots=True)
class ChaoxingCommentComponents:
    session: CommentSession
    detector: ChaoxingTaskDetector
    comment_handler: ChaoxingCommentTaskHandler
    content_handler: ChaoxingContentTaskHandler


def create_chaoxing_comment_components(
    browser: Browser, model_config: ModelConfig
) -> ChaoxingCommentComponents:
    """Create components that share exactly one run-scoped comment session."""
    session = CommentSession()
    detector = ChaoxingTaskDetector(browser, comment_session=session)
    generator = LLMCommentBodyGenerator(
        llm=create_model_client(model_config), model=model_config.model_name
    )
    return ChaoxingCommentComponents(
        session=session,
        detector=detector,
        comment_handler=ChaoxingCommentTaskHandler(
            browser,
            comment_session=session,
            body_generator=generator,
            detector=detector,
        ),
        content_handler=ChaoxingContentTaskHandler(browser, detector=detector),
    )
