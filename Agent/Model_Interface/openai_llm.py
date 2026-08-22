from openai import OpenAI
import json
from Model_Interface import basic_llm
from typing import List, Dict, Any, Callable

class OpenAIInterface(basic_llm.LLM):
    def __init__(self, api_key: str, base_url: str | None = None):
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        
    def _convert_tool_calls(self, tool_calls: List[basic_llm.ToolCall]) -> List[dict]:
        """
        将工具调用信息转换为OpenAI的格式
        """
        openai_tool_calls = []
        for tool_call in tool_calls:
            openai_tool_calls.append({"id": tool_call.id, "type": "function", "function":{"name": tool_call.name, "arguments": json.dumps(tool_call.arguments, ensure_ascii=False)} })
        return openai_tool_calls
    def _convert_messages(self, role, content: str | None = None, tool_calls: List[basic_llm.ToolCall] | None =None, tool_call_id: str | None = None)->dict:
        if role in ("system", "user"):
            return {"role": role, "content": content}
        elif role == "assistant":
            if tool_calls: # 如果有工具调用信息，则将工具调用信息添加到消息中
                return {"role": role, "content": content, "tool_calls": self._convert_tool_calls(tool_calls)}
            else:
                return {"role": role, "content": content}
        elif role == "tool":
            if tool_call_id: # 如果有工具调用ID，则将工具调用ID添加到消息中
                return {"role": role, "tool_call_id": tool_call_id, "content": content or ""}
            else:
                raise ValueError( "role='tool'时必须提供tool_call_id, 否则无法确定工具结果对应哪次调用")
        else:
            raise ValueError(f"不支持的role类型: {role}")
    def call_model(self, model, messages, tools) -> basic_llm.LLMRes:
        messages_t = self.client.chat.completions.create(model=model, messages=messages, tools=tools)
        response = messages_t.choices[0].message
        text = response.content
        tool_calls = []
        if response.tool_calls:
            for item in response.tool_calls:
                tool_calls.append(basic_llm.ToolCall(item.id,item.function.name, json.loads(item.function.arguments) ) )
        return basic_llm.LLMRes(text, tool_calls) # 返回只携带模型返回结果中的文本和工具调用信息的一1个类
    

    
