from linkforge.config.settings import ModelConfig
from linkforge.llm.anthropic import AnthropicInterface
from linkforge.llm.base import LLM
from linkforge.llm.openai import OpenAIInterface


def create_model_client(model_config: ModelConfig) -> LLM:
    if model_config.protocol == "openai":
        return OpenAIInterface(api_key=model_config.api_key, base_url=model_config.base_url)
    elif model_config.protocol == "anthropic":
        return AnthropicInterface(api_key=model_config.api_key)  # Anthropic interface doesn't need base_url
    else:
        raise NotImplementedError(f"Protocol {model_config.protocol} not supported")
