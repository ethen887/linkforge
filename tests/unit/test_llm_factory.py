"""Unit tests for the LLM factory."""
import pytest
from linkforge.config.settings import ModelConfig
from linkforge.llm.factory import create_model_client


class TestCreateModelClient:
    def test_openai_protocol_creates_openai_interface(self):
        config = ModelConfig(
            api_key="test",
            base_url="https://api.openai.com/v1",
            model_name="gpt-4",
            protocol="openai"
        )
        client = create_model_client(config)
        from linkforge.llm.openai import OpenAIInterface
        assert isinstance(client, OpenAIInterface)

    def test_anthropic_protocol_creates_anthropic_interface(self):
        config = ModelConfig(
            api_key="test",
            base_url="https://api.anthropic.com",
            model_name="claude",
            protocol="anthropic"
        )
        client = create_model_client(config)
        from linkforge.llm.anthropic import AnthropicInterface
        assert isinstance(client, AnthropicInterface)

    def test_unknown_protocol_raises(self):
        config = ModelConfig(
            api_key="test",
            base_url="https://example.com",
            model_name="m",
            protocol="unknown_protocol"
        )
        with pytest.raises(NotImplementedError) as exc_info:
            create_model_client(config)
        assert "not supported" in str(exc_info.value)