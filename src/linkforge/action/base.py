"""Base interface for action executors."""

from abc import ABC, abstractmethod

from linkforge.action.models import Action


class ActionExecutor(ABC):
    """Execute actions against an implementation-specific target."""

    @abstractmethod
    def execute(self, action: Action) -> None:
        """Execute an action."""
        raise NotImplementedError
