"""Playwright 对文档绑定的 BrowserElement 引用的实现。"""

from collections.abc import Iterator
from contextlib import contextmanager

from playwright.sync_api import ElementHandle, Error, Frame, Page

from linkforge.browser.element import BrowserElement
from linkforge.browser.exceptions import BrowserElementError, BrowserError


class _Element:
    def __init__(self, handle: ElementHandle, scope: list[ElementHandle], page: Page) -> None:
        self._handle = handle
        self._scope = scope
        self._page = page
        scope.append(handle)

    def _require_live(self) -> None:
        if self._handle not in self._scope or self._page.is_closed():
            raise BrowserElementError("DOM element scope is closed.")
        if not self._handle.evaluate("element => element.isConnected"):
            raise BrowserElementError("Captured DOM element has been detached.")

    def query_all(self, selector: str) -> tuple[BrowserElement, ...]:
        try:
            self._require_live()
            return tuple(
                _Element(h, self._scope, self._page) for h in self._handle.query_selector_all(selector)
            )
        except Error as exc:
            raise BrowserElementError("Failed to query scoped DOM elements.") from exc

    def evaluate(self, expression: str) -> object:
        try:
            self._require_live()
            return self._handle.evaluate(expression)
        except Error as exc:
            raise BrowserElementError("Failed to inspect scoped DOM element.") from exc

    def screenshot(self) -> bytes:
        try:
            self._require_live()
            self._handle.scroll_into_view_if_needed()
            return self._handle.screenshot(type="png")
        except Error as exc:
            raise BrowserElementError("Failed to capture scoped DOM element.") from exc

    def click(self) -> None:
        try:
            self._require_live()
            self._handle.click()
        except Error as exc:
            raise BrowserElementError("Failed to click scoped DOM element.") from exc

    def scroll_into_view(self) -> None:
        try:
            self._require_live()
            self._handle.evaluate(
                "e => e.scrollIntoView({block:'center',inline:'nearest',behavior:'instant'})"
            )
        except Error as exc:
            raise BrowserElementError("Failed to bring scoped DOM element into view.") from exc

    def fill(self, text: str) -> None:
        try:
            self._require_live()
            self._handle.fill(text)
        except Error as exc:
            raise BrowserElementError("Failed to fill scoped DOM element.") from exc

    def press(self, key: str) -> None:
        try:
            self._require_live()
            self._handle.press(key)
        except Error as exc:
            raise BrowserElementError("Failed to press scoped DOM element.") from exc

    def type_text(self, text: str) -> None:
        try:
            self._require_live()
            self._handle.focus()
            self._page.keyboard.insert_text(text)
        except Error as exc:
            raise BrowserElementError("Failed to type in scoped DOM element.") from exc

    def frame_query_all(self, selector: str) -> tuple[BrowserElement, ...]:
        try:
            self._require_live()
            frame = self._handle.content_frame()
            if frame is None:
                raise BrowserElementError("Scoped frame is not ready.")
            return tuple(_Element(h, self._scope, self._page) for h in frame.query_selector_all(selector))
        except Error as exc:
            raise BrowserElementError("Failed to query scoped frame.") from exc


def _under(frame: Frame, ancestor: Frame) -> bool:
    parent = frame.parent_frame
    while parent is not None:
        if parent == ancestor:
            return True
        parent = parent.parent_frame
    return False


@contextmanager
def element_scope(
    page: Page, frame_url_contains: str, selector: str, *, ancestor_url: str, include_ancestor: bool = False
) -> Iterator[tuple[BrowserElement, ...]]:
    """在恰好一个后代 frame 中定位可交互元素并返回可用的 BrowserElement 集合。

    要求恰好匹配一个祖先 frame 和一个同样唯一的后代 frame，否则抛出 BrowserError。
    通过上下文管理器使用，退出时释放所有捕获元素的句柄；配合 include_ancestor
    可在祖先 frame 本身成为目标时也参与匹配。
    """
    handles: list[ElementHandle] = []
    try:
        ancestors = [frame for frame in page.frames if frame.url == ancestor_url]
        if len(ancestors) != 1:
            raise BrowserError("Expected exactly one ancestor frame for DOM element scope.")
        frames = [
            frame
            for frame in page.frames
            if frame_url_contains in frame.url
            and (_under(frame, ancestors[0]) or (include_ancestor and frame == ancestors[0]))
        ]
        if len(frames) != 1:
            raise BrowserError("Expected exactly one descendant frame for DOM element scope.")
        elements = tuple(_Element(h, handles, page) for h in frames[0].query_selector_all(selector))
    except Error as exc:
        raise BrowserElementError("Failed to open DOM element scope.") from exc
    try:
        yield elements
    finally:
        # 导航后的文档可能已释放其远程句柄。
        for handle in handles:
            try:
                handle.dispose()
            except Error:
                pass
        handles.clear()
