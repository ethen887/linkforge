from Core_Agent.agent_framwork   import RecAgent
from Model_Interface.basic_llm import LLM
from Tools_Package.weather_model import weather_tool
def create_weather_agent(client: LLM, model_name: str) -> RecAgent:
    return RecAgent( system_prompt = "你是一个能够查询天气的助手, 用户询问实时天气时，必须调用天气工具获取真实数据。",
                     client = client,
                     tools = [weather_tool],
                     model = model_name
                   )
