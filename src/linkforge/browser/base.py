"""
LinkForge 浏览器抽象接口。

本模块定义 LinkForge Browser Infrastructure 对上层暴露的统一浏览器能力。

设计目标：
1. 隔离具体浏览器自动化框架，例如 Playwright。
2. 为 Agent、Tools 和 Application 层提供稳定的浏览器接口。
3. 统一浏览器资源生命周期模型。
4. 为后续 FakeBrowser、测试替身以及其他 Browser Adapter 提供抽象基础。

注意：
本模块只定义“浏览器能够做什么”，不负责决定“浏览器应该做什么”。

具体浏览器操作由实现类负责，例如：
    Browser
        ↓
    PlaywrightBrowser
        ↓
    Playwright
        ↓
    Chromium

Observation、Action、Agent Loop 等更高层抽象不属于本模块职责。
"""

from abc import ABC, abstractmethod
from types import TracebackType
from typing import Self


class Browser(ABC):
    """
    LinkForge 浏览器统一抽象接口。

    Browser 表示一次浏览器运行实例，对 Browser、BrowserContext 和 Page
    等底层资源进行统一封装。

    上层模块只能依赖本接口，不应直接依赖 Playwright、Page、Locator
    或 BrowserContext 等具体实现类型。

    Browser 的基本生命周期为：

        start()
            ↓
        open()
            ↓
        read / interact
            ↓
        close()

    Browser 实现类应保证 close() 可以安全执行资源清理，即使前面的任务
    因异常而提前终止。
    """

    def __enter__(self) -> Self:
        """
        进入浏览器上下文并启动浏览器资源。

        允许使用以下形式管理浏览器生命周期：

            with PlaywrightBrowser(...) as browser:
                browser.open("https://example.com")

        Returns:
            当前 Browser 实例。
        """
        self.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        """
        退出浏览器上下文并释放浏览器资源。

        无论 with 代码块正常结束还是发生异常，都调用 close() 进行资源清理。

        Args:
            exc_type: 异常类型；正常退出时为 None。
            exc_value: 异常对象；正常退出时为 None。
            traceback: 异常 traceback；正常退出时为 None。

        Returns:
            固定返回 False，不吞掉业务异常，让异常继续向上层传播。
        """
        self.close()
        return False

    @abstractmethod
    def start(self) -> None:
        """
        启动浏览器运行环境。

        实现类通常需要完成以下资源初始化：

            Playwright Runtime
                ↓
            Browser
                ↓
            BrowserContext
                ↓
            Page

        本方法不得执行具体业务页面导航。

        Raises:
            BrowserError:
                浏览器运行环境启动失败时抛出。
        """
        raise NotImplementedError

    @abstractmethod
    def open(self, url: str) -> None:
        """
        打开指定 URL。

        浏览器必须已经通过 start() 完成初始化。

        Args:
            url: 需要访问的完整 URL。

        Raises:
            BrowserError:
                浏览器尚未启动、导航失败或发生其他浏览器错误时抛出。
        """
        raise NotImplementedError

    @abstractmethod
    def current_url(self) -> str:
        """
        获取当前页面 URL。

        Returns:
            当前 Page 所处页面的完整 URL。

        Raises:
            BrowserError:
                浏览器未启动或无法获取当前页面状态时抛出。
        """
        raise NotImplementedError

    @abstractmethod
    def title(self) -> str:
        """
        获取当前页面标题。

        Returns:
            当前网页的 title。

        Raises:
            BrowserError:
                浏览器未启动或无法读取页面标题时抛出。
        """
        raise NotImplementedError

    @abstractmethod
    def text(self) -> str:
        """
        获取当前页面的基础可见文本。

        本方法仅提供 Browser Infrastructure 阶段所需的原始页面文本读取能力，
        不负责生成结构化 Observation。

        后续 Observation Infrastructure 将基于 Browser 能力进一步提取和组织
        Agent 所需的网页状态。

        Returns:
            当前页面的基础文本内容。

        Raises:
            BrowserError:
                页面文本读取失败时抛出。
        """
        raise NotImplementedError

    @abstractmethod
    def click(self, selector: str) -> None:
        """
        点击由 selector 指定的页面元素。

        Args:
            selector: 用于定位页面元素的选择器。

        Raises:
            BrowserError:
                元素不存在、不可交互、操作超时或点击失败时抛出。
        """
        raise NotImplementedError

    @abstractmethod
    def fill(self, selector: str, text: str) -> None:
        """
        向指定输入元素填写文本。

        Args:
            selector: 用于定位输入元素的选择器。
            text: 需要填写的文本内容。

        Raises:
            BrowserError:
                元素不存在、元素不可编辑或填写失败时抛出。
        """
        raise NotImplementedError

    @abstractmethod
    def press(self, selector: str, key: str) -> None:
        """
        向指定页面元素发送键盘按键。

        Args:
            selector: 用于定位目标元素的选择器。
            key: 需要发送的按键名称，例如 "Enter"、"Escape"。

        Raises:
            BrowserError:
                元素不存在或键盘操作失败时抛出。
        """
        raise NotImplementedError

    @abstractmethod
    def scroll(self, delta_y: int) -> None:
        """
        在当前页面执行垂直滚动。

        Args:
            delta_y:
                垂直滚动距离，单位为 CSS pixel。
                正值表示向下滚动，负值表示向上滚动。

        Raises:
            BrowserError:
                页面不可用或滚动操作失败时抛出。
        """
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        """
        关闭浏览器并释放所有相关资源。

        实现类应依次清理自己持有的 Page、BrowserContext、Browser
        以及底层浏览器运行环境。

        close() 应尽可能设计为幂等操作，即重复调用不应因为资源已经释放
        而导致新的异常。

        该特性非常重要，因为 Application 层未来会采用类似：

            try:
                ...
            finally:
                browser.close()

        的方式保证异常情况下仍能释放外部资源。
        """
        raise NotImplementedError
