from openai import OpenAI
import json
from linkforge.llm.base import LLM, LLMResponse, ToolCall
from typing import List


class OpenAIInterface(LLM):
    def __init__(self, api_key: str, base_url: str | None = None):
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        
    def _convert_tool_calls(self, tool_calls: List[ToolCall]) -> List[dict]:
        """
        Convert tool calls to OpenAI format
        """
        openai_tool_calls = []
        for tool_call in tool_calls:
            openai_tool_calls.append({
                "id": tool_call.id, 
                "type": "function", 
                "function": {
                    "name": tool_call.name, 
                    "arguments": json.dumps(tool_call.arguments, ensure_ascii=False)
                }
            })
        return openai_tool_calls
    
    def _convert_messages(self, role: str, content: str | None = None, 
                         tool_calls: List[ToolCall] | None = None, 
                         tool_call_id: str | None = None) -> dict:
        if role in ("system", "user"):
            return {"role": role, "content": content}
        elif role == "assistant":
            if tool_calls:  # If there are tool calls, add them to the message
                return {"role": role, "content": content, "tool_calls": self._convert_tool_calls(tool_calls)}
            else:
                return {"role": role, "content": content}
        elif role == "tool":
            if tool_call_id:  # If there's a tool call ID, add it to the message
                return {"role": role, "tool_call_id": tool_call_id, "content": content or ""}
            else:
                raise ValueError("role='tool' requires tool_call_id to match tool result to the call")
        else:
            raise ValueError(f"Unsupported role type: {role}")
    
    def call_model(self, model: str, messages: list, tools: list) -> LLMResponse:
        messages_t = self.client.chat.completions.create(model=model, messages=messages, tools=tools)
        response = messages_t.choices[0].message
        text = response.content
        tool_calls = []
        if response.tool_calls:
            for item in response.tool_calls:
                tool_calls.append(ToolCall(item.id, item.function.name, json.loads(item.function.arguments)))
        return LLMResponse(text, tool_calls)  # Return only text and tool calls from model response