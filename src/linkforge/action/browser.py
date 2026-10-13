"""基于浏览器的动作执行器。"""

from typing import assert_never

from linkforge.action.base import ActionExecutor
from linkforge.action.exceptions import ActionExecutionError
from linkforge.action.models import (
    Action,
    ClickAction,
    FillAction,
    OpenAction,
    PressAction,
    ScrollAction,
)
from linkforge.browser.base import Browser
from linkforge.browser.exceptions import BrowserError


class BrowserActionExecutor(ActionExecutor):
    """通过 Browser 抽象层执行结构化动作。"""

    def __init__(self, browser: Browser) -> None:
        self._browser = browser

    def execute(self, action: Action) -> None:
        """将一个动作映射到对应的 Browser 操作。"""
        try:
            if isinstance(action, OpenAction):
                self._browser.open(action.url)
            elif isinstance(action, ClickAction):
                self._browser.click_target(action.target_id)
            elif isinstance(action, FillAction):
                self._browser.fill_target(action.target_id, action.text)
            elif isinstance(action, PressAction):
                self._browser.press_target(action.target_id, action.key)
            elif isinstance(action, ScrollAction):
                self._browser.scroll(action.delta_y)
            else:
                assert_never(action)
        except BrowserError as exc:
            raise ActionExecutionError("Failed to execute browser action.") from exc
