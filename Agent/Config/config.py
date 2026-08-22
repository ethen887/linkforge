from dataclasses import dataclass


@dataclass
class ModelConfig:
    """
    一套模型服务配置。
    每创建一个对象，就代表一种模型调用方案。
    """
    api_key: str
    base_url: str
    model_name: str
    protocol: str = "openai" # 默认使用OpenAI的接口协议

# 各模型供应商的默认配置
MODEL_PROVIDERS = {
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


def append_provider(provider: str, 
                    display_name: str, 
                    base_url: str, 
                    protocol: str = "openai", 
                    default_models: str = None
                    ) -> dict[str, dict]:
    MODEL_PROVIDERS[provider] = {
        "display_name": display_name,
        "base_url": base_url,
        "protocol": protocol,
        "models": default_models,
    }
def create_model_config(provider: str, api: str, model_name: str = None) -> ModelConfig:
    if provider not in MODEL_PROVIDERS:
        raise ValueError(f"未知的模型供应商: {provider}")
    provider_info = MODEL_PROVIDERS[provider]
    if model_name is None:
        model_name = provider_info["default_model"]
    return ModelConfig(
        api_key=api,
        base_url=provider_info["base_url"],
        model_name=model_name,
        protocol=provider_info["protocol"]
    )
        
    