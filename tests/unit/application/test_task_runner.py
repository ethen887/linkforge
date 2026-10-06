"""Unit tests for the application task-runner lifecycle."""

import ast
import inspect
from collections.abc import Callable, Sequence

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


def _no_sleep(_seconds: float) -> None:
    pass


def _runner(
    task_types: Sequence[TaskType],
    *,
    events: list[str] | None = None,
    unknown_retry_attempts: int | None = None,
    unknown_retry_interval_seconds: float = 0.5,
    sleep: Callable[[float], None] = _no_sleep,
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
        **(
            {"unknown_retry_attempts": unknown_retry_attempts} if unknown_retry_attempts is not None else {}
        ),
        unknown_retry_interval_seconds=unknown_retry_interval_seconds,
        sleep=sleep,
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


def test_runner_can_repeat_video_content_video_vertical_slice() -> None:
    events: list[str] = []
    runner, detector, handlers = _runner(
        [TaskType.VIDEO, TaskType.CONTENT, TaskType.VIDEO, TaskType.COMPLETE],
        events=events,
    )

    runner.run()

    assert events == ["detect", "video", "detect", "content", "detect", "video", "detect"]
    assert detector.call_count == 4
    assert handlers[TaskType.VIDEO].call_count == 2
    assert handlers[TaskType.CONTENT].call_count == 1


def test_complete_exits_without_calling_any_handler() -> None:
    runner, detector, handlers = _runner([TaskType.COMPLETE])

    runner.run()

    assert detector.call_count == 1
    assert all(handler.call_count == 0 for handler in handlers.values())


def test_unknown_raises_without_calling_any_handler() -> None:
    runner, detector, handlers = _runner([TaskType.UNKNOWN], unknown_retry_attempts=0)

    with pytest.raises(UnknownTaskError, match="Unable to determine the current course task"):
        runner.run()

    assert detector.call_count == 1
    assert all(handler.call_count == 0 for handler in handlers.values())


def test_transient_unknown_is_retried_with_a_bounded_delay() -> None:
    sleep_calls: list[float] = []
    runner, detector, handlers = _runner(
        [TaskType.UNKNOWN, TaskType.VIDEO, TaskType.COMPLETE],
        unknown_retry_attempts=1,
        unknown_retry_interval_seconds=0.25,
        sleep=sleep_calls.append,
    )

    runner.run()

    assert detector.call_count == 3
    assert handlers[TaskType.VIDEO].call_count == 1
    assert sleep_calls == [0.25]


def test_unknown_retry_exhaustion_raises_without_unbounded_detection() -> None:
    sleep_calls: list[float] = []
    runner, detector, handlers = _runner(
        [TaskType.UNKNOWN, TaskType.UNKNOWN],
        unknown_retry_attempts=1,
        unknown_retry_interval_seconds=0.25,
        sleep=sleep_calls.append,
    )

    with pytest.raises(UnknownTaskError):
        runner.run()

    assert detector.call_count == 2
    assert all(handler.call_count == 0 for handler in handlers.values())
    assert sleep_calls == [0.25]


@pytest.mark.parametrize("unknown_count", [1, 3])
def test_default_retry_recovers_after_video_and_continues_workflow(unknown_count: int) -> None:
    events: list[str] = []
    sleep_calls: list[float] = []
    runner, detector, handlers = _runner(
        [TaskType.VIDEO, *([TaskType.UNKNOWN] * unknown_count), TaskType.DOCUMENT, TaskType.COMPLETE],
        events=events,
        sleep=sleep_calls.append,
    )

    runner.run()

    assert detector.call_count == unknown_count + 3
    assert sleep_calls == [0.5] * unknown_count
    assert events == ["detect", "video", *(["detect"] * (unknown_count + 1)), "document", "detect"]
    assert handlers[TaskType.VIDEO].call_count == 1
    assert handlers[TaskType.DOCUMENT].call_count == 1
    assert handlers[TaskType.CONTENT].call_count == 0


def test_default_retry_exhaustion_after_video_is_fail_closed() -> None:
    sleep_calls: list[float] = []
    runner, detector, handlers = _runner(
        [TaskType.VIDEO, *([TaskType.UNKNOWN] * 4), TaskType.CONTENT],
        sleep=sleep_calls.append,
    )

    with pytest.raises(UnknownTaskError):
        runner.run()

    assert detector.call_count == 5
    assert sleep_calls == [0.5] * 3
    assert handlers[TaskType.VIDEO].call_count == 1
    assert all(handler.call_count == 0 for task, handler in handlers.items() if task is not TaskType.VIDEO)


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
