"""Fake LLM implementations for testing without making real API calls."""

from typing import List, Optional

from linkforge.llm.base import LLM, LLMResponse, ToolCall


class FakeLLM(LLM):
    """A deterministic fake LLM that returns predefined responses for testing."""

    def __init__(self, scripted_responses: Optional[List[LLMResponse]] = None):
        self.scripted_responses = scripted_responses or []
        self.call_count = 0
        self.received_messages = []
        self.received_tools = []
        self.received_model = None

    def add_response(self, response: LLMResponse):
        """Add a response to the scripted sequence."""
        self.scripted_responses.append(response)

    def _convert_tool_calls(self, tool_calls: List[ToolCall]) -> List[dict]:
        """Convert tool calls to a generic format."""
        return [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.name, "arguments": str(tc.arguments)},
            }
            for tc in tool_calls
        ]

    def _convert_messages(
        self,
        role: str,
        content: str | None = None,
        tool_calls: List[ToolCall] | None = None,
        tool_call_id: str | None = None,
    ) -> dict:
        """Convert messages in a simple format compatible with the fake."""
        msg = {"role": role}
        if content is not None:
            msg["content"] = content
        if tool_calls:
            msg["tool_calls"] = self._convert_tool_calls(tool_calls)
        if tool_call_id:
            msg["tool_call_id"] = tool_call_id
        return msg

    def call_model(self, model: str, messages: list, tools: list) -> LLMResponse:
        """Return the next scripted response."""
        self.received_model = model
        self.received_messages = list(messages)
        self.received_tools = list(tools)

        if self.call_count >= len(self.scripted_responses):
            return LLMResponse(content="No more scripted responses")

        response = self.scripted_responses[self.call_count]
        self.call_count += 1
        return response


class RecordingFakeLLM(FakeLLM):
    """A fake LLM that records all calls for assertions."""

    def __init__(self):
        super().__init__()
        self.calls = []

    def call_model(self, model: str, messages: list, tools: list) -> LLMResponse:
        self.calls.append(
            {
                "model": model,
                "messages": list(messages),
                "tools": list(tools),
            }
        )
        return super().call_model(model, messages, tools)
