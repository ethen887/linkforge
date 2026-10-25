"""平台无关的应用生命周期编排。"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from linkforge.application.issues import RunIssue
from linkforge.application.task_runner import TaskReviewRequiredError, TaskRunner
from linkforge.browser.base import Browser
from linkforge.browser.exceptions import BrowserError
from linkforge.browser.factory import create_browser
from linkforge.config.settings import BrowserConfig, ModelConfig
from linkforge.llm.base import LLM
from linkforge.llm.errors import ModelRequestCancelledError
from linkforge.llm.factory import create_model_client

BrowserFactory = Callable[[BrowserConfig], Browser]
LLMFactory = Callable[[ModelConfig], LLM]

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ApplicationConfig:
    """单次 LinkForge 应用运行的平台无关配置。"""

    course_url: str
    browser_config: BrowserConfig
    model_config: ModelConfig
    on_course_url_changed: Callable[[str], None] | None = field(default=None, repr=False, compare=False)
    on_review_required: Callable[[bool], None] | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not self.course_url.strip():
            raise ValueError("course_url must not be empty")


class PlatformRuntime(Protocol):
    """根据应用持有的资源准备课程就绪状态并构建任务。"""

    def prepare(self, *, browser: Browser, course_url: str, should_stop: Callable[[], bool]) -> bool:
        """等待平台启动就绪；停止时返回 False。"""
        ...

    def build_runner(self, *, browser: Browser, llm: LLM, model: str) -> TaskRunner:
        """为单次平台运行创建完整的任务执行器。"""
        ...


class LinkForgeApplication:
    """持有资源并执行一次同步的 LinkForge 应用运行。"""

    def __init__(
        self,
        *,
        config: ApplicationConfig,
        platform: PlatformRuntime,
        browser_factory: BrowserFactory = create_browser,
        llm_factory: LLMFactory = create_model_client,
    ) -> None:
        self._config = config
        self._platform = platform
        self._browser_factory = browser_factory
        self._llm_factory = llm_factory
        self._stop_requested = False
        self.issues: list[RunIssue] = []
        self.review_required = False

    def run(self) -> None:
        """运行直至平台完成、响应停止请求或发生错误。"""
        logger.info("Application run started")
        llm: LLM | None = None
        try:
            browser = self._browser_factory(self._config.browser_config)
            llm = self._llm_factory(self._config.model_config)
            llm.configure_runtime(should_stop=self._should_stop)

            with browser:
                logger.info("Browser started")
                browser.open_for_readiness(self._config.course_url)
                logger.debug("Course page opened")
                if not self._platform.prepare(
                    browser=browser,
                    course_url=self._config.course_url,
                    should_stop=self._should_stop,
                ):
                    logger.info("Application stopped during platform preparation")
                    return
                runner = self._platform.build_runner(
                    browser=browser,
                    llm=llm,
                    model=self._config.model_config.model_name,
                )
                self.issues = getattr(runner, "issues", [])
                try:
                    runner.run(should_stop=self._should_stop)
                except TaskReviewRequiredError as review:
                    self.review_required = True
                    logger.info("草稿处理已暂停，等待人工检查；停止后关闭浏览器")
                    if self._config.on_review_required is not None:
                        self._config.on_review_required(review.saved)
                    # 保留浏览器供人工修改及提交；此处不再分派任务或判断平台完成。
                    while not self._should_stop():
                        try:
                            browser.evaluate_in_frames("() => null")
                        except BrowserError:
                            break
                        time.sleep(0.2)
                    return
                logger.info("Platform runtime completed")
        except ModelRequestCancelledError:
            if not self._should_stop():
                raise
            logger.info("Application model request cancelled")
        except BaseException as exc:
            logger.error("Application runtime failed (%s)", type(exc).__name__)
            raise
        finally:
            if llm is not None:
                llm.close()
            logger.info("Application cleanup finished")

    def stop(self) -> None:
        """请求停止，由准备流程或支持中断的任务响应并清理资源。"""
        self._stop_requested = True
        logger.info("Application stop requested")

    def _should_stop(self) -> bool:
        return self._stop_requested
