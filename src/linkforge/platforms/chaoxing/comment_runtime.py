"""为某一次学习通评论处理应用运行提供的组装辅助函数。"""

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
    """本次评论处理运行所需的组件集合。"""

    session: CommentSession
    detector: ChaoxingTaskDetector
    comment_handler: ChaoxingCommentTaskHandler
    content_handler: ChaoxingContentTaskHandler


def create_chaoxing_comment_components(
    browser: Browser, model_config: ModelConfig
) -> ChaoxingCommentComponents:
    """创建共享同一个单次运行范围内评论会话的组件。"""
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
