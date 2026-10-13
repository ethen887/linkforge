from linkforge.config.settings import ModelConfig
from linkforge.llm.anthropic import AnthropicInterface
from linkforge.llm.base import LLM
from linkforge.llm.openai import OpenAIInterface


def create_model_client(model_config: ModelConfig) -> LLM:
    """根据配置中的协议创建对应的模型客户端。

    Args:
        model_config: 包含协议、API Key 与接口地址的模型配置。

    Returns:
        对应协议的 LLM 客户端实例。

    Raises:
        NotImplementedError: 配置的协议不受支持时抛出。
    """
    if model_config.protocol == "openai":
        return OpenAIInterface(api_key=model_config.api_key, base_url=model_config.base_url)
    elif model_config.protocol == "anthropic":
        return AnthropicInterface(api_key=model_config.api_key, base_url=model_config.base_url)
    else:
        raise NotImplementedError(f"Protocol {model_config.protocol} not supported")
