"""动作数据模型。"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class OpenAction:
    """在浏览器中打开一个 URL。"""

    url: str


@dataclass(frozen=True, slots=True)
class ClickAction:
    """点击来自当前观察结果的一个交互元素。"""

    target_id: int


@dataclass(frozen=True, slots=True)
class FillAction:
    """用文本填充来自当前观察结果的一个交互元素。"""

    target_id: int
    text: str


@dataclass(frozen=True, slots=True)
class PressAction:
    """向来自当前观察结果的一个交互元素发送按键。"""

    target_id: int
    key: str


@dataclass(frozen=True, slots=True)
class ScrollAction:
    """按 CSS 像素差值垂直滚动浏览器。"""

    delta_y: int


type Action = OpenAction | ClickAction | FillAction | PressAction | ScrollAction
