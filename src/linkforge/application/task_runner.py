"""Course-task detection and dispatch lifecycle."""

import logging
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from enum import Enum

logger = logging.getLogger(__name__)


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
        unknown_retry_attempts: int = 3,
        unknown_retry_interval_seconds: float = 0.5,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if unknown_retry_attempts < 0:
            raise ValueError("unknown_retry_attempts must not be negative")
        if unknown_retry_interval_seconds <= 0:
            raise ValueError("unknown_retry_interval_seconds must be greater than 0")

        self._detector = detector
        self._video_handler = video_handler
        self._document_handler = document_handler
        self._content_handler = content_handler
        self._comment_handler = comment_handler
        self._quiz_handler = quiz_handler
        self._unknown_retry_attempts = unknown_retry_attempts
        self._unknown_retry_interval_seconds = unknown_retry_interval_seconds
        self._sleep = sleep

    def run(self, *, should_stop: Callable[[], bool] | None = None) -> None:
        """Dispatch tasks until completion or a stop request at a task boundary."""
        while True:
            if should_stop is not None and should_stop():
                logger.info("Task runner stopped at task boundary")
                return
            task_type = self._detect_with_bounded_unknown_retry()
            logger.info("Detected task type: %s", task_type.name)

            if task_type is TaskType.COMPLETE:
                logger.info("Task runner reached COMPLETE")
                return

            if task_type is TaskType.UNKNOWN:
                logger.error("Task detection remained UNKNOWN after bounded retries")
                raise UnknownTaskError("Unable to determine the current course task.")

            handler: TaskHandler
            if task_type is TaskType.VIDEO:
                handler = self._video_handler
            elif task_type is TaskType.DOCUMENT:
                handler = self._document_handler
            elif task_type is TaskType.CONTENT:
                handler = self._content_handler
            elif task_type is TaskType.COMMENT:
                handler = self._comment_handler
            else:
                handler = self._quiz_handler

            logger.info("Dispatching task to %s handler", task_type.name)
            try:
                handler.run()
            except BaseException:
                logger.error("%s handler failure propagated to task runner", task_type.name)
                raise

    def _detect_with_bounded_unknown_retry(self) -> TaskType:
        for retry_index in range(self._unknown_retry_attempts + 1):
            task_type = self._detector.detect()
            logger.debug(
                "Task detection attempt %d/%d returned %s",
                retry_index + 1,
                self._unknown_retry_attempts + 1,
                task_type.name,
            )
            if task_type is not TaskType.UNKNOWN:
                return task_type
            if retry_index < self._unknown_retry_attempts:
                logger.warning(
                    "Task type UNKNOWN; retrying after %.3f seconds",
                    self._unknown_retry_interval_seconds,
                )
                self._sleep(self._unknown_retry_interval_seconds)

        return TaskType.UNKNOWN
