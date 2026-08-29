"""
LinkForge Playwright 浏览器实现。

本模块负责使用 Playwright 实现 LinkForge 定义的 Browser 抽象接口。

职责：
1. 启动和关闭 Playwright Runtime。
2. 创建和管理 Chromium Browser。
3. 创建和管理 BrowserContext。
4. 创建和管理 Page。
5. 实现页面导航、读取和基础交互能力。
6. 将 Playwright 底层异常转换为 LinkForge Browser 异常。

依赖关系：

    Agent / Tools / Application
              ↓
           Browser
              ↓
      PlaywrightBrowser
              ↓
          Playwright
              ↓
           Chromium

本模块属于基础设施实现层，不负责：
- Agent 决策；
- Observation 构建；
- Action 规划；
- 具体网站业务逻辑。
"""

from __future__ import annotations

from playwright.sync_api import (
    Browser as PlaywrightNativeBrowser,
)
from playwright.sync_api import (
    BrowserContext,
    Page,
    Playwright,
    sync_playwright,
)
from playwright.sync_api import (
    Error as PlaywrightError,
)
from playwright.sync_api import (
    TimeoutError as PlaywrightTimeoutError,
)

from .base import Browser
from .exceptions import (
    BrowserClosedError,
    BrowserElementError,
    BrowserError,
    BrowserNavigationError,
    BrowserStartError,
    BrowserTimeoutError,
)


class PlaywrightBrowser(Browser):
    """
    基于 Playwright Sync API 的 Browser 实现。

    当前实现采用以下资源模型：

        Playwright Runtime
                ↓
             Browser
                ↓
         BrowserContext
                ↓
              Page

    第一阶段仅管理：
    - 一个 Browser；
    - 一个 BrowserContext；
    - 一个 Page。

    暂不支持多标签页、多 Context、持久化 Cookie 等复杂能力。

    Args:
        headless:
            是否使用无头模式运行 Chromium。
            False 时可以看到浏览器窗口，适合开发和调试。
        timeout_ms:
            默认操作与导航超时时间，单位为毫秒。

    Raises:
        ValueError:
            timeout_ms 小于等于 0 时抛出。
    """

    def __init__(
        self,
        *,
        headless: bool = False,
        timeout_ms: int = 15_000,
    ) -> None:
        if timeout_ms <= 0:
            raise ValueError("timeout_ms must be greater than 0")

        self._headless = headless
        self._timeout_ms = timeout_ms

        self._playwright: Playwright | None = None
        self._browser: PlaywrightNativeBrowser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    def start(self) -> None:
        """
        启动 Playwright 浏览器运行环境。

        初始化顺序：

            sync_playwright()
                    ↓
                Chromium
                    ↓
             BrowserContext
                    ↓
                  Page

        如果浏览器已经正常启动，则重复调用本方法不会再次创建新资源。

        Raises:
            BrowserStartError:
                Playwright Runtime、Chromium、Context 或 Page 创建失败。
        """
        if self._page is not None and not self._page.is_closed():
            return

        # 防止上一次初始化过程只创建了部分资源。
        self._close_resources()

        try:
            self._playwright = sync_playwright().start()

            self._browser = self._playwright.chromium.launch(
                headless=self._headless,
            )

            self._context = self._browser.new_context()

            self._page = self._context.new_page()

            self._page.set_default_timeout(self._timeout_ms)
            self._page.set_default_navigation_timeout(self._timeout_ms)

        except Exception as exc:
            # 启动过程中任何一步失败，都需要清理已经创建的部分资源。
            self._close_resources()

            raise BrowserStartError("Failed to start Playwright browser.") from exc

    def open(self, url: str) -> None:
        """
        打开指定 URL。

        Args:
            url:
                需要访问的完整 URL。

        Raises:
            ValueError:
                URL 为空。
            BrowserClosedError:
                Browser 尚未启动或 Page 已关闭。
            BrowserTimeoutError:
                页面导航超过配置的超时时间。
            BrowserNavigationError:
                页面导航发生其他 Playwright 错误。
        """
        if not url.strip():
            raise ValueError("url must not be empty")

        page = self._require_page()

        try:
            page.goto(
                url,
                timeout=self._timeout_ms,
            )

        except PlaywrightTimeoutError as exc:
            raise BrowserTimeoutError(f"Timed out while navigating to URL: {url}") from exc

        except PlaywrightError as exc:
            raise BrowserNavigationError(f"Failed to navigate to URL: {url}") from exc

    def current_url(self) -> str:
        """
        获取当前页面 URL。

        Returns:
            当前页面完整 URL。

        Raises:
            BrowserClosedError:
                Browser 尚未启动或 Page 已关闭。
        """
        page = self._require_page()
        return page.url

    def title(self) -> str:
        """
        获取当前页面标题。

        Returns:
            当前网页的 title。

        Raises:
            BrowserClosedError:
                Browser 尚未启动或 Page 已关闭。
            BrowserError:
                Playwright 无法读取页面标题。
        """
        page = self._require_page()

        try:
            return page.title()

        except PlaywrightError as exc:
            raise BrowserError("Failed to read page title.") from exc

    def text(self) -> str:
        """
        获取当前页面的基础文本内容。

        当前阶段直接读取 body 的 innerText。

        本方法只提供 Browser Infrastructure 所需的基础文本读取能力，
        不负责过滤、压缩、结构化或生成 Observation。

        Returns:
            当前页面 body 中的文本内容。

        Raises:
            BrowserClosedError:
                Browser 尚未启动或 Page 已关闭。
            BrowserTimeoutError:
                获取页面文本超时。
            BrowserError:
                获取页面文本发生其他错误。
        """
        page = self._require_page()

        try:
            return page.locator("body").inner_text(
                timeout=self._timeout_ms,
            )

        except PlaywrightTimeoutError as exc:
            raise BrowserTimeoutError("Timed out while reading page text.") from exc

        except PlaywrightError as exc:
            raise BrowserError("Failed to read page text.") from exc

    def click(self, selector: str) -> None:
        """
        点击指定页面元素。

        使用 Playwright Locator API 完成元素定位和点击。

        Args:
            selector:
                用于定位页面元素的选择器。

        Raises:
            ValueError:
                selector 为空。
            BrowserClosedError:
                Browser 尚未启动或 Page 已关闭。
            BrowserTimeoutError:
                等待元素可交互超时。
            BrowserElementError:
                元素定位或点击发生其他错误。
        """
        if not selector.strip():
            raise ValueError("selector must not be empty")

        page = self._require_page()

        try:
            page.locator(selector).click(
                timeout=self._timeout_ms,
            )

        except PlaywrightTimeoutError as exc:
            raise BrowserTimeoutError(f"Timed out while clicking element: {selector}") from exc

        except PlaywrightError as exc:
            raise BrowserElementError(f"Failed to click element: {selector}") from exc

    def fill(
        self,
        selector: str,
        text: str,
    ) -> None:
        """
        向指定输入元素填写文本。

        Args:
            selector:
                用于定位输入元素的选择器。
            text:
                需要填写的文本内容。

        Raises:
            ValueError:
                selector 为空。
            BrowserClosedError:
                Browser 尚未启动或 Page 已关闭。
            BrowserTimeoutError:
                等待输入元素超时。
            BrowserElementError:
                元素不可编辑或填写失败。
        """
        if not selector.strip():
            raise ValueError("selector must not be empty")

        page = self._require_page()

        try:
            page.locator(selector).fill(
                text,
                timeout=self._timeout_ms,
            )

        except PlaywrightTimeoutError as exc:
            raise BrowserTimeoutError(f"Timed out while filling element: {selector}") from exc

        except PlaywrightError as exc:
            raise BrowserElementError(f"Failed to fill element: {selector}") from exc

    def press(
        self,
        selector: str,
        key: str,
    ) -> None:
        """
        向指定页面元素发送键盘按键。

        Args:
            selector:
                用于定位目标元素的选择器。
            key:
                Playwright 支持的按键名称，例如：
                "Enter"、"Escape"、"Tab"。

        Raises:
            ValueError:
                selector 或 key 为空。
            BrowserClosedError:
                Browser 尚未启动或 Page 已关闭。
            BrowserTimeoutError:
                等待元素超时。
            BrowserElementError:
                键盘操作失败。
        """
        if not selector.strip():
            raise ValueError("selector must not be empty")

        if not key.strip():
            raise ValueError("key must not be empty")

        page = self._require_page()

        try:
            page.locator(selector).press(
                key,
                timeout=self._timeout_ms,
            )

        except PlaywrightTimeoutError as exc:
            raise BrowserTimeoutError(f"Timed out while pressing key on element: {selector}") from exc

        except PlaywrightError as exc:
            raise BrowserElementError(f"Failed to press key '{key}' on element: {selector}") from exc

    def scroll(self, delta_y: int) -> None:
        """
        在当前页面执行垂直滚动。

        Args:
            delta_y:
                垂直滚动距离，单位为 CSS pixel。
                正值向下滚动，负值向上滚动。

        Raises:
            BrowserClosedError:
                Browser 尚未启动或 Page 已关闭。
            BrowserError:
                页面滚动操作失败。
        """
        page = self._require_page()

        try:
            page.mouse.wheel(
                0,
                delta_y,
            )

        except PlaywrightError as exc:
            raise BrowserError(f"Failed to scroll page by delta_y={delta_y}.") from exc

    def close(self) -> None:
        """
        关闭浏览器并释放所有相关资源。

        清理顺序：

            Page
              ↓
        BrowserContext
              ↓
           Browser
              ↓
        Playwright Runtime

        本方法设计为幂等操作。

        即使：
            browser.close()
            browser.close()

        被重复调用，也不会因为资源已经释放而失败。

        Raises:
            BrowserError:
                资源清理过程中发生错误。

        Note:
            即使某个资源关闭失败，本方法仍会继续尝试释放其余资源，
            避免因为一次清理失败导致更多资源泄漏。
        """
        errors = self._close_resources()

        if errors:
            first_error = errors[0]

            raise BrowserError(f"Browser cleanup completed with {len(errors)} error(s).") from first_error

    def _require_page(self) -> Page:
        """
        获取当前可用 Page。

        Returns:
            当前有效的 Playwright Page。

        Raises:
            BrowserClosedError:
                Browser 尚未启动或 Page 已关闭。
        """
        if self._page is None:
            raise BrowserClosedError("Browser has not been started. Call start() first.")

        if self._page.is_closed():
            raise BrowserClosedError("Browser page has already been closed.")

        return self._page

    def _close_resources(self) -> list[Exception]:
        """
        尽最大努力释放 Browser 持有的全部底层资源。

        本方法不会主动抛出资源关闭异常，而是将异常收集后返回，
        以避免一个资源清理失败阻止其他资源继续释放。

        Returns:
            资源清理过程中捕获到的异常列表。
            没有异常时返回空列表。
        """
        errors: list[Exception] = []

        page = self._page
        self._page = None

        if page is not None:
            try:
                if not page.is_closed():
                    page.close()
            except Exception as exc:
                errors.append(exc)

        context = self._context
        self._context = None

        if context is not None:
            try:
                context.close()
            except Exception as exc:
                errors.append(exc)

        browser = self._browser
        self._browser = None

        if browser is not None:
            try:
                browser.close()
            except Exception as exc:
                errors.append(exc)

        playwright = self._playwright
        self._playwright = None

        if playwright is not None:
            try:
                playwright.stop()
            except Exception as exc:
                errors.append(exc)

        return errors
