"""Platform-neutral application lifecycle orchestration."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from linkforge.application.task_runner import TaskRunner
from linkforge.browser.base import Browser
from linkforge.browser.factory import create_browser
from linkforge.config.settings import BrowserConfig, ModelConfig
from linkforge.llm.base import LLM
from linkforge.llm.factory import create_model_client

BrowserFactory = Callable[[BrowserConfig], Browser]
LLMFactory = Callable[[ModelConfig], LLM]


@dataclass(frozen=True, slots=True)
class ApplicationConfig:
    """Platform-neutral configuration for one LinkForge application run."""

    course_url: str
    browser_config: BrowserConfig
    model_config: ModelConfig

    def __post_init__(self) -> None:
        if not self.course_url.strip():
            raise ValueError("course_url must not be empty")


class PlatformRuntime(Protocol):
    """Build a platform-specific task runner from application-owned resources."""

    def build_runner(self, *, browser: Browser, llm: LLM, model: str) -> TaskRunner:
        """Create the complete task runner for one platform run."""
        ...


class LinkForgeApplication:
    """Own resources and execute one synchronous LinkForge application run."""

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
        """Run until platform completion, a task-boundary stop, or an error."""
        browser = self._browser_factory(self._config.browser_config)
        llm = self._llm_factory(self._config.model_config)

        with browser:
            browser.open(self._config.course_url)
            runner = self._platform.build_runner(
                browser=browser,
                llm=llm,
                model=self._config.model_config.model_name,
            )
            runner.run(should_stop=self._should_stop)

    def stop(self) -> None:
        """Request a stop at the next TaskRunner task boundary."""
        self._stop_requested = True

    def _should_stop(self) -> bool:
        return self._stop_requested
