from anthropic import Anthropic
from Model_Interface import basic_llm 
from typing import List
import json
from anthropic.types import TextBlock, ToolUseBlock


class AnthropicInterface(basic_llm.LLM):
    def __init__(self, api_key: str):
        self.client = Anthropic(api_key)

    def _convert_tool_calls(self, tool_calls: List[basic_llm.ToolCall]) -> List[dict]:
        """将工具调用信息转换为Anthropic的格式"""
        anthropic_tool_calls = []
        for tool_call in tool_calls:
            anthropic_tool_calls.append({
                "type": "tool_use",
                "id": tool_call.id,
                "name": tool_call.name,
                "input": tool_call.arguments # Anthropic的input直接接收dict
            })
        return anthropic_tool_calls

    def _convert_messages(self, role, content: str | None = None, tool_calls: List[basic_llm.ToolCall] | None = None, tool_call_id: str | None = None) -> dict:
        if role == "system":
            # Anthropic的system prompt不放入messages，这里返回None，在call_model中单独提取
            return None 
        elif role == "user":
            return {"role": role, "content": content}
        elif role == "assistant":
            if tool_calls:
                # assistant的消息中，需要将文本和工具调用组合成content块列表
                content_blocks = []
                if content:
                    content_blocks.append({"type": "text", "text": content})
                content_blocks.extend(self._convert_tool_calls(tool_calls))
                return {"role": role, "content": content_blocks}
            else:
                return {"role": role, "content": content}
        elif role == "tool":
            if tool_call_id:
                # tool角色在Anthropic中为user角色下的tool_result块
                return {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": tool_call_id,
                            "content": content or ""
                        }
                    ]
                }
            else:
                raise ValueError("role='tool'时必须提供tool_call_id, 否则无法确定工具结果对应哪次调用")
        else:
            raise ValueError(f"不支持的role类型: {role}")

    def call_model(self, model: str, message: list, tools: list) -> basic_llm.LLMRes:
        system_prompt = None
        new_message = []
        for item in message: # 提取message中的system prompt和用户输入
            if item["role"] == "system":
                system_prompt = item["content"]
            else:
                new_message.append(item)
                
        message_t = self.client.messages.create(model=model, system=system_prompt, messages=new_message, tools=tools)
        text = None
        tool_calls = []
        for item in message_t.content:
            if isinstance(item, TextBlock):
                text = item.text
            elif isinstance(item, ToolUseBlock):
                tool_calls.append(basic_llm.ToolCall(item.id, item.name, item.input))

        return basic_llm.LLMRes(content=text, tool_calls=tool_calls)
