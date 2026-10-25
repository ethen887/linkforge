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

    def scroll_into_view(self) -> None:
        """将元素滚动至视口中部，减少固定顶栏遮挡；不改变内容或强制点击。"""
        ...

    def fill(self, text: str) -> None:
        """通过正常输入操作填写文本框或可编辑区域。"""
        ...

    def press(self, key: str) -> None:
        """在元素上发送按键。"""
        ...

    def type_text(self, text: str) -> None:
        """通过键盘输入纯文本，不解释为 HTML。"""
        ...

    def frame_query_all(self, selector: str) -> tuple["BrowserElement", ...]:
        """在此 iframe 的文档内查询；返回引用仍受当前作用域约束。"""
        ...
