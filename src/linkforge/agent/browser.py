"""Browser-agent decision interface."""

from abc import ABC, abstractmethod

from linkforge.agent.models import BrowserDecision
from linkforge.observation.models import Observation


class BrowserAgent(ABC):
    """Choose the next browser action from the current observation."""

    @abstractmethod
    def decide(self, observation: Observation) -> BrowserDecision:
        """Return the next action or signal normal completion."""
        raise NotImplementedError
