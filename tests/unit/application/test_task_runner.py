"""Unit tests for the application task-runner lifecycle."""

import ast
import inspect
from collections.abc import Sequence

import pytest

import linkforge.application.task_runner as task_runner_module
from linkforge.application.task_runner import (
    TaskDetector,
    TaskHandler,
    TaskRunner,
    TaskType,
    UnknownTaskError,
)


class RecordingTaskDetector(TaskDetector):
    """Return scripted task types while recording each detection."""

    def __init__(self, task_types: Sequence[TaskType], *, events: list[str] | None = None) -> None:
        self._task_types = iter(task_types)
        self.events = events if events is not None else []
        self.call_count = 0

    def detect(self) -> TaskType:
        self.events.append("detect")
        self.call_count += 1
        try:
            return next(self._task_types)
        except StopIteration as exc:
            raise AssertionError("No scripted task detection remains.") from exc


class RecordingTaskHandler(TaskHandler):
    """Record handler calls without performing real course work."""

    def __init__(self, name: str, *, events: list[str] | None = None) -> None:
        self.name = name
        self.events = events if events is not None else []
        self.call_count = 0

    def run(self) -> None:
        self.events.append(self.name)
        self.call_count += 1


def _runner(
    task_types: Sequence[TaskType],
    *,
    events: list[str] | None = None,
) -> tuple[TaskRunner, RecordingTaskDetector, dict[TaskType, RecordingTaskHandler]]:
    detector = RecordingTaskDetector(task_types, events=events)
    handlers = {
        TaskType.VIDEO: RecordingTaskHandler("video", events=events),
        TaskType.DOCUMENT: RecordingTaskHandler("document", events=events),
        TaskType.CONTENT: RecordingTaskHandler("content", events=events),
        TaskType.COMMENT: RecordingTaskHandler("comment", events=events),
        TaskType.QUIZ: RecordingTaskHandler("quiz", events=events),
    }
    runner = TaskRunner(
        detector=detector,
        video_handler=handlers[TaskType.VIDEO],
        document_handler=handlers[TaskType.DOCUMENT],
        content_handler=handlers[TaskType.CONTENT],
        comment_handler=handlers[TaskType.COMMENT],
        quiz_handler=handlers[TaskType.QUIZ],
    )
    return runner, detector, handlers


@pytest.mark.parametrize(
    "selected_task",
    [
        TaskType.VIDEO,
        TaskType.DOCUMENT,
        TaskType.CONTENT,
        TaskType.COMMENT,
        TaskType.QUIZ,
    ],
)
def test_runner_dispatches_only_selected_handler_then_detects_again(
    selected_task: TaskType,
) -> None:
    runner, detector, handlers = _runner([selected_task, TaskType.COMPLETE])

    runner.run()

    assert detector.call_count == 2
    assert handlers[selected_task].call_count == 1
    assert all(
        handler.call_count == (1 if task_type is selected_task else 0)
        for task_type, handler in handlers.items()
    )


def test_runner_owns_complete_multi_task_sequence() -> None:
    events: list[str] = []
    runner, detector, handlers = _runner(
        [
            TaskType.VIDEO,
            TaskType.DOCUMENT,
            TaskType.CONTENT,
            TaskType.COMMENT,
            TaskType.QUIZ,
            TaskType.COMPLETE,
        ],
        events=events,
    )

    runner.run()

    assert events == [
        "detect",
        "video",
        "detect",
        "document",
        "detect",
        "content",
        "detect",
        "comment",
        "detect",
        "quiz",
        "detect",
    ]
    assert detector.call_count == 6
    assert all(handler.call_count == 1 for handler in handlers.values())


def test_complete_exits_without_calling_any_handler() -> None:
    runner, detector, handlers = _runner([TaskType.COMPLETE])

    runner.run()

    assert detector.call_count == 1
    assert all(handler.call_count == 0 for handler in handlers.values())


def test_unknown_raises_without_calling_any_handler() -> None:
    runner, detector, handlers = _runner([TaskType.UNKNOWN])

    with pytest.raises(UnknownTaskError, match="Unable to determine the current course task"):
        runner.run()

    assert detector.call_count == 1
    assert all(handler.call_count == 0 for handler in handlers.values())


def test_stop_request_exits_at_task_boundary_before_detecting_again() -> None:
    runner, detector, handlers = _runner([TaskType.VIDEO])
    stop_checks = iter([False, True])

    runner.run(should_stop=lambda: next(stop_checks))

    assert detector.call_count == 1
    assert handlers[TaskType.VIDEO].call_count == 1
    assert all(
        handler.call_count == (1 if task_type is TaskType.VIDEO else 0)
        for task_type, handler in handlers.items()
    )


def test_application_runtime_has_no_platform_or_playwright_dependency() -> None:
    syntax_tree = ast.parse(inspect.getsource(task_runner_module))
    imported_modules = {
        node.module
        for node in ast.walk(syntax_tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    imported_modules.update(
        alias.name for node in ast.walk(syntax_tree) if isinstance(node, ast.Import) for alias in node.names
    )

    assert not any(
        module == "playwright" or module.startswith("playwright.") for module in imported_modules
    )
    assert not any(module.startswith("linkforge.platforms") for module in imported_modules)
