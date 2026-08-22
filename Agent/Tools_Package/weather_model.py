import requests
from Core_Agent.agent_framwork import AgentTool
def get_seniverse_weather(location: str) -> str:
    """
    使用心知天气 (Seniverse) API 查询指定城市的实时天气。
    """
    # 从你的控制台信息中提取的私钥 (请确保已在环境变量中设置)
    # 根据网页显示，你的公钥之一是 PvWHimNUUvKlpVhXR
    api_key = "SsdqNq9DmYagpPUTK"
    
    # 心知天气 v3 接口地址
    url = "https://api.seniverse.com/v3/weather/now.json"
    
    params = {
        "key": api_key,
        "location": location, # 支持城市中文名、拼音、IP地址等
        "language": "zh-Hans", # 使用简体中文
        "unit": "c"            # 摄氏度
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

weather_tool = AgentTool(
    name = "get_seniverse_weather",
    description = "查询指定城市的实时天气",
    parameters={
        "type": "object",
        "properties": {
            "location": {
                "type": "string",
                "description": "城市名称，例如 '北京'、'杭州' 或 'shanghai'"
            }
        },
        "required": ["location"]
    },
    function = get_seniverse_weather
)