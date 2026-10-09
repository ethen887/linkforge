import json
from typing import Any, cast

from openai import OpenAI

from linkforge.llm.base import LLM, LLMMessage, LLMResponse, ToolCall
from linkforge.llm.errors import ModelRequestError

_MODEL_REQUEST_TIMEOUT_SECONDS = 120.0
_JSON_OBJECT_ENDPOINTS = {
    "https://api.deepseek.com",
    "https://api.openai.com/v1",
    "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    "https://generativelanguage.googleapis.com/v1beta/openai",
}


class OpenAIInterface(LLM):
    def __init__(self, api_key: str, base_url: str | None = None):
        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=_MODEL_REQUEST_TIMEOUT_SECONDS,
            max_retries=0,
        )

    def _convert_tool_calls(self, tool_calls: tuple[ToolCall, ...]) -> list[dict[str, Any]]:
        """Convert LinkForge tool calls to OpenAI function tool-call format."""
        openai_tool_calls = []

        for tool_call in tool_calls:
            openai_tool_calls.append(
                {
                    "id": tool_call.id,
                    "type": "function",
                    "function": {
                        "name": tool_call.name,
                        "arguments": json.dumps(
                            tool_call.arguments,
                            ensure_ascii=False,
                        ),
                    },
                }
            )

        return openai_tool_calls

    def _convert_message(self, message: LLMMessage) -> dict[str, Any]:
        """Convert a LinkForge message to OpenAI message format."""
        role = message.role

        if message.images:
            content: list[dict[str, Any]] = []
            if message.content:
                content.append({"type": "text", "text": message.content})
            content.extend(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{image.media_type};base64,{image.base64_data()}"},
                }
                for image in message.images
            )
            return {"role": role, "content": content}

        if role in ("system", "user"):
            return {
                "role": role,
                "content": message.content,
            }

        if role == "assistant":
            if message.tool_calls:
                return {
                    "role": role,
                    "content": message.content,
                    "tool_calls": self._convert_tool_calls(message.tool_calls),
                }

            return {
                "role": role,
                "content": message.content,
            }

        if role == "tool":
            if not message.tool_call_id:
                raise ValueError("role='tool' requires tool_call_id to match tool result to the call")

            return {
                "role": role,
                "tool_call_id": message.tool_call_id,
                "content": message.content or "",
            }

        raise ValueError(f"Unsupported role type: {role}")

    def call_model(
        self,
        model: str,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]],
    ) -> LLMResponse:
        """Call an OpenAI-compatible model and normalize its response."""
        return self._call(model, messages, tools)

    def call_json_model(self, model: str, messages: list[LLMMessage]) -> LLMResponse:
        # Deliberately endpoint-scoped: arbitrary OpenAI-compatible proxies do
        # not necessarily implement response_format even when their protocol
        # otherwise matches Chat Completions.
        endpoint = str(self.client.base_url).rstrip("/")
        return self._call(model, messages, [], json_object=endpoint in _JSON_OBJECT_ENDPOINTS)

    def _call(
        self,
        model: str,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]],
        *,
        json_object: bool = False,
    ) -> LLMResponse:
        openai_messages = [self._convert_message(message) for message in messages]
        try:
            messages_t = self.client.chat.completions.create(
                model=model,
                messages=cast(Any, openai_messages),
                **({"tools": cast(Any, tools)} if tools else {}),
                **({"response_format": cast(Any, {"type": "json_object"})} if json_object else {}),
            )
        except Exception as exc:
            raise ModelRequestError.from_exception(exc) from exc

        response = messages_t.choices[0].message
        text = response.content
        tool_calls: list[ToolCall] = []

        if response.tool_calls:
            for item in response.tool_calls:
                # OpenAI SDK may return different tool-call variants.
                # LinkForge currently supports function tool calls only.
                if item.type != "function":
                    continue

                arguments = json.loads(item.function.arguments)

                if not isinstance(arguments, dict):
                    raise ValueError(f"Tool '{item.function.name}' arguments must decode to a JSON object")

                tool_calls.append(
                    ToolCall(
                        id=item.id,
                        name=item.function.name,
                        arguments=arguments,
                    )
                )

        return LLMResponse(
            content=text,
            tool_calls=tool_calls,
            finish_reason=getattr(messages_t.choices[0], "finish_reason", None),
        )
