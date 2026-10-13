"""
LinkForge 浏览器抽象接口。

本模块定义 Browser Infrastructure 对上层暴露的统一浏览器能力，
用于隔离 Playwright 等具体浏览器自动化实现。

Browser 只描述“浏览器能够做什么”，不负责决定“浏览器应该做什么”。
Observation、Action 和 Agent Loop 等上层逻辑不属于本模块职责。
"""

from abc import ABC, abstractmethod
from contextlib import AbstractContextManager
from types import TracebackType
from typing import Literal, Self

from linkforge.browser.element import BrowserElement
from linkforge.browser.exceptions import BrowserError
from linkforge.browser.models import BrowserPage, InteractiveElement


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

    def element_scope(
        self, frame_url_contains: str, selector: str, *, ancestor_url: str
    ) -> AbstractContextManager[tuple[BrowserElement, ...]]:
        """在指定祖先 URL 的某一个后代 frame 中捕获节点。

        要求恰好存在一个祖先 frame 和一个匹配的后代 frame；允许元素结果为空。
        上下文退出时释放引用。作为可选能力，使现有仅文本的 Browser 实现
        保持兼容。
        """
        raise BrowserError("This browser does not support scoped DOM elements.")

    def page_element_scope(self, selector: str) -> AbstractContextManager[tuple[BrowserElement, ...]]:
        """捕获所选页面主 frame 中的节点，退出时释放引用。"""
        raise BrowserError("This browser does not support main-frame DOM elements.")

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

    def open_for_readiness(self, url: str) -> None:
        """在调用方进行就绪检查前先执行导航；否则回退到普通 open。"""
        self.open(url)

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
        发现当前页面快照中的可交互元素。

        调用本方法会刷新逻辑目标映射，并使先前发现产生的 ID 失效。
        导航或 DOM 替换也可能使当前映射中的 ID 过期。

        Returns:
            Browser 无关的元素及逻辑目标 ID。

        Raises:
            BrowserError: 无法检查浏览器状态。
        """
        raise NotImplementedError

    @abstractmethod
    def evaluate_in_frames(self, expression: str) -> tuple[object, ...]:
        """在每个 frame 中求值受信任的、与提供商无关的页面表达式。

        结果按 frame 顺序以普通 Python 值返回，不暴露提供商相关的 frame 对象。
        动态页面求值期间被分离的 frame 可能被省略。平台适配器可用此原语进行
        确定性的 DOM 检查或触发正常页面行为（如请求 HTML 媒体播放）；
        表达式不得伪造站点状态。

        Args:
            expression: 要在每个 frame 中求值的 JavaScript 表达式。

        Returns:
            成功检查到的 frame 的与提供商无关的求值结果。

        Raises:
            BrowserError: 无法检查该页面或其某个 frame。
        """
        raise NotImplementedError

    @abstractmethod
    def current_page(self) -> BrowserPage:
        """返回当前页面的不透明引用。"""
        raise NotImplementedError

    @abstractmethod
    def open_new_page_from_frame(
        self,
        frame_url_contains: str,
        selector: str,
        *,
        timeout_ms: int,
    ) -> BrowserPage:
        """点击一个匹配 frame 中的某个元素并捕获其弹窗页面。"""
        raise NotImplementedError

    @abstractmethod
    def switch_page(self, page: BrowserPage) -> None:
        """将后续 Browser 操作切换到某个受管理的页面。"""
        raise NotImplementedError

    @abstractmethod
    def close_page(self, page: BrowserPage) -> None:
        """关闭一个受管理的页面，且不隐式选择其他页面。"""
        raise NotImplementedError

    @abstractmethod
    def click_target(self, target_id: int) -> None:
        """
        点击当前页面快照中发现的一个元素。

        Args:
            target_id: interactive_elements() 返回的逻辑目标 ID。

        Raises:
            BrowserError: 目标未知、已过期或无法点击。
        """
        raise NotImplementedError

    @abstractmethod
    def fill_target(self, target_id: int, text: str) -> None:
        """
        向当前页面快照中发现的一个元素填写内容。

        Args:
            target_id: interactive_elements() 返回的逻辑目标 ID。
            text: 要输入的文本。

        Raises:
            BrowserError: 目标未知、已过期或无法填写。
        """
        raise NotImplementedError

    @abstractmethod
    def press_target(self, target_id: int, key: str) -> None:
        """
        向当前页面快照中的一个元素发送按键。

        Args:
            target_id: interactive_elements() 返回的逻辑目标 ID。
            key: 按键名称，例如 "Enter" 或 "Escape"。

        Raises:
            BrowserError: 目标未知、已过期或无法接收按键。
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
