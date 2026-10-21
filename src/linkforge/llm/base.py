import base64
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class ToolCall:
    """模型生成的工具调用，描述需要执行的函数及其参数。"""

    id: str
    name: str
    arguments: dict


type MessageRole = Literal["system", "user", "assistant", "tool"]


@dataclass(frozen=True, slots=True)
class LLMImage:
    """内存中的图片输入；线上编码格式由各适配器负责。"""

    data: bytes = field(repr=False)
    media_type: Literal["image/png", "image/jpeg", "image/webp", "image/gif"] = "image/png"

    def __post_init__(self) -> None:
        if not isinstance(self.data, bytes) or not self.data:
            raise ValueError("Image data must be non-empty bytes")
        if self.media_type not in ("image/png", "image/jpeg", "image/webp", "image/gif"):
            raise ValueError("Unsupported image media type")

    def base64_data(self) -> str:
        """将图片字节编码为 ASCII 字符串形式的 base64 数据，供线上传输使用。"""
        return base64.b64encode(self.data).decode("ascii")


@dataclass(frozen=True, slots=True)
class LLMMessage:
    """与具体服务商无关的 LinkForge 模型对话消息。"""

    role: MessageRole
    content: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None
    images: tuple[LLMImage, ...] = ()

    def __post_init__(self) -> None:
        if self.images and self.role != "user":
            raise ValueError("Image inputs are supported only on user messages")


class LLMResponse:
    """归一化的模型调用结果，包含文本内容、工具调用与结束原因。"""

    def __init__(
        self,
        content: str | None = None,
        tool_calls: list[ToolCall] | None = None,
        *,
        finish_reason: str | None = None,
    ):
        self.content = content
        self.tool_calls = tool_calls or []
        self.finish_reason = finish_reason


class LLM:
    """模型客户端的抽象基类，定义对话调用与 JSON 调用接口。"""

    def configure_runtime(self, *, should_stop: Callable[[], bool]) -> None:
        """接入应用的协作停止；网络适配器据此启用可取消请求。"""
        self._should_stop = should_stop

    def close(self) -> None:
        """释放模型客户端资源；无资源的测试替身无需实现。"""

    def call_json_model(self, model: str, messages: list[LLMMessage]) -> LLMResponse:
        """请求 JSON 输出；在适配器确认支持时，可能会约束输出格式。"""
        return self.call_model(model, messages, [])

    def call_model(
        self,
        model: str,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]],
    ) -> LLMResponse:
        raise NotImplementedError("Subclass must implement call_model method")
