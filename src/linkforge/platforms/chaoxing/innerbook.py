"""Validated state and run-scoped completion for continuous-scroll innerbooks."""

from dataclasses import dataclass
from urllib.parse import urlsplit

from linkforge.platforms.chaoxing.models import _number

INNERBOOK_MODULE_PATH = "/ananas/modules/innerbook/"


def is_innerbook(url: str) -> bool:
    """Recognize the module route, excluding query-string lookalikes."""
    return urlsplit(url).path.startswith(INNERBOOK_MODULE_PATH)


def frame_path(value: object) -> tuple[int, ...]:
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(item, int) and not isinstance(item, bool) and item >= 0 for item in value)
    ):
        raise ValueError("innerbook frame path is missing or malformed")
    return tuple(value)


@dataclass(frozen=True, slots=True)
class InnerbookViewer:
    """One loaded book reader, associated by its exact iframe ancestry."""

    url: str
    path: tuple[int, ...]
    scroll_y: float
    height: float
    scroll_height: float
    page_count: int
    visible_pages_ready: bool

    @classmethod
    def from_raw(cls, raw: object) -> "InnerbookViewer":
        if not isinstance(raw, dict):
            raise ValueError("innerbook reader must be an object")
        url = raw.get("url")
        count = raw.get("page_count")
        ready = raw.get("visible_pages_ready")
        if not isinstance(url, str) or not url or not isinstance(ready, bool):
            raise ValueError("innerbook reader identity or readiness is malformed")
        if not isinstance(count, int) or isinstance(count, bool) or count <= 0:
            raise ValueError("innerbook page count must be positive")
        scroll_y = _number(raw.get("scroll_y"), "innerbook scroll_y")
        height = _number(raw.get("height"), "innerbook height")
        scroll_height = _number(raw.get("scroll_height"), "innerbook scroll_height")
        if scroll_y < 0 or height <= 0 or scroll_height < height or scroll_y > scroll_height - height + 8:
            raise ValueError("innerbook scroll metrics are inconsistent")
        return cls(url, frame_path(raw.get("frame_path")), scroll_y, height, scroll_height, count, ready)

    @property
    def at_bottom(self) -> bool:
        return self.scroll_height - self.scroll_y - self.height <= 8


def find_innerbook_viewer(
    raw_module: dict[str, object], viewers: tuple[InnerbookViewer, ...]
) -> InnerbookViewer | None:
    module_path = frame_path(raw_module.get("frame_path"))
    matches = [viewer for viewer in viewers if viewer.path[:-1] == module_path]
    if len(matches) > 1:
        raise ValueError("innerbook reader is ambiguous")
    return matches[0] if matches else None


class InnerbookSession:
    """Remember only book readers whose real bottom was verified this run."""

    def __init__(self) -> None:
        self._handled: set[tuple[str, int, str, tuple[int, ...], str]] = set()

    def is_handled(
        self, card_url: str, index: int, module_url: str, viewer: InnerbookViewer | None
    ) -> bool:
        return (
            viewer is not None and (card_url, index, module_url, viewer.path, viewer.url) in self._handled
        )

    def mark_handled(self, card_url: str, index: int, module_url: str, viewer: InnerbookViewer) -> None:
        if not viewer.at_bottom or not viewer.visible_pages_ready:
            raise ValueError("innerbook completion requires loaded visible pages at the real bottom")
        self._handled.add((card_url, index, module_url, viewer.path, viewer.url))


@dataclass(frozen=True, slots=True)
class InnerbookTarget:
    card_url: str
    index: int
    module_url: str
    module_path: tuple[int, ...]
