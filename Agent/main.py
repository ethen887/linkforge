import Core_Agent.agent as at
from Config.config import create_model_config,MODEL_PROVIDERS
from Core_Agent.client import create_model_client
from Core_Agent.agent import create_weather_agent

def init_entrance(): 
    print(
        '欢迎使用钱成发开发的学习通自动刷课做题的 Agent，'
        '"追求卓越，止于至善"是我本人的信仰。\n'
        '本 Agent 是本人在大一暑假期间基本纯手搓的一个小项目，'
        '欢迎大家从源码进行重构。\n'
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
    # return {"provider": provider, "model_name": model_name, "api_key": api_key}
    model_config = create_model_config(provider = provider,
                                       api = api_key,
                                       model_name = model_name
                                      )
    weather_client = create_model_client(model_config)
    weather_agent  = create_weather_agent(weather_client, model_name)
    print(weather_agent.run("帮我查询一下杭州的天气状况"))
if __name__ == "__main__":
    init_entrance()