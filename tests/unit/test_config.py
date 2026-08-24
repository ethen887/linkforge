"""Unit tests for the configuration module."""

import pytest

from linkforge.config.settings import (
    MODEL_PROVIDERS,
    ModelConfig,
    append_provider,
    create_model_config,
)


class TestModelConfig:
    def test_default_protocol(self):
        cfg = ModelConfig(api_key="test", base_url="https://example.com", model_name="m")
        assert cfg.protocol == "openai"

    def test_explicit_protocol(self):
        cfg = ModelConfig(
            api_key="test", base_url="https://example.com", model_name="m", protocol="anthropic"
        )
        assert cfg.protocol == "anthropic"


class TestModelProviders:
    def test_required_providers_present(self):
        assert "qwen" in MODEL_PROVIDERS
        assert "deepseek" in MODEL_PROVIDERS
        assert "openai" in MODEL_PROVIDERS
        assert "anthropic" in MODEL_PROVIDERS

    def test_provider_has_required_fields(self):
        for key, info in MODEL_PROVIDERS.items():
            assert "display_name" in info
            assert "base_url" in info
            assert "protocol" in info
            assert "default_model" in info

    def test_anthropic_protocol_is_anthropic(self):
        assert MODEL_PROVIDERS["anthropic"]["protocol"] == "anthropic"

    def test_openai_protocol_is_openai(self):
        assert MODEL_PROVIDERS["openai"]["protocol"] == "openai"


class TestCreateModelConfig:
    def test_creates_with_default_model(self):
        cfg = create_model_config(provider="openai", api="test-key")
        assert cfg.api_key == "test-key"
        assert cfg.model_name == "gpt-4.1-mini"
        assert cfg.protocol == "openai"
        assert cfg.base_url == "https://api.openai.com/v1"

    def test_creates_with_explicit_model(self):
        cfg = create_model_config(provider="openai", api="key", model_name="gpt-4")
        assert cfg.model_name == "gpt-4"

    def test_unknown_provider_raises(self):
        with pytest.raises(ValueError) as exc_info:
            create_model_config(provider="nonexistent", api="key")
        assert "Unknown model provider" in str(exc_info.value)

    def test_qwen_provider(self):
        cfg = create_model_config(provider="qwen", api="key")
        assert cfg.model_name == "qwen-plus"
        assert "dashscope" in cfg.base_url


class TestAppendProvider:
    def test_appends_new_provider(self):
        original_count = len(MODEL_PROVIDERS)
        append_provider(
            provider="test_provider",
            display_name="Test Provider",
            base_url="https://test.example.com",
            protocol="openai",
            default_models="test-model",
        )
        assert "test_provider" in MODEL_PROVIDERS
        assert MODEL_PROVIDERS["test_provider"]["display_name"] == "Test Provider"
        assert len(MODEL_PROVIDERS) == original_count + 1
