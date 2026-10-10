"""Action data models."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class OpenAction:
    """Navigate the browser to a URL."""

    url: str


@dataclass(frozen=True, slots=True)
class ClickAction:
    """Click an interactive element from the current observation."""

    target_id: int


@dataclass(frozen=True, slots=True)
class FillAction:
    """Fill an interactive element from the current observation with text."""

    target_id: int
    text: str


@dataclass(frozen=True, slots=True)
class PressAction:
    """Send a key press to an interactive element from the current observation."""

    target_id: int
    key: str


@dataclass(frozen=True, slots=True)
class ScrollAction:
    """Scroll the browser vertically by a CSS pixel delta."""

    delta_y: int


type Action = OpenAction | ClickAction | FillAction | PressAction | ScrollAction
