"""观察数据模型。"""

from dataclasses import dataclass

from linkforge.browser.models import InteractiveElement


@dataclass(frozen=True, slots=True)
class Observation:
    """一个不可变的已观察页面状态快照。"""

    url: str
    title: str
    text: str
    interactive_elements: tuple[InteractiveElement, ...]
