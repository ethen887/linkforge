"""Unit tests for the LinkForge configuration module."""

import pytest

from linkforge.config.settings import (
    MODEL_PROVIDERS,
    BrowserConfig,
    ModelConfig,
    append_provider,
    create_model_config,
)


class TestModelConfig:
    """Tests for ModelConfig."""

    def test_default_protocol(self):
        """ModelConfig should use the OpenAI protocol by default."""
        cfg = ModelConfig(
            api_key="test",
            base_url="https://example.com",
            model_name="m",
        )

        assert cfg.protocol == "openai"

    def test_explicit_protocol(self):
        """ModelConfig should allow explicitly specifying the protocol."""
        cfg = ModelConfig(
            api_key="test",
            base_url="https://example.com",
            model_name="m",
            protocol="anthropic",
        )

        assert cfg.protocol == "anthropic"


class TestBrowserConfig:
    """Tests for BrowserConfig."""

    def test_default_values(self):
        """BrowserConfig should provide stable default runtime values."""
        cfg = BrowserConfig()

        assert cfg.headless is False
        assert cfg.timeout_ms == 15_000
        assert cfg.profile_dir is None

    def test_explicit_values(self):
        """BrowserConfig should allow browser runtime values to be overridden."""
        cfg = BrowserConfig(
            headless=True,
            timeout_ms=5_000,
            profile_dir="browser-profile",
        )

        assert cfg.headless is True
        assert cfg.timeout_ms == 5_000
        assert cfg.profile_dir == "browser-profile"

    @pytest.mark.parametrize("timeout_ms", [0, -1, -10_000])
    def test_non_positive_timeout_raises(self, timeout_ms):
        """BrowserConfig should reject zero or negative timeout values."""
        with pytest.raises(
            ValueError,
            match="timeout_ms must be greater than 0",
        ):
            BrowserConfig(timeout_ms=timeout_ms)

    @pytest.mark.parametrize("profile_dir", ["", " ", "\t"])
    def test_empty_profile_dir_raises(self, profile_dir: str):
        """BrowserConfig should reject empty persistent-profile paths."""
        with pytest.raises(ValueError, match="profile_dir must not be empty"):
            BrowserConfig(profile_dir=profile_dir)


class TestModelProviders:
    """Tests for built-in model provider definitions."""

    def test_required_providers_present(self):
        """Required built-in providers should be registered."""
        assert "qwen" in MODEL_PROVIDERS
        assert "deepseek" in MODEL_PROVIDERS
        assert "openai" in MODEL_PROVIDERS
        assert "anthropic" in MODEL_PROVIDERS

    def test_provider_has_required_fields(self):
        """Every built-in provider should contain the required fields."""
        for info in MODEL_PROVIDERS.values():
            assert "display_name" in info
            assert "base_url" in info
            assert "protocol" in info
            assert "default_model" in info

    def test_anthropic_protocol_is_anthropic(self):
        """Anthropic provider should use the Anthropic protocol."""
        assert MODEL_PROVIDERS["anthropic"]["protocol"] == "anthropic"

    def test_openai_protocol_is_openai(self):
        """OpenAI provider should use the OpenAI protocol."""
        assert MODEL_PROVIDERS["openai"]["protocol"] == "openai"


class TestCreateModelConfig:
    """Tests for create_model_config()."""

    def test_creates_with_default_model(self):
        """Provider default model should be used when model_name is omitted."""
        cfg = create_model_config(
            provider="openai",
            api="test-key",
        )

        assert cfg.api_key == "test-key"
        assert cfg.model_name == "gpt-4.1-mini"
        assert cfg.protocol == "openai"
        assert cfg.base_url == "https://api.openai.com/v1"

    def test_creates_with_explicit_model(self):
        """Explicit model_name should override the provider default."""
        cfg = create_model_config(
            provider="openai",
            api="key",
            model_name="gpt-4",
        )

        assert cfg.model_name == "gpt-4"

    def test_unknown_provider_raises(self):
        """Unknown providers should raise ValueError."""
        with pytest.raises(ValueError) as exc_info:
            create_model_config(
                provider="nonexistent",
                api="key",
            )

        assert "Unknown model provider" in str(exc_info.value)

    def test_qwen_provider(self):
        """Qwen should create an OpenAI-compatible model configuration."""
        cfg = create_model_config(
            provider="qwen",
            api="key",
        )

        assert cfg.model_name == "qwen-plus"
        assert "dashscope" in cfg.base_url


class TestAppendProvider:
    """Tests for append_provider()."""

    def test_appends_new_provider(self):
        """append_provider() should register a new provider."""
        provider_name = "test_provider"
        original_count = len(MODEL_PROVIDERS)

        try:
            append_provider(
                provider=provider_name,
                display_name="Test Provider",
                base_url="https://test.example.com",
                protocol="openai",
                default_models="test-model",
            )

            assert provider_name in MODEL_PROVIDERS
            assert MODEL_PROVIDERS[provider_name]["display_name"] == "Test Provider"
            assert MODEL_PROVIDERS[provider_name]["base_url"] == "https://test.example.com"
            assert MODEL_PROVIDERS[provider_name]["protocol"] == "openai"
            assert MODEL_PROVIDERS[provider_name]["models"] == "test-model"
            assert len(MODEL_PROVIDERS) == original_count + 1

        finally:
            MODEL_PROVIDERS.pop(provider_name, None)
