"""Browser-neutral data models."""

from dataclasses import dataclass
from typing import Literal, TypeAlias

InteractiveElementRole: TypeAlias = Literal["link", "button", "textbox"]


@dataclass(frozen=True, slots=True)
class InteractiveElement:
    """An interactive page target exposed without browser implementation details."""

    target_id: int
    role: InteractiveElementRole
    name: str
