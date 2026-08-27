"""
该文件是用来给用户创建Agent的, 在该文件内写好创建某个具体agent的函数, 供用户外部调用 api 接口
"""

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
