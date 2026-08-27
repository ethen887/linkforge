from typing import Any, cast

from anthropic import Anthropic
from anthropic.types import MessageParam, TextBlock, ToolParam, ToolUseBlock

from linkforge.llm.base import LLM, LLMResponse, ToolCall


class AnthropicInterface(LLM):
    def __init__(self, api_key: str):
        self.client = Anthropic(api_key=api_key)

        # Anthropic system prompt is sent as a top-level request parameter,
        # not as an item inside the messages list.
        self._system_prompt: str | None = None

    def _convert_tool_calls(self, tool_calls: list[ToolCall]) -> list[dict]:
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

    def _convert_messages(
        self,
        role: str,
        content: str | None = None,
        tool_calls: list[ToolCall] | None = None,
        tool_call_id: str | None = None,
    ) -> dict | None:
        """Convert a LinkForge message to Anthropic message format."""
        if role == "system":
            # Anthropic does not support "system" as a message role.
            # Save it and later pass it through messages.create(system=...).
            self._system_prompt = content
            return None

        if role == "user":
            return {
                "role": "user",
                "content": content or "",
            }

        if role == "assistant":
            if tool_calls:
                content_blocks: list[dict] = []

                if content:
                    content_blocks.append(
                        {
                            "type": "text",
                            "text": content,
                        }
                    )

                content_blocks.extend(self._convert_tool_calls(tool_calls))

                return {
                    "role": "assistant",
                    "content": content_blocks,
                }

            return {
                "role": "assistant",
                "content": content or "",
            }

        if role == "tool":
            if not tool_call_id:
                raise ValueError("role='tool' requires tool_call_id to match tool result to the call")

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

        raise ValueError(f"Unsupported role type: {role}")

    def call_model(self, model: str, messages: list, tools: list) -> LLMResponse:
        """Call an Anthropic model and normalize its response."""
        anthropic_messages: list[MessageParam] = []

        for item in messages:
            # _convert_messages() intentionally returns None for system messages.
            if item is None:
                continue

            anthropic_messages.append(cast(MessageParam, item))

        anthropic_tools = self._convert_tools(tools)

        if self._system_prompt:
            message_t = self.client.messages.create(
                model=model,
                max_tokens=1024,
                system=self._system_prompt,
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

        for item in message_t.content:
            if isinstance(item, TextBlock):
                text = item.text

            elif isinstance(item, ToolUseBlock):
                tool_calls.append(
                    ToolCall(
                        id=item.id,
                        name=item.name,
                        arguments=item.input,
                    )
                )

        return LLMResponse(
            content=text,
            tool_calls=tool_calls,
        )
