import json
from typing import Any, cast

from openai import AsyncOpenAI, OpenAI

from linkforge.llm.base import LLM, LLMMessage, LLMResponse, ToolCall
from linkforge.llm.errors import ModelRequestCancelledError, ModelRequestError
from linkforge.llm.request_runtime import REQUEST_TIMEOUT_SECONDS, RequestProgress, run_request

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
            timeout=REQUEST_TIMEOUT_SECONDS,
            max_retries=0,
        )

    def close(self) -> None:
        self.client.close()

    async def _stream(self, progress: RequestProgress, options: dict[str, Any]) -> Any:
        async with AsyncOpenAI(
            api_key=self.client.api_key,
            base_url=self.client.base_url,
            timeout=REQUEST_TIMEOUT_SECONDS,
            max_retries=0,
        ) as client:
            async with client.chat.completions.stream(**options) as stream:
                async for event in stream:
                    if event.type == "chunk":
                        chunk = event.chunk
                        # 部分兼容服务会附加 reasoning_content，只统计字符数。
                        for choice in chunk.choices:
                            progress.chunk(
                                content=choice.delta.content,
                                reasoning=getattr(choice.delta, "reasoning_content", None),
                            )
                        if not chunk.choices:
                            progress.chunk()
                        if chunk.usage is not None:
                            progress.usage(chunk.usage)
                completion = await stream.get_final_completion()
                if completion.usage is not None:
                    progress.usage(completion.usage)
                return completion

    def _convert_tool_calls(self, tool_calls: tuple[ToolCall, ...]) -> list[dict[str, Any]]:
        """将 LinkForge 的工具调用转换为 OpenAI 的函数工具调用格式。"""
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
        """将 LinkForge 消息转换为 OpenAI 消息格式。"""
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
        """调用兼容 OpenAI 接口的模型并将其响应归一化。"""
        return self._call(model, messages, tools)

    def call_json_model(self, model: str, messages: list[LLMMessage]) -> LLMResponse:
        # 刻意按端点限定：任意的 OpenAI 兼容代理未必都实现 response_format，
        # 即使其协议与 Chat Completions 恰好匹配。
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
        options = dict(
            model=model,
            messages=cast(Any, openai_messages),
            **({"tools": cast(Any, tools)} if tools else {}),
            **({"response_format": cast(Any, {"type": "json_object"})} if json_object else {}),
        )
        should_stop = getattr(self, "_should_stop", None)
        try:
            if should_stop is not None:
                messages_t = run_request(
                    lambda progress: self._stream(progress, options),
                    should_stop=should_stop,
                    provider="openai-compatible",
                    model=model,
                    messages=messages,
                )
            else:
                messages_t = self.client.chat.completions.create(**options)
        except ModelRequestCancelledError:
            raise
        except Exception as exc:
            raise ModelRequestError.from_exception(exc) from exc

        response = messages_t.choices[0].message
        text = response.content
        tool_calls: list[ToolCall] = []

        if response.tool_calls:
            for item in response.tool_calls:
                # OpenAI SDK 可能返回不同的工具调用变体。
                # LinkForge 目前只支持函数工具调用。
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
