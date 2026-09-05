"""
LinkForge 浏览器抽象接口。

本模块定义 Browser Infrastructure 对上层暴露的统一浏览器能力，
用于隔离 Playwright 等具体浏览器自动化实现。

Browser 只描述“浏览器能够做什么”，不负责决定“浏览器应该做什么”。
Observation、Action 和 Agent Loop 等上层逻辑不属于本模块职责。
"""

from abc import ABC, abstractmethod
from types import TracebackType
from typing import Literal, Self

from linkforge.browser.models import InteractiveElement


class Browser(ABC):
    """
    LinkForge 浏览器统一抽象接口。

    Browser 对一次浏览器运行实例进行抽象，并统一管理浏览器资源生命周期。
    上层模块应依赖本接口，而不是直接依赖 Playwright、Page 或 BrowserContext。

    基本生命周期：

        start()
            ↓
        open()
            ↓
        read / interact
            ↓
        close()

    实现类应保证资源能够在正常退出和异常退出时被可靠释放。
    """

    def __enter__(self) -> Self:
        """
        启动浏览器并进入上下文管理器。

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
    ) -> Literal[False]:
        """
        退出上下文并释放浏览器资源。

        无论代码块正常结束还是发生异常，都执行资源清理。
        固定返回 False，使业务异常继续向上层传播。

        Args:
            exc_type: 异常类型，正常退出时为 None。
            exc_value: 异常对象，正常退出时为 None。
            traceback: 异常 traceback，正常退出时为 None。

        Returns:
            固定返回 False。
        """
        self.close()
        return False

    @abstractmethod
    def start(self) -> None:
        """
        启动浏览器运行环境。

        实现类应完成底层运行时、Browser、BrowserContext 和 Page 等资源初始化。
        本方法只负责基础设施初始化，不执行具体页面导航。

        Raises:
            BrowserError: 浏览器启动失败时抛出。
        """
        raise NotImplementedError

    @abstractmethod
    def open(self, url: str) -> None:
        """
        打开指定 URL。

        Args:
            url: 需要访问的完整 URL。

        Raises:
            BrowserError: 浏览器未启动、导航失败或发生其他浏览器错误时抛出。
        """
        raise NotImplementedError

    @abstractmethod
    def current_url(self) -> str:
        """
        获取当前页面 URL。

        Returns:
            当前页面的完整 URL。

        Raises:
            BrowserError: 浏览器未启动或无法获取页面状态时抛出。
        """
        raise NotImplementedError

    @abstractmethod
    def title(self) -> str:
        """
        获取当前页面标题。

        Returns:
            当前页面标题。

        Raises:
            BrowserError: 浏览器未启动或标题读取失败时抛出。
        """
        raise NotImplementedError

    @abstractmethod
    def text(self) -> str:
        """
        获取当前页面的基础可见文本。

        本方法只提供原始文本读取能力，不负责构造结构化 Observation。

        Returns:
            当前页面的基础文本内容。

        Raises:
            BrowserError: 页面文本读取失败时抛出。
        """
        raise NotImplementedError

    @abstractmethod
    def interactive_elements(self) -> tuple[InteractiveElement, ...]:
        """
        Discover interactive elements in the current page snapshot.

        Calling this method refreshes the logical target mapping and invalidates
        IDs from an earlier discovery. Navigation or DOM replacement can also
        make IDs from the current mapping stale.

        Returns:
            Browser-neutral elements with logical target IDs.

        Raises:
            BrowserError: Browser state cannot be inspected.
        """
        raise NotImplementedError

    @abstractmethod
    def evaluate_in_frames(self, expression: str) -> tuple[object, ...]:
        """Evaluate a trusted provider-neutral page expression in every frame.

        Results are returned in frame order as plain Python values, without
        exposing provider-specific frame objects. Frames detached during a
        dynamic-page evaluation may be omitted. Platform adapters may use this
        primitive for deterministic DOM inspection or normal page behavior such
        as requesting HTML media playback; the expression must not forge site state.

        Args:
            expression: JavaScript expression to evaluate in each frame.

        Returns:
            Provider-neutral evaluation results for successfully inspected frames.

        Raises:
            BrowserError: The page or one of its frames cannot be inspected.
        """
        raise NotImplementedError

    @abstractmethod
    def click_target(self, target_id: int) -> None:
        """
        Click an element discovered in the current page snapshot.

        Args:
            target_id: Logical target ID returned by interactive_elements().

        Raises:
            BrowserError: The target is unknown, stale, or cannot be clicked.
        """
        raise NotImplementedError

    @abstractmethod
    def fill_target(self, target_id: int, text: str) -> None:
        """
        Fill an element discovered in the current page snapshot.

        Args:
            target_id: Logical target ID returned by interactive_elements().
            text: Text to enter.

        Raises:
            BrowserError: The target is unknown, stale, or cannot be filled.
        """
        raise NotImplementedError

    @abstractmethod
    def press_target(self, target_id: int, key: str) -> None:
        """
        Send a key press to an element in the current page snapshot.

        Args:
            target_id: Logical target ID returned by interactive_elements().
            key: Key name, such as "Enter" or "Escape".

        Raises:
            BrowserError: The target is unknown, stale, or cannot receive the key press.
        """
        raise NotImplementedError

    @abstractmethod
    def click(self, selector: str) -> None:
        """
        点击指定页面元素。

        Args:
            selector: 用于定位页面元素的选择器。

        Raises:
            BrowserError: 元素不可用、操作超时或点击失败时抛出。
        """
        raise NotImplementedError

    @abstractmethod
    def fill(self, selector: str, text: str) -> None:
        """
        向指定输入元素填写文本。

        Args:
            selector: 用于定位输入元素的选择器。
            text: 需要填写的文本。

        Raises:
            BrowserError: 元素不可编辑或填写失败时抛出。
        """
        raise NotImplementedError

    @abstractmethod
    def press(self, selector: str, key: str) -> None:
        """
        向指定页面元素发送按键。

        Args:
            selector: 用于定位目标元素的选择器。
            key: 按键名称，例如 "Enter" 或 "Escape"。

        Raises:
            BrowserError: 元素不可用或按键操作失败时抛出。
        """
        raise NotImplementedError

    @abstractmethod
    def scroll(self, delta_y: int) -> None:
        """
        在当前页面执行垂直滚动。

        Args:
            delta_y: 垂直滚动距离，单位为 CSS pixel。
                正值向下滚动，负值向上滚动。

        Raises:
            BrowserError: 页面不可用或滚动失败时抛出。
        """
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        """
        关闭浏览器并释放相关资源。

        实现类应释放自身持有的 Page、BrowserContext、Browser 及底层运行时资源。
        close() 应尽可能保持幂等，使重复清理不会产生额外异常。
        """
        raise NotImplementedError
