import base64
from dataclasses import dataclass, field
from typing import Any, Literal, TypeAlias


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


MessageRole: TypeAlias = Literal["system", "user", "assistant", "tool"]


@dataclass(frozen=True, slots=True)
class LLMImage:
    """In-memory image input; adapters own wire-format encoding."""

    data: bytes = field(repr=False)
    media_type: Literal["image/png", "image/jpeg", "image/webp", "image/gif"] = "image/png"

    def __post_init__(self) -> None:
        if not isinstance(self.data, bytes) or not self.data:
            raise ValueError("Image data must be non-empty bytes")
        if self.media_type not in ("image/png", "image/jpeg", "image/webp", "image/gif"):
            raise ValueError("Unsupported image media type")

    def base64_data(self) -> str:
        return base64.b64encode(self.data).decode("ascii")


@dataclass(frozen=True, slots=True)
class LLMMessage:
    """A provider-neutral message in a LinkForge model conversation."""

    role: MessageRole
    content: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None
    images: tuple[LLMImage, ...] = ()

    def __post_init__(self) -> None:
        if self.images and self.role != "user":
            raise ValueError("Image inputs are supported only on user messages")


class LLMResponse:
    def __init__(self, content: str | None = None, tool_calls: list[ToolCall] | None = None):
        self.content = content
        self.tool_calls = tool_calls or []


class LLM:
    def call_model(
        self,
        model: str,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]],
    ) -> LLMResponse:
        raise NotImplementedError("Subclass must implement call_model method")
