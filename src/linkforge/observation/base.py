"""Base interface for observation sources."""

from abc import ABC, abstractmethod

from linkforge.observation.models import Observation


class Observer(ABC):
    """Produce normalized state snapshots from an observation source."""

    @abstractmethod
    def observe(self) -> Observation:
        """Capture and return the current state of the observation source."""
        raise NotImplementedError
