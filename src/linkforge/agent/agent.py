from linkforge.agent.framework import RecAgent
from linkforge.llm.base import LLM
from linkforge.tools.weather import weather_tool


def create_weather_agent(client: LLM, model_name: str) -> RecAgent:
    return RecAgent(
        system_prompt="你是一个能够查询天气的助手, 用户询问实时天气时，"
        "必须调用天气工具获取真实数据。",
        client=client,
        tools=[weather_tool],
        model=model_name,
    )
