from typing import Any, cast

from anthropic import Anthropic
from anthropic.types import MessageParam, TextBlock, ToolParam, ToolUseBlock

from linkforge.llm.base import LLM, LLMMessage, LLMResponse, ToolCall


class AnthropicInterface(LLM):
    def __init__(self, api_key: str, base_url: str | None = None):
        self.client = Anthropic(api_key=api_key, base_url=base_url)

    def _convert_tool_calls(self, tool_calls: tuple[ToolCall, ...]) -> list[dict[str, Any]]:
        """Convert LinkForge tool calls to Anthropic tool-use blocks."""
        anthropic_tool_calls = []

        for tool_call in tool_calls:
            anthropic_tool_calls.append(
                {
                    "type": "tool_use",
                    "id": tool_call.id,
                    "name": tool_call.name,
                    "input": tool_call.arguments,
                }
            )

        return anthropic_tool_calls

    def _convert_tools(self, tools: list[Any]) -> list[ToolParam]:
        """Convert LinkForge/OpenAI-style tool definitions to Anthropic format."""
        anthropic_tools: list[ToolParam] = []

        for tool in tools:
            if not isinstance(tool, dict):
                raise TypeError("Tool definition must be a dictionary")

            function = tool.get("function")

            if tool.get("type") != "function" or not isinstance(function, dict):
                raise ValueError("Anthropic adapter currently supports function tools only")

            name = function.get("name")
            description = function.get("description")
            parameters = function.get("parameters")

            if not isinstance(name, str):
                raise ValueError("Tool definition requires a string 'name'")

            if not isinstance(parameters, dict):
                raise ValueError(f"Tool '{name}' requires a dictionary 'parameters' schema")

            anthropic_tool: ToolParam = {
                "name": name,
                "input_schema": cast(Any, parameters),
            }

            if isinstance(description, str):
                anthropic_tool["description"] = description

            anthropic_tools.append(anthropic_tool)

        return anthropic_tools

    def _convert_message(self, message: LLMMessage) -> dict[str, Any] | None:
        """Convert a LinkForge message to Anthropic message format."""
        role = message.role

        if role == "system":
            return None

        if role == "user":
            if message.images:
                blocks: list[dict[str, Any]] = []
                if message.content:
                    blocks.append({"type": "text", "text": message.content})
                blocks.extend(
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": image.media_type,
                            "data": image.base64_data(),
                        },
                    }
                    for image in message.images
                )
                return {"role": "user", "content": blocks}
            return {
                "role": "user",
                "content": message.content or "",
            }

        if role == "assistant":
            if message.tool_calls:
                content_blocks: list[dict[str, Any]] = []

                if message.content:
                    content_blocks.append(
                        {
                            "type": "text",
                            "text": message.content,
                        }
                    )

                content_blocks.extend(self._convert_tool_calls(message.tool_calls))

                return {
                    "role": "assistant",
                    "content": content_blocks,
                }

            return {
                "role": "assistant",
                "content": message.content or "",
            }

        if role == "tool":
            if not message.tool_call_id:
                raise ValueError("role='tool' requires tool_call_id to match tool result to the call")

            return {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": message.tool_call_id,
                        "content": message.content or "",
                    }
                ],
            }

        raise ValueError(f"Unsupported role type: {role}")

    def call_model(
        self,
        model: str,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]],
    ) -> LLMResponse:
        """Call an Anthropic model and normalize its response."""
        anthropic_messages: list[MessageParam] = []
        system_prompt: str | None = None

        for message in messages:
            if message.role == "system":
                system_prompt = message.content
                continue

            converted_message = self._convert_message(message)
            if converted_message is None:
                continue
            anthropic_messages.append(cast(MessageParam, converted_message))

        anthropic_tools = self._convert_tools(tools)

        if system_prompt:
            message_t = self.client.messages.create(
                model=model,
                max_tokens=1024,
                system=system_prompt,
                messages=anthropic_messages,
                tools=anthropic_tools,
            )
        else:
            message_t = self.client.messages.create(
                model=model,
                max_tokens=1024,
                messages=anthropic_messages,
                tools=anthropic_tools,
            )

        text: str | None = None
        tool_calls: list[ToolCall] = []

        for content_block in message_t.content:
            if isinstance(content_block, TextBlock):
                text = content_block.text

            elif isinstance(content_block, ToolUseBlock):
                tool_calls.append(
                    ToolCall(
                        id=content_block.id,
                        name=content_block.name,
                        arguments=content_block.input,
                    )
                )

        return LLMResponse(
            content=text,
            tool_calls=tool_calls,
        )
