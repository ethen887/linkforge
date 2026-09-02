"""Test doubles for external LinkForge interfaces."""

from linkforge.browser.base import Browser
from linkforge.browser.exceptions import BrowserError
from linkforge.llm.base import LLM, LLMResponse, ToolCall


class FakeBrowser(Browser):
    """A deterministic Browser implementation that does not launch a real browser."""

    def __init__(
        self,
        *,
        url: str = "about:blank",
        title: str = "",
        text: str = "",
        observation_error: BrowserError | None = None,
        action_error: BrowserError | None = None,
    ) -> None:
        self.url = url
        self.page_title = title
        self.page_text = text
        self.observation_error = observation_error
        self.action_error = action_error
        self.action_calls: list[tuple[object, ...]] = []

    def start(self) -> None:
        pass

    def open(self, url: str) -> None:
        self._raise_action_error()
        self.url = url
        self.action_calls.append(("open", url))

    def current_url(self) -> str:
        self._raise_observation_error()
        return self.url

    def title(self) -> str:
        self._raise_observation_error()
        return self.page_title

    def text(self) -> str:
        self._raise_observation_error()
        return self.page_text

    def click(self, selector: str) -> None:
        self._raise_action_error()
        self.action_calls.append(("click", selector))

    def fill(self, selector: str, text: str) -> None:
        self._raise_action_error()
        self.action_calls.append(("fill", selector, text))

    def press(self, selector: str, key: str) -> None:
        self._raise_action_error()
        self.action_calls.append(("press", selector, key))

    def scroll(self, delta_y: int) -> None:
        self._raise_action_error()
        self.action_calls.append(("scroll", delta_y))

    def close(self) -> None:
        pass

    def _raise_observation_error(self) -> None:
        if self.observation_error is not None:
            raise self.observation_error

    def _raise_action_error(self) -> None:
        if self.action_error is not None:
            raise self.action_error


class FakeLLM(LLM):
    """A deterministic fake LLM that returns predefined responses for testing."""

    def __init__(self, scripted_responses: list[LLMResponse] | None = None):
        self.scripted_responses = scripted_responses or []
        self.call_count = 0
        self.received_messages = []
        self.received_tools = []
        self.received_model = None

    def add_response(self, response: LLMResponse):
        """Add a response to the scripted sequence."""
        self.scripted_responses.append(response)

    def _convert_tool_calls(self, tool_calls: list[ToolCall]) -> list[dict]:
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
        tool_calls: list[ToolCall] | None = None,
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
