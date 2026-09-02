"""Action data models."""

from dataclasses import dataclass
from typing import TypeAlias


@dataclass(frozen=True, slots=True)
class OpenAction:
    """Navigate the browser to a URL."""

    url: str


@dataclass(frozen=True, slots=True)
class ClickAction:
    """Click the element matched by a selector."""

    selector: str


@dataclass(frozen=True, slots=True)
class FillAction:
    """Fill the element matched by a selector with text."""

    selector: str
    text: str


@dataclass(frozen=True, slots=True)
class PressAction:
    """Send a key press to the element matched by a selector."""

    selector: str
    key: str


@dataclass(frozen=True, slots=True)
class ScrollAction:
    """Scroll the browser vertically by a CSS pixel delta."""

    delta_y: int


Action: TypeAlias = OpenAction | ClickAction | FillAction | PressAction | ScrollAction
