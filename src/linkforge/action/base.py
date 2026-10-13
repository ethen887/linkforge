"""动作执行器的基础接口。"""

from abc import ABC, abstractmethod

from linkforge.action.models import Action


class ActionExecutor(ABC):
    """针对特定实现的目标执行动作。"""

    @abstractmethod
    def execute(self, action: Action) -> None:
        """执行一个动作。"""
        raise NotImplementedError
