"""Browser-neutral data models."""

from dataclasses import dataclass
from typing import Literal

type InteractiveElementRole = Literal["link", "button", "textbox"]


@dataclass(frozen=True, slots=True)
class InteractiveElement:
    """An interactive page target exposed without browser implementation details."""

    target_id: int
    role: InteractiveElementRole
    name: str


@dataclass(frozen=True, slots=True)
class BrowserPage:
    """Opaque reference to one page managed by a Browser instance."""

    page_id: int
    url: str
