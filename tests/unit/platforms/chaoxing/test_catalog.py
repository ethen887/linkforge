"""Catalog evidence must never turn an unfinished or ambiguous node into content."""

import logging

import pytest

from linkforge.application.task_runner import TaskType
from linkforge.platforms.chaoxing.catalog import knowledge_is_completed
from linkforge.platforms.chaoxing.task_detector import ChaoxingTaskDetector
from tests.fakes import FakeBrowser

CARD_URL = "https://mooc1.chaoxing.com/mooc-ans/knowledge/cards?knowledgeid=100"


def _node(**changes: object) -> dict[str, object]:
    return {"node_id": "cur100", "active": True, "completed_count": 1, "pending_count": 0, **changes}


def _frames(nodes: list[object]) -> tuple[object, ...]:
    return (
        {
            "frame_url": "https://mooc1.chaoxing.com/mycourse/studentstudy",
            "active_tab_count": 1,
            "catalog": nodes,
        },
        {
            "frame_url": CARD_URL,
            "active_tab_count": 0,
            "modules": [
                {"module_url": "/ananas/modules/unsupported/", "has_job_icon": False, "finished": False}
            ],
        },
    )


def test_completed_catalog_prevents_dispatching_even_unsupported_module(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.DEBUG):
        assert (
            ChaoxingTaskDetector(FakeBrowser(frame_evaluation_results=_frames([_node()]))).detect()
            is TaskType.CONTENT
        )
    assert "source=catalog_check" in caplog.text
    assert CARD_URL not in caplog.text


@pytest.mark.parametrize(
    "nodes", [[], [_node(completed_count=0)], [_node(completed_count=0, pending_count=1)]]
)
def test_no_explicit_check_keeps_unsupported_module_fail_closed(nodes: list[object]) -> None:
    assert (
        ChaoxingTaskDetector(FakeBrowser(frame_evaluation_results=_frames(nodes))).detect()
        is TaskType.UNKNOWN
    )


@pytest.mark.parametrize(
    "nodes",
    [
        [_node(pending_count=1)],
        [_node(completed_count=True)],
        [_node(active=False)],
        [_node(node_id="cur200")],
        [_node(), _node()],
        [_node(), _node(node_id="cur200")],
        [_node(completed_count=2)],
        [None],
    ],
)
def test_inconsistent_catalog_returns_unknown_with_safe_diagnostics(
    nodes: list[object],
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.DEBUG):
        assert (
            ChaoxingTaskDetector(FakeBrowser(frame_evaluation_results=_frames(nodes))).detect()
            is TaskType.UNKNOWN
        )
    assert "stage=catalog_completion" in caplog.text
    assert "reason=malformed_state" in caplog.text
    assert "cur200" not in caplog.text


def test_multiple_catalog_frames_are_ambiguous() -> None:
    frames = _frames([_node()])
    with pytest.raises(ValueError, match="Ambiguous"):
        knowledge_is_completed((*frames, frames[0]), CARD_URL)
