"""Data models for browser-agent decisions."""

from dataclasses import dataclass

from linkforge.action.models import Action


@dataclass(frozen=True, slots=True)
class FinishDecision:
    """Signal that a browser task completed normally."""


type BrowserDecision = Action | FinishDecision
