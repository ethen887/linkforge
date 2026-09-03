"""Unit tests for Anthropic message/tool-call conversion logic.

These tests do NOT make real API calls. They only verify the pure conversion logic.
"""

from types import SimpleNamespace

import pytest

from linkforge.llm.base import LLMMessage, ToolCall


class TestAnthropicMessageConversion:
    """Test the Anthropic adapter's internal message conversion helper."""

    def _make_interface(self):
        from linkforge.llm.anthropic import AnthropicInterface

        instance = AnthropicInterface.__new__(AnthropicInterface)
        return instance

    def test_system_message_returns_none(self):
        """Anthropic does not put system messages in the messages list."""
        iface = self._make_interface()
        result = iface._convert_message(LLMMessage(role="system", content="Be helpful"))
        assert result is None

    def test_user_message_conversion(self):
        iface = self._make_interface()
        result = iface._convert_message(LLMMessage(role="user", content="Hello"))
        assert result == {"role": "user", "content": "Hello"}

    def test_assistant_without_tools(self):
        iface = self._make_interface()
        result = iface._convert_message(LLMMessage(role="assistant", content="Hi"))
        assert result == {"role": "assistant", "content": "Hi"}

    def test_assistant_with_tools_uses_content_blocks(self):
        iface = self._make_interface()
        tc = ToolCall(id="tool_1", name="get_weather", arguments={"city": "Shanghai"})
        result = iface._convert_message(
            LLMMessage(role="assistant", content="Let me check", tool_calls=(tc,))
        )
        assert result["role"] == "assistant"
        assert isinstance(result["content"], list)
        # Should contain both a text block and a tool_use block
        assert any(b.get("type") == "text" for b in result["content"])
        assert any(b.get("type") == "tool_use" for b in result["content"])

    def test_tool_message_becomes_user_with_tool_result(self):
        """Anthropic tool results are returned as user messages with tool_result blocks."""
        iface = self._make_interface()
        result = iface._convert_message(LLMMessage(role="tool", content="sunny 25C", tool_call_id="tool_1"))
        assert result["role"] == "user"
        assert isinstance(result["content"], list)
        assert result["content"][0]["type"] == "tool_result"
        assert result["content"][0]["tool_use_id"] == "tool_1"
        assert result["content"][0]["content"] == "sunny 25C"

    def test_tool_message_without_id_raises(self):
        iface = self._make_interface()
        with pytest.raises(ValueError):
            iface._convert_message(LLMMessage(role="tool", content="result"))


class TestAnthropicToolCallsConversion:
    def test_convert_empty_list(self):
        from linkforge.llm.anthropic import AnthropicInterface

        instance = AnthropicInterface.__new__(AnthropicInterface)
        assert instance._convert_tool_calls(()) == []

    def test_convert_uses_input_not_arguments(self):
        from linkforge.llm.anthropic import AnthropicInterface

        instance = AnthropicInterface.__new__(AnthropicInterface)
        tc = ToolCall(id="t1", name="get_weather", arguments={"city": "Beijing"})
        result = instance._convert_tool_calls((tc,))
        assert len(result) == 1
        assert result[0]["type"] == "tool_use"
        assert result[0]["id"] == "t1"
        assert result[0]["name"] == "get_weather"
        # Anthropic uses "input" directly with dict (not stringified)
        assert result[0]["input"] == {"city": "Beijing"}


class TestAnthropicPublicCall:
    def test_call_model_converts_linkforge_messages_before_sdk_call(self):
        from linkforge.llm.anthropic import AnthropicInterface

        calls = []

        def create(**kwargs):
            calls.append(kwargs)
            return SimpleNamespace(content=[])

        instance = AnthropicInterface.__new__(AnthropicInterface)
        instance.client = SimpleNamespace(messages=SimpleNamespace(create=create))
        tool_call = ToolCall(id="tool_1", name="get_weather", arguments={"city": "Hangzhou"})

        instance.call_model(
            "test-model",
            [
                LLMMessage(role="system", content="Be helpful"),
                LLMMessage(role="user", content="Weather?"),
                LLMMessage(
                    role="assistant",
                    content="Let me check",
                    tool_calls=(tool_call,),
                ),
                LLMMessage(role="tool", content="sunny", tool_call_id="tool_1"),
            ],
            [],
        )

        assert calls[0]["system"] == "Be helpful"
        assert calls[0]["messages"] == [
            {"role": "user", "content": "Weather?"},
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Let me check"},
                    {
                        "type": "tool_use",
                        "id": "tool_1",
                        "name": "get_weather",
                        "input": {"city": "Hangzhou"},
                    },
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "tool_1",
                        "content": "sunny",
                    }
                ],
            },
        ]

    def test_system_prompt_is_isolated_per_request(self):
        from linkforge.llm.anthropic import AnthropicInterface

        calls = []

        def create(**kwargs):
            calls.append(kwargs)
            return SimpleNamespace(content=[])

        instance = AnthropicInterface.__new__(AnthropicInterface)
        instance.client = SimpleNamespace(messages=SimpleNamespace(create=create))

        instance.call_model(
            "test-model",
            [
                LLMMessage(role="system", content="System A"),
                LLMMessage(role="user", content="Request A"),
            ],
            [],
        )
        instance.call_model(
            "test-model",
            [
                LLMMessage(role="system", content="System B"),
                LLMMessage(role="user", content="Request B"),
            ],
            [],
        )

        assert calls[0]["system"] == "System A"
        assert calls[1]["system"] == "System B"
