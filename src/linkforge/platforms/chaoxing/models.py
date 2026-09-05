"""Typed Chaoxing DOM state shared by deterministic platform adapters."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

DOCUMENT_BOTTOM_TOLERANCE_PX = 8.0


def _number(value: object, name: str) -> float:
    """Validate and normalize one finite numeric DOM value."""
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")

    return float(value)


@dataclass(frozen=True, slots=True)
class ChaoxingModuleState:
    """One embedded module in DOM order inside the current content card."""

    url: str
    has_job_icon: bool
    finished: bool


@dataclass(frozen=True, slots=True)
class ChaoxingVideoState:
    """Provider-neutral HTMLMediaElement state from one video module frame."""

    frame_url: str
    paused: bool
    ended: bool
    current_time: float
    duration: float | None
    ready_state: int


@dataclass(frozen=True, slots=True)
class ChaoxingPageState:
    """Validated snapshot of the active Chaoxing card and its video frames."""

    content_frame_url: str
    knowledge_id: str | None
    active_tab_index: int
    has_next_tab: bool
    modules: tuple[ChaoxingModuleState, ...]
    videos: tuple[ChaoxingVideoState, ...]


@dataclass(frozen=True, slots=True)
class ChaoxingDocumentModuleState:
    """Outer-card metadata for one PDF module."""

    module_index: int
    module_url: str
    object_id: str
    declared_page_count: int | None
    has_job_icon: bool
    finished: bool

    @classmethod
    def from_raw(
        cls,
        raw: object,
        *,
        module_index: int,
    ) -> ChaoxingDocumentModuleState:
        """Validate and convert one content-frame PDF module."""
        if not isinstance(raw, dict):
            raise ValueError("document module state must be an object")

        value: dict[str, Any] = raw

        module_url = value.get("module_url")
        object_id = value.get("object_id")
        declared_page_count = value.get("declared_page_count")
        has_job_icon = value.get("has_job_icon")
        finished = value.get("finished")

        if not isinstance(module_url, str) or "/ananas/modules/pdf/" not in module_url:
            raise ValueError("module_url must identify a Chaoxing PDF module")

        if not isinstance(object_id, str) or not object_id:
            raise ValueError("object_id must be a non-empty string")

        if declared_page_count is not None and (
            not isinstance(declared_page_count, int)
            or isinstance(declared_page_count, bool)
            or declared_page_count <= 0
        ):
            raise ValueError("declared_page_count must be a positive integer or null")

        if not isinstance(has_job_icon, bool) or not isinstance(finished, bool):
            raise ValueError("has_job_icon and finished must be bools")

        if finished and not has_job_icon:
            raise ValueError("a document without a job icon cannot be job-finished")

        return cls(
            module_index=module_index,
            module_url=module_url,
            object_id=object_id,
            declared_page_count=declared_page_count,
            has_job_icon=has_job_icon,
            finished=finished,
        )


@dataclass(frozen=True, slots=True)
class ChaoxingDocumentViewerState:
    """Continuous-scroll state for one final Chaoxing PDF viewer frame."""

    object_id: str
    page_count: int
    visible_pages: tuple[int, ...]
    scroll_y: float
    inner_height: float
    scroll_height: float
    bottom_distance: float
    at_bottom: bool

    @classmethod
    def from_raw(
        cls,
        raw: object,
    ) -> ChaoxingDocumentViewerState:
        """Validate viewer metrics and derive bottom state with tolerance."""
        if not isinstance(raw, dict):
            raise ValueError("document viewer state must be an object")

        value: dict[str, Any] = raw

        object_id = value.get("object_id")
        page_count = value.get("page_count")
        raw_visible_pages = value.get("visible_pages")

        if not isinstance(object_id, str) or not object_id:
            raise ValueError("viewer object_id must be a non-empty string")

        if not isinstance(page_count, int) or isinstance(page_count, bool) or page_count < 0:
            raise ValueError("viewer page_count must be a non-negative integer")

        if not isinstance(raw_visible_pages, list) or not all(
            isinstance(page, int) and not isinstance(page, bool) and page > 0 for page in raw_visible_pages
        ):
            raise ValueError("viewer visible_pages must contain positive integers")

        scroll_y = _number(
            value.get("scroll_y"),
            "scroll_y",
        )

        inner_height = _number(
            value.get("inner_height"),
            "inner_height",
        )

        scroll_height = _number(
            value.get("scroll_height"),
            "scroll_height",
        )

        if scroll_y < 0 or inner_height <= 0 or scroll_height <= 0:
            raise ValueError("viewer scroll metrics are outside their valid ranges")

        bottom_distance = scroll_height - (scroll_y + inner_height)

        return cls(
            object_id=object_id,
            page_count=page_count,
            visible_pages=tuple(raw_visible_pages),
            scroll_y=scroll_y,
            inner_height=inner_height,
            scroll_height=scroll_height,
            bottom_distance=bottom_distance,
            at_bottom=(bottom_distance <= DOCUMENT_BOTTOM_TOLERANCE_PX),
        )
