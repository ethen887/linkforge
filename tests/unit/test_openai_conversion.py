"""Unit tests for OpenAI message/tool-call conversion logic.

These tests do NOT make real API calls. They only verify the pure conversion logic.
"""

import pytest

from linkforge.llm.base import ToolCall


class TestOpenAIMessageConversion:
    """Test message conversion via the public LLM interface."""

    def _make_interface(self):
        # Import here to avoid module-level side effects
        from linkforge.llm.openai import OpenAIInterface

        # Bypass __init__ which would try to create an OpenAI client
        instance = OpenAIInterface.__new__(OpenAIInterface)
        return instance

    def test_system_message_conversion(self):
        iface = self._make_interface()
        result = iface._convert_messages(role="system", content="You are helpful")
        assert result == {"role": "system", "content": "You are helpful"}

    def test_user_message_conversion(self):
        iface = self._make_interface()
        result = iface._convert_messages(role="user", content="Hello")
        assert result == {"role": "user", "content": "Hello"}

    def test_assistant_message_without_tools(self):
        iface = self._make_interface()
        result = iface._convert_messages(role="assistant", content="Hi there")
        assert result == {"role": "assistant", "content": "Hi there"}

    def test_assistant_message_with_tools(self):
        iface = self._make_interface()
        tc = ToolCall(id="call_1", name="get_weather", arguments={"city": "Beijing"})
        result = iface._convert_messages(role="assistant", content="Let me check", tool_calls=[tc])
        assert result["role"] == "assistant"
        assert result["content"] == "Let me check"
        assert "tool_calls" in result
        assert len(result["tool_calls"]) == 1
        assert result["tool_calls"][0]["id"] == "call_1"
        assert result["tool_calls"][0]["function"]["name"] == "get_weather"

    def test_tool_message_requires_tool_call_id(self):
        iface = self._make_interface()
        with pytest.raises(ValueError):
            iface._convert_messages(role="tool", content="result")

    def test_tool_message_with_id(self):
        iface = self._make_interface()
        result = iface._convert_messages(role="tool", content="sunny", tool_call_id="call_xyz")
        assert result["role"] == "tool"
        assert result["tool_call_id"] == "call_xyz"
        assert result["content"] == "sunny"

    def test_unsupported_role_raises(self):
        iface = self._make_interface()
        with pytest.raises(ValueError) as exc_info:
            iface._convert_messages(role="wizard", content="test")
        assert "Unsupported role" in str(exc_info.value)

    def test_chinese_arguments_are_not_escaped(self):
        """Ensure unicode arguments are serialized correctly."""
        iface = self._make_interface()
        tc = ToolCall(id="1", name="fn", arguments={"city": "杭州"})
        result = iface._convert_messages(role="assistant", content=None, tool_calls=[tc])
        args_str = result["tool_calls"][0]["function"]["arguments"]
        assert "杭州" in args_str


class TestOpenAIToolCallsConversion:
    def test_convert_empty_list(self):
        from linkforge.llm.openai import OpenAIInterface

        instance = OpenAIInterface.__new__(OpenAIInterface)
        assert instance._convert_tool_calls([]) == []

    def test_convert_single_call(self):
        from linkforge.llm.openai import OpenAIInterface

        instance = OpenAIInterface.__new__(OpenAIInterface)
        tc = ToolCall(id="c1", name="get_weather", arguments={"city": "Beijing"})
        result = instance._convert_tool_calls([tc])
        assert len(result) == 1
        assert result[0]["id"] == "c1"
        assert result[0]["type"] == "function"
        assert result[0]["function"]["name"] == "get_weather"
