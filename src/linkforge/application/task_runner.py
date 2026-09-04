"""Course-task detection and dispatch lifecycle."""

from abc import ABC, abstractmethod
from collections.abc import Callable
from enum import Enum


class TaskType(Enum):
    """Course task types understood by the application runtime."""

    VIDEO = "video"
    DOCUMENT = "document"
    CONTENT = "content"
    COMMENT = "comment"
    QUIZ = "quiz"
    UNKNOWN = "unknown"
    COMPLETE = "complete"


class TaskDetector(ABC):
    """Detect the current course task from application-visible state."""

    @abstractmethod
    def detect(self) -> TaskType:
        """Return the task currently presented to the application."""
        raise NotImplementedError


class TaskHandler(ABC):
    """Complete one task of a specific type and return control to the runner."""

    @abstractmethod
    def run(self) -> None:
        """Run the current task until it is complete."""
        raise NotImplementedError


class UnknownTaskError(RuntimeError):
    """Raised when the current course task cannot be identified."""


class TaskRunner:
    """Own detection and dispatch for the complete course-task lifecycle."""

    def __init__(
        self,
        *,
        detector: TaskDetector,
        video_handler: TaskHandler,
        document_handler: TaskHandler,
        content_handler: TaskHandler,
        comment_handler: TaskHandler,
        quiz_handler: TaskHandler,
    ) -> None:
        self._detector = detector
        self._video_handler = video_handler
        self._document_handler = document_handler
        self._content_handler = content_handler
        self._comment_handler = comment_handler
        self._quiz_handler = quiz_handler

    def run(self, *, should_stop: Callable[[], bool] | None = None) -> None:
        """Dispatch tasks until completion or a stop request at a task boundary."""
        while should_stop is None or not should_stop():
            task_type = self._detector.detect()

            if task_type is TaskType.COMPLETE:
                return

            if task_type is TaskType.UNKNOWN:
                raise UnknownTaskError("Unable to determine the current course task.")

            if task_type is TaskType.VIDEO:
                self._video_handler.run()
            elif task_type is TaskType.DOCUMENT:
                self._document_handler.run()
            elif task_type is TaskType.CONTENT:
                self._content_handler.run()
            elif task_type is TaskType.COMMENT:
                self._comment_handler.run()
            elif task_type is TaskType.QUIZ:
                self._quiz_handler.run()
