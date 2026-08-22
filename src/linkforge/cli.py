from linkforge.config.settings import create_model_config, MODEL_PROVIDERS
from linkforge.llm.factory import create_model_client
from linkforge.agent.agent import create_weather_agent


def init_entrance():
    print(
        '欢迎使用LinkForge，'
        '"追求卓越，止于至善"是我们的信仰。\n'
        'LinkForge 是一个模块化自动化框架，'
        '用于连接网页、代码、API、大语言模型与可执行工作流。\n'
        '现在本项目支持的模型厂商包括：'
    )
    for provider_key, provider_info in MODEL_PROVIDERS.items():
        print(
            f"- {provider_info['display_name']} "
            f"（代号：{provider_key}，"
            f"默认模型：{provider_info['default_model']}）"
        )
    provider = input("请输入模型厂商: ").strip()
    model_name = input("请输入模型名称，直接回车使用默认模型: ").strip()
    api_key = input("请输入你在你所用的模型的开放平台获取的API_Key: ").strip()
    if model_name == "":
        model_name = MODEL_PROVIDERS[provider]["default_model"]
    
    model_config = create_model_config(provider=provider, api=api_key, model_name=model_name)
    weather_client = create_model_client(model_config)
    weather_agent = create_weather_agent(weather_client, model_name)
    print(weather_agent.run("帮我查询一下杭州的天气状况"))


def main():
    init_entrance()


if __name__ == "__main__":
    main()