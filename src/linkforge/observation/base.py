"""观察源的基础接口。"""

from abc import ABC, abstractmethod

from linkforge.observation.models import Observation


class Observer(ABC):
    """从观察源生成规范化的状态快照。"""

    @abstractmethod
    def observe(self) -> Observation:
        """捕获并返回观察源的当前状态。"""
        raise NotImplementedError
