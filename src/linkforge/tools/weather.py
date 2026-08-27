import requests

from linkforge.agent.framework import AgentTool


def get_seniverse_weather(location: str) -> str:
    """
    使用心知天气 (Seniverse) API 查询指定城市的实时天气。
    注意：此函数需要通过环境变量或参数传入API密钥，不应硬编码。
    """
    # 注意：这里的API密钥应该从环境变量或配置中获取，而不是硬编码
    # 为避免安全问题，此处移除了硬编码的密钥
    api_key = None  # 应该从环境变量或配置中获取

    if not api_key:
        return "错误：API密钥未配置。请设置环境变量或配置文件中的天气API密钥。"

    # 心知天气 v3 接口地址
    url = "https://api.seniverse.com/v3/weather/now.json"

    params = {
        "key": api_key,
        "location": location,  # 支持城市中文名、拼音、IP地址等
        "language": "zh-Hans",  # 使用简体中文
        "unit": "c",  # 摄氏度
    }

    try:
        response = requests.get(url, params=params, timeout=5)
        response.raise_for_status()
        data = response.json()

        # 解析返回的 JSON 数据
        # 心知天气的返回结构通常是 {"results": [{"location": {...}, "now": {...}, "last_update": "..."}]}
        result = data["results"][0]
        city_name = result["location"]["name"]
        weather_text = result["now"]["text"]
        temperature = result["now"]["temperature"]

        return f"{city_name}当前天气：{weather_text}，气温：{temperature}℃。"
    except Exception as e:
        return f"获取心知天气数据失败：{str(e)}"


# 创建天气工具实例
weather_tool = AgentTool(
    name="get_seniverse_weather",
    description="查询指定城市的实时天气状况。输入城市名称，返回当前天气文本和温度。",
    parameters={
        "type": "object",
        "properties": {
            "location": {
                "type": "string",
                "description": "城市名称，支持中文（如 '北京'、'杭州'）、拼音或英文（如 'shanghai'）",
            }
        },
        "required": ["location"],
    },
    function=get_seniverse_weather,
)
