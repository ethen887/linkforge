from dataclasses import dataclass
from typing import Any, Literal, TypeAlias


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


MessageRole: TypeAlias = Literal["system", "user", "assistant", "tool"]


@dataclass(frozen=True, slots=True)
class LLMMessage:
    """A provider-neutral message in a LinkForge model conversation."""

    role: MessageRole
    content: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None


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
