"""在独立网络线程上运行可取消的异步请求，避免占用 Playwright 的事件循环。"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from collections.abc import Callable, Coroutine
from contextlib import suppress
from dataclasses import dataclass, field
from threading import Event, Thread
from typing import Any
from uuid import uuid4

from linkforge.llm.base import LLMMessage
from linkforge.llm.errors import ModelRequestCancelledError, ModelRequestError, model_failure_reason

logger = logging.getLogger(__name__)
REQUEST_TIMEOUT_SECONDS = 300.0
PROGRESS_INTERVAL_SECONDS = 15.0
POLL_INTERVAL_SECONDS = 0.1


def _count(value: Any) -> int:
    return value if type(value) is int and value >= 0 else 0


@dataclass
class RequestProgress:
    """只记录数值和本地产生的标识，不保存服务端正文或请求参数。"""

    request_id: str = field(default_factory=lambda: uuid4().hex[:12])
    started: float = field(default_factory=time.monotonic)
    chunks: int = 0
    content_chars: int = 0
    reasoning_chars: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    first_chunk_seconds: float | None = None
    last_chunk_at: float | None = None

    def chunk(self, *, content: Any = None, reasoning: Any = None) -> None:
        self.chunks += 1
        self.last_chunk_at = time.monotonic()
        self.content_chars += len(content) if isinstance(content, str) else 0
        self.reasoning_chars += len(reasoning) if isinstance(reasoning, str) else 0
        if self.first_chunk_seconds is None:
            self.first_chunk_seconds = time.monotonic() - self.started
            logger.info(
                "模型请求 %s：收到首个数据块，耗时 %.1f 秒（不代表已生成答案）",
                self.request_id,
                self.first_chunk_seconds,
            )

    def usage(self, usage: Any) -> None:
        self.input_tokens = _count(getattr(usage, "prompt_tokens", getattr(usage, "input_tokens", None)))
        self.output_tokens = _count(
            getattr(usage, "completion_tokens", getattr(usage, "output_tokens", None))
        )
        details = getattr(usage, "completion_tokens_details", None)
        self.reasoning_tokens = _count(getattr(details, "reasoning_tokens", None))

    def report(self, state: str) -> None:
        first = f"{self.first_chunk_seconds:.1f}s" if self.first_chunk_seconds is not None else "未收到"
        idle = (
            f"{time.monotonic() - self.last_chunk_at:.1f}s" if self.last_chunk_at is not None else "未收到"
        )
        logger.info(
            "模型请求 %s：%s，已用 %.1f 秒，首块=%s，距上次数据=%s，数据块=%d，答案字符=%d，"
            "推理字符=%d，输入/输出/推理 token=%d/%d/%d（用量由服务商提供，缺省为0）",
            self.request_id,
            state,
            time.monotonic() - self.started,
            first,
            idle,
            self.chunks,
            self.content_chars,
            self.reasoning_chars,
            self.input_tokens,
            self.output_tokens,
            self.reasoning_tokens,
        )


def run_request[T](
    operation: Callable[[RequestProgress], Coroutine[Any, Any, T]],
    *,
    should_stop: Callable[[], bool],
    provider: str,
    model: str,
    messages: list[LLMMessage],
) -> T:
    """同步桥接异步 SDK；取消后等待任务及 HTTP 客户端完成清理，无后台遗留请求。"""
    if should_stop():
        raise ModelRequestCancelledError
    progress = RequestProgress()
    images = [image for message in messages for image in message.images]
    logger.info(
        "模型请求 %s：开始，协议=%s，模型指纹=%s，消息=%d，图片=%d，图片字节=%d，上限=%.0f秒",
        progress.request_id,
        provider,
        hashlib.sha256(model.encode()).hexdigest()[:12],
        len(messages),
        len(images),
        sum(len(image.data) for image in images),
        REQUEST_TIMEOUT_SECONDS,
    )
    cancelled = Event()
    finished = Event()
    result: list[T] = []
    errors: list[BaseException] = []

    async def supervise() -> T:
        task = asyncio.create_task(operation(progress))
        next_report = time.monotonic() + PROGRESS_INTERVAL_SECONDS
        try:
            while True:
                if cancelled.is_set():
                    raise ModelRequestCancelledError
                elapsed = time.monotonic() - progress.started
                if elapsed >= REQUEST_TIMEOUT_SECONDS:
                    raise TimeoutError
                done, _ = await asyncio.wait({task}, timeout=POLL_INTERVAL_SECONDS)
                # 停止优先于同时到达的答案，避免随后点击或提交。
                if cancelled.is_set():
                    raise ModelRequestCancelledError
                if done:
                    return task.result()
                if time.monotonic() >= next_report:
                    progress.report("等待响应" if not progress.chunks else "正在接收")
                    next_report = time.monotonic() + PROGRESS_INTERVAL_SECONDS
        finally:
            if not task.done():
                task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await task

    def work() -> None:
        try:
            result.append(asyncio.run(supervise()))
        except BaseException as exc:
            errors.append(exc)
        finally:
            finished.set()

    thread = Thread(target=work, name="linkforge-model-request")
    thread.start()
    try:
        while not finished.wait(POLL_INTERVAL_SECONDS):
            if should_stop():
                cancelled.set()
    finally:
        # 也处理调用者被异常中断的情况。
        cancelled.set()
        thread.join()
    if should_stop() or (errors and isinstance(errors[0], ModelRequestCancelledError)):
        progress.report("已取消，连接已关闭")
        raise ModelRequestCancelledError
    if errors:
        exc = errors[0]
        if not isinstance(exc, Exception):
            raise exc
        status = getattr(exc, "status_code", None)
        safe_status = status if type(status) is int and 100 <= status <= 599 else None
        # 不使用异常正文、响应头、原始 URL 或服务端 request_id。
        logger.warning(
            "模型请求 %s：失败，HTTP=%s，原因=%s",
            progress.request_id,
            safe_status or "无",
            model_failure_reason(exc),
        )
        progress.report("失败")
        raise ModelRequestError.from_exception(exc) from None
    progress.report("完成")
    return result[0]
