"""浏览器智能体决策接口。"""

from abc import ABC, abstractmethod

from linkforge.agent.models import BrowserDecision
from linkforge.observation.models import Observation


class BrowserAgent(ABC):
    """根据当前观察结果选择下一个浏览器动作。"""

    @abstractmethod
    def decide(self, observation: Observation) -> BrowserDecision:
        """返回下一个动作或标记正常完成。"""
        raise NotImplementedError
