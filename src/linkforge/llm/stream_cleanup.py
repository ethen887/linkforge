"""在 SDK 提前结束 SSE 消费时，按嵌套顺序关闭 HTTP 字节迭代器。"""

from collections.abc import AsyncIterator
from typing import Any

try:
    import httpx2 as httpx
except ImportError:
    import httpx  # type: ignore[no-redef]


class ClosingByteStream(httpx.AsyncByteStream):
    def __init__(self, stream: Any) -> None:
        self._stream = stream
        self._iterator: Any = None
        self._closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        self._iterator = self._stream.__aiter__()
        try:
            async for chunk in self._iterator:
                yield chunk
        finally:
            await self.aclose()

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            if self._iterator is not None and hasattr(self._iterator, "aclose"):
                await self._iterator.aclose()
        finally:
            await self._stream.aclose()


async def own_response_stream(response: Any) -> None:
    # SSE 的 [DONE] 可以先于 HTTP EOF；不能把嵌套生成器留到事件循环并发清理。
    response.stream = ClosingByteStream(response.stream)
