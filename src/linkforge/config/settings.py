"""
LinkForge configuration models and built-in provider definitions.

本模块负责定义 LinkForge 各基础设施模块使用的配置数据结构。

当前包含：
- LLM 模型服务配置；
- Browser 运行时配置；
- 内置模型 Provider 信息；
- 模型配置创建辅助函数。

本模块只描述“配置是什么”，不负责创建或运行具体的 LLM、Browser 等资源。
"""

from dataclasses import dataclass
from typing import Any


@dataclass
class ModelConfig:
    """
    LLM 模型服务配置。

    每个 ModelConfig 对象描述一次模型客户端创建所需的基础配置。

    Attributes:
        api_key: 模型服务 API Key。
        base_url: 模型服务 API Base URL。
        model_name: 实际调用的模型名称。
        protocol: Provider 所使用的接口协议。
    """

    api_key: str
    base_url: str
    model_name: str
    protocol: str = "openai"


@dataclass
class BrowserConfig:
    """
    Browser 运行时配置。

    BrowserConfig 只保存浏览器运行参数，不负责创建或管理浏览器实例。

    Attributes:
        headless:
            是否以无头模式运行浏览器。
            False 时显示浏览器窗口，适合本地开发与调试。
        timeout_ms:
            Browser 页面操作和导航的默认超时时间，单位为毫秒。
        profile_dir:
            可选的 Chromium user-data 目录。指定后可复用浏览器登录态。

    Raises:
        ValueError:
            timeout_ms 小于等于 0，或 profile_dir 为空白字符串时抛出。
    """

    headless: bool = False
    timeout_ms: int = 15_000
    profile_dir: str | None = None

    def __post_init__(self) -> None:
        """
        校验 Browser 配置是否合法。

        Raises:
            ValueError:
                timeout_ms 必须大于 0，且 profile_dir 不能是空白字符串。
        """
        if self.timeout_ms <= 0:
            raise ValueError("timeout_ms must be greater than 0")
        if self.profile_dir is not None and not self.profile_dir.strip():
            raise ValueError("profile_dir must not be empty")


# Built-in model provider configurations.
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
    "gemini": {
        "display_name": "Google Gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "protocol": "openai",
        "default_model": "gemini-3.8-flash",
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
    """
    向运行时 Provider 注册表追加模型服务。

    Args:
        provider: Provider 唯一标识。
        display_name: Provider 显示名称。
        base_url: Provider API Base URL。
        default_models: Provider 模型信息。
        protocol: Provider 使用的接口协议。

    Returns:
        更新后的 MODEL_PROVIDERS。
    """
    MODEL_PROVIDERS[provider] = {
        "display_name": display_name,
        "base_url": base_url,
        "protocol": protocol,
        "models": default_models,
    }

    return MODEL_PROVIDERS


def create_model_config(
    provider: str,
    api: str,
    model_name: str | None = None,
) -> ModelConfig:
    """
    根据 Provider 创建模型配置。

    Args:
        provider: MODEL_PROVIDERS 中注册的 Provider 名称。
        api: 模型服务 API Key。
        model_name:
            指定模型名称。
            为 None 时使用 Provider 的默认模型。

    Returns:
        创建完成的 ModelConfig。

    Raises:
        ValueError:
            Provider 未注册时抛出。
    """
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
