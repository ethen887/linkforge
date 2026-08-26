from dataclasses import dataclass
from typing import Any


@dataclass
class ModelConfig:
    """
    Model service configuration.
    Each created object represents a model invocation scheme.
    """

    api_key: str
    base_url: str
    model_name: str
    protocol: str = "openai"  # Default to OpenAI interface protocol


# Model provider configurations
MODEL_PROVIDERS: dict[str, dict[str, Any]] = {
    "qwen": {
        "display_name": "阿里云百炼",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "protocol": "openai",
        "default_model": "qwen-plus",
    },
    "deepseek": {
        "display_name": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "protocol": "openai",
        "default_model": "deepseek-chat",
    },
    "openai": {
        "display_name": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "protocol": "openai",
        "default_model": "gpt-4.1-mini",
    },
    "anthropic": {
        "display_name": "Anthropic",
        "base_url": "https://api.anthropic.com",
        "protocol": "anthropic",
        "default_model": "claude-sonnet-4-5",
    },
}


def append_provider(
    provider: str,
    display_name: str,
    base_url: str,
    default_models: str,
    protocol: str = "openai",
) -> dict[str, dict[str, Any]]:
    MODEL_PROVIDERS[provider] = {
        "display_name": display_name,
        "base_url": base_url,
        "protocol": protocol,
        "models": default_models,
    }
    return MODEL_PROVIDERS


def create_model_config(provider: str, api: str, model_name: str) -> ModelConfig:
    if provider not in MODEL_PROVIDERS:
        raise ValueError(f"Unknown model provider: {provider}")
    provider_info = MODEL_PROVIDERS[provider]
    if model_name is None:
        model_name = provider_info["default_model"]
    return ModelConfig(
        api_key=api,
        base_url=provider_info["base_url"],
        model_name=model_name,
        protocol=provider_info["protocol"],
    )
