"""课程任务检测与分派生命周期。"""

import logging
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from enum import Enum
from typing import Protocol

from linkforge.application.issues import RunIssue

logger = logging.getLogger(__name__)


class TaskType(Enum):
    """应用运行时能够识别的课程任务类型。"""

    VIDEO = "video"
    DOCUMENT = "document"
    CONTENT = "content"
    COMMENT = "comment"
    QUIZ = "quiz"
    UNKNOWN = "unknown"
    COMPLETE = "complete"


class TaskDetector(ABC):
    """从应用可见的状态中检测当前课程任务。"""

    @abstractmethod
    def detect(self) -> TaskType:
        """返回当前呈现给应用的任务。"""
        raise NotImplementedError


class TaskHandler(ABC):
    """完成一个特定类型的任务，并将控制权交还给运行器。"""

    @abstractmethod
    def run(self) -> None:
        """运行当前任务直至其完成。"""
        raise NotImplementedError

    def run_interruptibly(self, *, should_stop: Callable[[], bool] | None = None) -> None:
        """运行任务；支持中途停止的处理器可覆盖此方法。"""
        self.run()


class UnknownTaskError(RuntimeError):
    """当当前课程任务无法被识别时抛出。"""


class TaskRecovery(Protocol):
    """由平台验证问题位置并推进到后续内容。"""

    issues: list[RunIssue]

    def checkpoint(self) -> None: ...

    def recover(
        self, task_type: TaskType, error: Exception, should_stop: Callable[[], bool] | None
    ) -> bool: ...


class TaskRunner:
    """负责完整课程任务生命周期中的检测与分派。"""

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
        recovery: TaskRecovery | None = None,
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
        self._recovery = recovery
        self.issues: list[RunIssue] = recovery.issues if recovery is not None else []

    def run(self, *, should_stop: Callable[[], bool] | None = None) -> None:
        """分派任务直至完成或收到停止请求，并向处理器传递停止回调。"""
        while True:
            if should_stop is not None and should_stop():
                logger.info("Task runner stopped at task boundary")
                return
            if self._recovery is not None:
                self._recovery.checkpoint()
            task_type = self._detect_with_bounded_unknown_retry()
            logger.info("Detected task type: %s", task_type.name)

            if task_type is TaskType.COMPLETE:
                logger.info("Task runner reached COMPLETE")
                return

            if task_type is TaskType.UNKNOWN:
                logger.error("Task detection remained UNKNOWN after bounded retries")
                error = UnknownTaskError("Unable to determine the current course task.")
                if self._recover(task_type, error, should_stop):
                    continue
                raise error

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
                handler.run_interruptibly(should_stop=should_stop)
            except Exception as exc:
                if self._recover(task_type, exc, should_stop):
                    continue
                logger.error("%s handler failure propagated to task runner", task_type.name)
                raise

    def _recover(
        self, task_type: TaskType, error: Exception, should_stop: Callable[[], bool] | None
    ) -> bool:
        if self._recovery is None:
            return False
        return self._recovery.recover(task_type, error, should_stop)

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
