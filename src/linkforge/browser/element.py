"""供确定性适配器使用的、与提供商无关、绑定文档的 DOM 元素。"""

from typing import Protocol


class BrowserElement(Protocol):
    """仅在其 Browser.element_scope 上下文内部有效。

    元素引用捕获到的 DOM 节点，绝不静默地重新指向替换后的节点。
    所有操作失败都抛出 BrowserError。脚本和选择器均属可信的应用代码，
    绝非模型生成的浏览器指令。
    """

    def query_all(self, selector: str) -> tuple["BrowserElement", ...]:
        """返回限定到本元素的、按 DOM 顺序排列的后代。"""
        ...

    def evaluate(self, expression: str) -> object:
        """以本元素为参数求值一个受信任的表达式。"""
        ...

    def screenshot(self) -> bytes:
        """滚动到可见区域，然后将本元素作为内存中的 PNG 字节捕获。"""
        ...

    def click(self) -> None:
        """执行一次常规的可操作的 DOM 点击。"""
        ...
