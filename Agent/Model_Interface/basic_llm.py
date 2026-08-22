from typing import List, Optional


class ToolCall:
    def __init__(
        self,
        id,
        name: str,
        arguments: dict
    ):
        self.id = id
        self.name = name
        self.arguments = arguments

class LLMRes:
    def __init__(self, content: str | None = None, tool_calls: List[ToolCall] | None = None):
        self.content = content
        self.tool_calls = tool_calls or []
 

class LLM:
    def _convert_tool_calls(self, tool_calls: List[ToolCall]) -> List[dict]:
        raise NotImplementedError("该子类未重写_convert_tool_calls方法")
    def _convert_messages(self, role:str, content: str | None = None, tool_calls:List[ToolCall] | None = None, tool_call_id: str | None = None) -> dict: # 统一历史消息添加接口, 具体的格式在各自的子类中具体实现
        raise NotImplementedError("该子类未重写_convert_messages方法")
    def call_model(self, model: str, messages: list, tools: list) -> LLMRes:
        raise NotImplementedError("该子类未重写call_model方法")

# class HisMessage:
#     """
#     统一历史对话格式, 在要append到history中时, 只需调用转换方法(该方法在Anthropic和OpenAI接口中实现),即可将人类容易读懂的内容转换为对应接口的格式
#     """
#     def __init__(self, role: str, content: str = None, tool_calls: List[ToolCall] = None, toll_call_id: Optional[str] = None):
#         self.role = role
#         self.content = content
#         self.tool_calls = tool_calls or []
#         self.tool_call_id = toll_call_id
