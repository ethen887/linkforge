"""Unit tests for typed Chaoxing document state parsing."""

import pytest

from linkforge.platforms.chaoxing.models import (
    ChaoxingDocumentModuleState,
    ChaoxingDocumentViewerState,
)


def test_module_state_preserves_platform_metadata_without_using_job_id() -> None:
    state = ChaoxingDocumentModuleState.from_raw(
        {
            "module_url": "/ananas/modules/pdf/index.html",
            "object_id": "pdf-a",
            "declared_page_count": 13,
            "has_job_icon": False,
            "finished": False,
        },
        module_index=2,
    )

    assert state.module_index == 2
    assert state.object_id == "pdf-a"
    assert state.declared_page_count == 13
    assert not state.has_job_icon


@pytest.mark.parametrize(
    ("scroll_y", "expected_bottom"),
    [(5_780.0, True), (5_779.0, False)],
)
def test_viewer_bottom_uses_eight_pixel_tolerance(
    scroll_y: float,
    expected_bottom: bool,
) -> None:
    state = ChaoxingDocumentViewerState.from_raw(
        {
            "object_id": "pdf-a",
            "page_count": 13,
            "visible_pages": [12, 13],
            "scroll_y": scroll_y,
            "inner_height": 546,
            "scroll_height": 6_334,
        }
    )

    assert state.at_bottom is expected_bottom
    assert state.bottom_distance == 6_334 - (scroll_y + 546)


@pytest.mark.parametrize(
    "raw",
    [
        None,
        {"object_id": "", "page_count": 1, "visible_pages": []},
        {
            "object_id": "pdf-a",
            "page_count": True,
            "visible_pages": [],
            "scroll_y": 0,
            "inner_height": 546,
            "scroll_height": 1_230,
        },
        {
            "object_id": "pdf-a",
            "page_count": 1,
            "visible_pages": [False],
            "scroll_y": 0,
            "inner_height": 546,
            "scroll_height": 1_230,
        },
    ],
)
def test_viewer_rejects_malformed_state(raw: object) -> None:
    with pytest.raises(ValueError):
        ChaoxingDocumentViewerState.from_raw(raw)
