from anthropic import Anthropic
from anthropic.types import TextBlock, ToolUseBlock

from linkforge.llm.base import LLM, LLMResponse, ToolCall


class AnthropicInterface(LLM):
    def __init__(self, api_key: str):
        self.client = Anthropic(api_key=api_key)

    def _convert_tool_calls(self, tool_calls: list[ToolCall]) -> list[dict]:
        """Convert tool calls to Anthropic format"""
        anthropic_tool_calls = []
        for tool_call in tool_calls:
            anthropic_tool_calls.append(
                {
                    "type": "tool_use",
                    "id": tool_call.id,
                    "name": tool_call.name,
                    "input": tool_call.arguments,  # Anthropic's input accepts dict directly
                }
            )
        return anthropic_tool_calls

    def _convert_messages(
        self,
        role: str,
        content: str | None = None,
        tool_calls: list[ToolCall] | None = None,
        tool_call_id: str | None = None,
    ) -> dict | None:
        if role == "system":
            # Anthropic's system prompt is not part of messages, return None here
            # It will be extracted in call_model
            return None
        elif role == "user":
            return {"role": role, "content": content}
        elif role == "assistant":
            if tool_calls:
                # In Anthropic, assistant messages need to combine text and
                #  tool calls in content blocks
                content_blocks = []
                if content:
                    content_blocks.append({"type": "text", "text": content})
                content_blocks.extend(self._convert_tool_calls(tool_calls))
                return {"role": role, "content": content_blocks}
            else:
                return {"role": role, "content": content}
        elif role == "tool":
            if tool_call_id:
                # In Anthropic, tool results appear as tool_result blocks under user role
                return {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": tool_call_id,
                            "content": content or "",
                        }
                    ],
                }
            else:
                raise ValueError(
                    "role='tool' requires tool_call_id to match tool result to the call"
                )
        else:
            raise ValueError(f"Unsupported role type: {role}")

    def call_model(self, model: str, message: list, tools: list) -> LLMResponse:
        system_prompt = None
        new_message = []
        for item in message:  # Extract system prompt and user input from message
            if item["role"] == "system":
                system_prompt = item["content"]
            else:
                new_message.append(item)

        message_t = self.client.messages.create(
            model=model, system=system_prompt, messages=new_message, tools=tools
        )
        text = None
        tool_calls = []
        for item in message_t.content:
            if isinstance(item, TextBlock):
                text = item.text
            elif isinstance(item, ToolUseBlock):
                tool_calls.append(ToolCall(item.id, item.name, item.input))

        return LLMResponse(content=text, tool_calls=tool_calls)
