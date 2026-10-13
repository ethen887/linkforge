"""浏览器智能体决策的数据模型。"""

from dataclasses import dataclass

from linkforge.action.models import Action


@dataclass(frozen=True, slots=True)
class FinishDecision:
    """标记浏览器任务已正常完成。"""


type BrowserDecision = Action | FinishDecision
