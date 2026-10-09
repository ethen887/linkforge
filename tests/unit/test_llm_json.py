from types import SimpleNamespace

import pytest

from linkforge.llm.anthropic import AnthropicInterface
from linkforge.llm.base import LLM, LLMMessage, LLMResponse
from linkforge.llm.errors import ModelRequestError
from linkforge.llm.openai import OpenAIInterface


@pytest.mark.parametrize(
    "endpoint,model,enabled",
    [
        ("https://dashscope.aliyuncs.com/compatible-mode/v1/", "qwen3.8-flash", True),
        ("https://dashscope-intl.aliyuncs.com/compatible-mode/v1", "qwen-plus", True),
        ("https://api.openai.com/v1", "gpt-4.1-mini", True),
        ("https://api.deepseek.com/", "deepseek-chat", True),
        ("https://generativelanguage.googleapis.com/v1beta/openai/", "gemini-3.8-flash", True),
        ("https://custom.example/v1", "qwen3.8-flash", False),
        ("https://dashscope.aliyuncs.com.evil.example/compatible-mode/v1", "qwen3.8-flash", False),
    ],
)
def test_json_mode_is_limited_to_known_provider_endpoints(endpoint, model, enabled):
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="{}", tool_calls=None), finish_reason="length"
                )
            ]
        )

    adapter = OpenAIInterface.__new__(OpenAIInterface)
    adapter.client = SimpleNamespace(
        base_url=endpoint, chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    result = adapter.call_json_model(model, [LLMMessage("user", "JSON")])
    assert result.finish_reason == "length"
    assert ("response_format" in calls[0]) is enabled
    if enabled:
        assert calls[0]["response_format"] == {"type": "json_object"}
    adapter.call_model(model, [LLMMessage("user", "normal")], [])
    assert "response_format" not in calls[1]


def test_base_json_request_preserves_legacy_adapter_contract():
    class Adapter(LLM):
        def call_model(self, model, messages, tools):
            assert model == "test" and tools == []
            return LLMResponse("{}")

    assert Adapter().call_json_model("test", []).content == "{}"


def test_anthropic_preserves_stop_reason_without_adding_parameters():
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(content=[], stop_reason="max_tokens")

    adapter = AnthropicInterface.__new__(AnthropicInterface)
    adapter.client = SimpleNamespace(messages=SimpleNamespace(create=create))
    assert adapter.call_json_model("test", []).finish_reason == "max_tokens"
    assert "response_format" not in calls[0]


@pytest.mark.parametrize("adapter_type", [OpenAIInterface, AnthropicInterface])
def test_provider_request_failure_is_wrapped_with_safe_reason(adapter_type):
    class ProviderError(Exception):
        status_code = 429

    def create(**_kwargs):
        raise ProviderError("PRIVATE PROVIDER RESPONSE")

    adapter = adapter_type.__new__(adapter_type)
    if adapter_type is OpenAIInterface:
        adapter.client = SimpleNamespace(
            base_url="https://api.openai.com/v1",
            chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
        )
    else:
        adapter.client = SimpleNamespace(messages=SimpleNamespace(create=create))

    with pytest.raises(ModelRequestError, match="限流或额度不足") as caught:
        adapter.call_json_model("test", [])
    assert "PRIVATE" not in str(caught.value)
