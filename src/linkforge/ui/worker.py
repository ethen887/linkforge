"""Qt worker-thread bridge for the synchronous LinkForge runtime."""

from __future__ import annotations

import logging
from collections.abc import Callable
from threading import Lock

from PySide6.QtCore import QObject, Signal, Slot

from linkforge.application import ApplicationConfig, LinkForgeApplication
from linkforge.ui.error_messages import user_error_message

ApplicationFactory = Callable[[ApplicationConfig], LinkForgeApplication]

logger = logging.getLogger(__name__)

_TASK_NAMES = {
    "VIDEO": "视频",
    "DOCUMENT": "文档",
    "CONTENT": "课程内容",
    "COMMENT": "讨论",
    "QUIZ": "测验",
    "UNKNOWN": "未知任务",
    "COMPLETE": "已完成",
}
_HANDLER_NAMES = {
    "video_handler": "视频任务",
    "document_handler": "文档任务",
    "content_handler": "课程内容",
    "comment_handler": "讨论任务",
    "quiz_handler": "测验任务",
}


class RuntimeWorker(QObject):
    """Create and execute one application on a background Qt thread."""

    running = Signal()
    completed = Signal()
    failed = Signal(str, str)
    finished = Signal()

    def __init__(self, config: ApplicationConfig, application_factory: ApplicationFactory) -> None:
        super().__init__()
        self._config = config
        self._application_factory = application_factory
        self._application: LinkForgeApplication | None = None
        self._stop_requested = False
        self._lock = Lock()

    @Slot()
    def run(self) -> None:
        """Build and synchronously run the application on the owning worker thread."""
        try:
            application = self._application_factory(self._config)
            with self._lock:
                self._application = application
                stop_requested = self._stop_requested
            if stop_requested:
                application.stop()
            self.running.emit()
            application.run()
        except BaseException as exc:
            error_type = type(exc).__name__
            user_error = user_error_message(exc)
            summary = _safe_error_summary(user_error.summary, self._config.model_config.api_key)
            logger.error("GUI worker stopped with %s", error_type)
            self.failed.emit(user_error.category, summary)
        else:
            self.completed.emit()
        finally:
            with self._lock:
                self._application = None
            self.finished.emit()

    def request_stop(self) -> None:
        """Request the application's existing task-boundary stop behavior."""
        with self._lock:
            self._stop_requested = True
            application = self._application
        if application is not None:
            application.stop()


class _LogEmitter(QObject):
    message = Signal(str)


class GuiLogHandler(logging.Handler):
    """Forward a safe, user-oriented subset of runtime records through Qt."""

    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.emitter = _LogEmitter()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = _user_message(record)
            if message is not None:
                self.emitter.message.emit(message)
        except Exception:
            self.handleError(record)


def _safe_error_summary(summary: str, api_key: str) -> str:
    if api_key:
        summary = summary.replace(api_key, "[已隐藏]")
    sensitive_markers = (
        "authorization",
        "cookie",
        "password",
        "access_token",
        "refresh_token",
        "session_token",
        "token=",
        "ticket=",
        "auth=",
        "session=",
    )
    if any(marker in summary.lower() for marker in sensitive_markers):
        return "错误详情可能包含敏感认证信息，已隐藏。"
    return summary


def _user_message(record: logging.LogRecord) -> str | None:
    message = record.getMessage()
    if record.name == "linkforge.platforms.chaoxing.startup":
        return {
            "Chaoxing manual login required": "等待登录：请在浏览器中完成学习通登录，进入课程后将自动继续",
            "Waiting for Chaoxing course page": "正在等待课程页面加载",
            "Returning to requested Chaoxing course after login": "登录页面已退出，正在返回课程页面",
            "Chaoxing course page ready": "课程页面已就绪，开始课程任务",
            "Chaoxing startup wait stopped": "已停止登录等待",
            "Chaoxing startup readiness timed out": "登录或课程页面加载超时，请检查浏览器页面后重试",
        }.get(message)
    if record.name == "linkforge.application.runtime":
        return {
            "Application run started": "开始执行课程任务",
            "Browser started": "浏览器已打开",
            "Course page opened": "课程页面已打开",
            "Platform runtime completed": "课程工作流已结束",
            "Application cleanup finished": "浏览器资源已清理",
            "Application stop requested": "已请求安全停止",
        }.get(message)

    if record.name == "linkforge.application.task_runner":
        prefix = "Detected task type: "
        if message.startswith(prefix):
            task_type = message.removeprefix(prefix)
            return f"当前任务：{_TASK_NAMES.get(task_type, task_type)}"
        if message == "Task runner stopped at task boundary":
            return "已在安全任务边界停止"
        if message == "Task runner reached COMPLETE":
            return "课程任务已完成"

    for module_suffix, display_name in _HANDLER_NAMES.items():
        if record.name.endswith(module_suffix):
            if message.endswith("handler started"):
                return f"{display_name}开始"
            if message.endswith("handler completed"):
                return f"{display_name}完成"
            if message.endswith("handler failed"):
                return f"{display_name}发生错误"
    return None
