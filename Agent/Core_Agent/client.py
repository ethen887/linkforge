from Model_Interface.openai_llm import OpenAIInterface
from Model_Interface.anthropic_llm import AnthropicInterface
from Model_Interface.basic_llm  import LLM
from Config.config import ModelConfig
def create_model_client(model_config:ModelConfig) -> LLM:
    if model_config.protocol == "openai":
        return OpenAIInterface(api_key=model_config.api_key, base_url=model_config.base_url)
    elif model_config.protocol == "anthropic":
        return AnthropicInterface(api_key=model_config.api_key) # Anthropic的接口协议不需要传入base_url
    else:
        raise NotImplementedError(f"协议 {model_config.protocol} 暂不支持")
