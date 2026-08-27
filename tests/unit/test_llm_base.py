"""Unit tests for the LLM base interface."""

import pytest

from linkforge.llm.base import LLM, LLMResponse, ToolCall


class TestToolCall:
    def test_tool_call_creation(self):
        tc = ToolCall(id="call_1", name="get_weather", arguments={"city": "Hangzhou"})
        assert tc.id == "call_1"
        assert tc.name == "get_weather"
        assert tc.arguments == {"city": "Hangzhou"}

    def test_tool_call_dataclass_equality(self):
        tc1 = ToolCall(id="call_1", name="fn", arguments={})
        tc2 = ToolCall(id="call_1", name="fn", arguments={})
        assert tc1 == tc2


class TestLLMResponse:
    def test_default_response(self):
        resp = LLMResponse()
        assert resp.content is None
        assert resp.tool_calls == []

    def test_response_with_content(self):
        resp = LLMResponse(content="Hello")
        assert resp.content == "Hello"
        assert resp.tool_calls == []

    def test_response_with_tool_calls(self):
        tc = ToolCall(id="1", name="fn", arguments={})
        resp = LLMResponse(content=None, tool_calls=[tc])
        assert resp.content is None
        assert len(resp.tool_calls) == 1
        assert resp.tool_calls[0].name == "fn"

    def test_response_none_tool_calls_becomes_empty_list(self):
        resp = LLMResponse(content="test", tool_calls=None)
        assert resp.tool_calls == []


class TestLLMBase:
    def test_convert_tool_calls_not_implemented(self):
        llm = LLM()
        with pytest.raises(NotImplementedError):
            llm._convert_tool_calls([])

    def test_convert_messages_not_implemented(self):
        llm = LLM()
        with pytest.raises(NotImplementedError):
            llm._convert_messages("user", content="hi")

    def test_call_model_not_implemented(self):
        llm = LLM()
        with pytest.raises(NotImplementedError):
            llm.call_model("model", [], [])
