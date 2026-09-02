"""Observation data models."""

from dataclasses import dataclass

from linkforge.browser.models import InteractiveElement


@dataclass(frozen=True, slots=True)
class Observation:
    """An immutable snapshot of observed page state."""

    url: str
    title: str
    text: str
    interactive_elements: tuple[InteractiveElement, ...]
