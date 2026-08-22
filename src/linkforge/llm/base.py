from typing import List, Optional
from dataclasses import dataclass
from typing import Dict, Any, Callable


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


class LLMResponse:
    def __init__(self, content: str | None = None, tool_calls: List[ToolCall] | None = None):
        self.content = content
        self.tool_calls = tool_calls or []


class LLM:
    def _convert_tool_calls(self, tool_calls: List[ToolCall]) -> List[dict]:
        raise NotImplementedError("Subclass must implement _convert_tool_calls method")
    
    def _convert_messages(self, role: str, content: str | None = None, 
                         tool_calls: List[ToolCall] | None = None, 
                         tool_call_id: str | None = None) -> dict:
        raise NotImplementedError("Subclass must implement _convert_messages method")
    
    def call_model(self, model: str, messages: list, tools: list) -> LLMResponse:
        raise NotImplementedError("Subclass must implement call_model method")