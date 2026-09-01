"""Observation data models."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Observation:
    """An immutable snapshot of observed page state."""

    url: str
    title: str
    text: str
