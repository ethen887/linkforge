"""与浏览器无关的数据模型。"""

from dataclasses import dataclass, field
from typing import Literal

type InteractiveElementRole = Literal["link", "button", "textbox"]


@dataclass(frozen=True, slots=True)
class InteractiveElement:
    """在隐藏浏览器实现细节的前提下暴露的一个可交互页面目标。"""

    target_id: int
    role: InteractiveElementRole
    name: str


@dataclass(frozen=True, slots=True)
class BrowserPage:
    """对由某个 Browser 实例监管的一个页面的不透明引用。"""

    page_id: int
    url: str


@dataclass(frozen=True, slots=True)
class BrowserJSONResponse:
    """正常页面操作产生的 JSON 响应；正文不参与对象的诊断输出。"""

    status: int
    data: object = field(repr=False)
