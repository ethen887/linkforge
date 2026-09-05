"""Parsing helpers for Chaoxing document frame inspection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from linkforge.platforms.chaoxing.models import (
    ChaoxingDocumentModuleState,
    ChaoxingDocumentViewerState,
)


@dataclass(frozen=True, slots=True)
class ChaoxingDocumentInspection:
    """Validated content modules and viewers from one all-frame snapshot."""

    modules: tuple[dict[str, object], ...]
    viewers: dict[str, ChaoxingDocumentViewerState]


def parse_document_inspection(
    frame_results: tuple[object, ...],
) -> ChaoxingDocumentInspection | None:
    """Parse one current-card snapshot, returning None while frames are replacing."""
    active_tab_count = 0
    content_frames: list[dict[str, Any]] = []
    viewers: dict[str, ChaoxingDocumentViewerState] = {}

    for result in frame_results:
        if not isinstance(result, dict):
            raise ValueError("every frame inspection result must be an object")
        frame_url = result.get("frame_url")
        frame_active_tab_count = result.get("active_tab_count")
        if (
            not isinstance(frame_url, str)
            or not isinstance(frame_active_tab_count, int)
            or isinstance(frame_active_tab_count, bool)
            or frame_active_tab_count < 0
        ):
            raise ValueError("malformed Chaoxing frame state")

        active_tab_count += frame_active_tab_count
        if "/mooc-ans/knowledge/cards" in frame_url:
            content_frames.append(result)

        raw_viewer = result.get("viewer")
        if raw_viewer is not None:
            viewer = ChaoxingDocumentViewerState.from_raw(raw_viewer)
            if viewer.object_id in viewers:
                raise ValueError(f"duplicate viewer for object_id={viewer.object_id!r}")
            viewers[viewer.object_id] = viewer

    if active_tab_count != 1 or len(content_frames) != 1:
        return None

    raw_modules = content_frames[0].get("modules")
    if not isinstance(raw_modules, list):
        raise ValueError("Chaoxing content-frame modules must be a list")
    modules: list[dict[str, object]] = []
    for raw_module in raw_modules:
        if not isinstance(raw_module, dict):
            raise ValueError("every Chaoxing module state must be an object")
        modules.append(raw_module)

    return ChaoxingDocumentInspection(modules=tuple(modules), viewers=viewers)


def parse_module_basics(raw_module: dict[str, object]) -> tuple[str, bool, bool]:
    """Validate fields shared by document and non-document modules."""
    module_url = raw_module.get("module_url")
    has_job_icon = raw_module.get("has_job_icon")
    finished = raw_module.get("finished")
    if (
        not isinstance(module_url, str)
        or not isinstance(has_job_icon, bool)
        or not isinstance(finished, bool)
    ):
        raise ValueError("malformed Chaoxing module state")
    return module_url, has_job_icon, finished


def document_viewer_is_ready(
    module: ChaoxingDocumentModuleState,
    viewer: ChaoxingDocumentViewerState | None,
) -> bool:
    """Return whether the final viewer has mounted its declared pages."""
    if viewer is None or viewer.page_count <= 0:
        return False
    return module.declared_page_count is None or viewer.page_count >= module.declared_page_count
