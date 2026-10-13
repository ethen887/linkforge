"""平台无关的应用生命周期编排。"""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from linkforge.application.task_runner import TaskRunner
from linkforge.browser.base import Browser
from linkforge.browser.factory import create_browser
from linkforge.config.settings import BrowserConfig, ModelConfig
from linkforge.llm.base import LLM
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

    def run(self) -> None:
        """运行直至平台完成、在任务边界停止或发生错误。"""
        logger.info("Application run started")
        try:
            browser = self._browser_factory(self._config.browser_config)
            llm = self._llm_factory(self._config.model_config)

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
                runner.run(should_stop=self._should_stop)
                logger.info("Platform runtime completed")
        except BaseException:
            logger.exception("Application runtime failed")
            raise
        finally:
            logger.info("Application cleanup finished")

    def stop(self) -> None:
        """请求在准备期间或下一个任务边界处停止。"""
        self._stop_requested = True
        logger.info("Application stop requested")

    def _should_stop(self) -> bool:
        return self._stop_requested
