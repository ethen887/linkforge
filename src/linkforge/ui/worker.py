"""为同步运行的 LinkForge 运行时提供的 Qt 工作线程桥接。"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import replace
from threading import Lock

from PySide6.QtCore import QObject, Signal, Slot

from linkforge.application import ApplicationConfig, LinkForgeApplication
from linkforge.application.issues import RunIssue
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
    """在后台 Qt 线程上创建并执行一个应用实例。"""

    running = Signal()
    completed = Signal()
    review_ready = Signal(bool)
    review_finished = Signal()
    failed = Signal(str, str)
    finished = Signal()
    course_url_changed = Signal(str)
    issues_ready = Signal(object)

    def __init__(self, config: ApplicationConfig, application_factory: ApplicationFactory) -> None:
        super().__init__()
        self._config = config
        self._application_factory = application_factory
        self._application: LinkForgeApplication | None = None
        self._stop_requested = False
        self._lock = Lock()

    @Slot()
    def run(self) -> None:
        """在所属的工作线程上构建并同步运行应用。"""
        application: LinkForgeApplication | None = None
        try:
            config = replace(
                self._config,
                on_course_url_changed=self.course_url_changed.emit,
                on_review_required=self.review_ready.emit,
            )
            application = self._application_factory(config)
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
            if getattr(application, "review_required", False):
                self.review_finished.emit()
            else:
                self.completed.emit()
        finally:
            issues: tuple[RunIssue, ...] = tuple(getattr(application, "issues", ()))
            if issues:
                logger.warning("本次运行有 %d 项问题待检查", len(issues))
                for issue in issues:
                    logger.warning("待检查：%s", issue.describe())
                self.issues_ready.emit(issues)
            with self._lock:
                self._application = None
            self.finished.emit()

    def request_stop(self) -> None:
        """请求应用停止；模型等待和视频轮询期间均可响应。"""
        with self._lock:
            self._stop_requested = True
            application = self._application
        if application is not None:
            application.stop()


class _LogEmitter(QObject):
    message = Signal(str)


class GuiLogHandler(logging.Handler):
    """通过 Qt 转发安全且面向用户的一部分运行时日志记录。"""

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
    if record.name == "linkforge.platforms.chaoxing.written_formula" and record.msg in {
        "TEX 公式：%s",
        "TEX 公式：预览未就绪，确认前重新输入一次",
        "TEX 公式：已确认预览，开始上传并等待插入（不重复确认）",
    }:
        return message
    if record.name == "linkforge.platforms.chaoxing.written_answer" and record.msg in {
        "大题答案校验失败：%s",
        "大题答案格式修复失败：%s",
        "大题答案格式不符合要求，正在尝试一次格式修复",
        "大题答案格式修复成功，继续填写",
        "公式转义已规范化：已去除命令前多余的反斜杠",
        "公式格式已规范化：已处理外层分隔符或多余转义",
        "正文中的成对公式已拆分，将通过 TEX 渲染",
    }:
        return message
    if record.name == "linkforge.platforms.chaoxing.written_assignment" and record.msg in {
        "第 %d 题：正在判断已有答案是否需要重做",
        "第 %d 题：AI 判断可保留已有答案，已跳过重做",
        "第 %d 题：AI 判断需要重做，生成完整答案后覆盖",
        "第 %d 题：已有公式图片加载失败，公式数据完整，将生成完整草稿后重做",
        "第 %d 题：等待编辑器初始化、已有答案恢复或公式加载",
        "第 %d 题：编辑器已就绪，继续生成草稿",
        "第 %d 题：等待编辑器就绪超时，原因：%s",
        "第 %d 题：正在生成大题草稿",
        "第 %d 题：大题草稿已填写并确认暂存",
        "作业草稿未全部确认暂存，已暂停等待人工检查（%s）",
        "作业草稿暂停原因：%s",
        "整份作业共 %d 题：逐题作答并暂存，全部处理后等待检查",
        "整份作业 %d 题已处理并确认暂存，等待人工检查和提交",
        "第 %d 题：正在录入第 %d/%d 段",
        "第 %d 题：第 %d/%d 段已核验",
        "第 %d 题：%s失败（%s）",
        "第 %d 题：已回读确认交互生效，继续后续核验",
        "第 %d 题：已确认交互未生效，重新定位后重试一次",
        "作业核验失败：题目数量、题型或题干发生变化",
        "第 %d 题：暂存后正文或公式与录入结果不一致",
        "第 %d 题：编辑器内容未同步到暂存表单",
        "第 %d 题：正在进行第 %d 轮作答审核",
        "第 %d 题：第 %d 轮作答审核通过",
        "第 %d 题：第 %d 轮审核问题：%s",
        "第 %d 题：正在根据审核记录进行第 %d 次重做",
        "作业大题自动审核全部通过，草稿等待人工检查",
        "作答审核仍未通过，已达到两轮自动重做上限，保留草稿等待人工检查",
    }:
        return message
    if record.name == "linkforge.platforms.chaoxing.quiz_draft":
        return message if message == "暂存按钮不唯一或暂不可用，已跳过本次暂存点击" else None
    if record.name == "linkforge.platforms.chaoxing.quiz_handler" and record.msg in {
        "第 %d 题：已点击暂时保存，正在重新核验选项",
        "第 %d 题：检测到已有答案，保留选项并跳过模型请求",
    }:
        return message
    if record.name == "linkforge.llm.request_runtime":
        # 该模块只输出本地标识、固定文案及数值统计。
        return message if message.startswith("模型请求 ") else None
    if record.name == "linkforge.platforms.chaoxing.quiz_solver":
        if record.msg == "Quiz model request: question=%d attempt=%d" and isinstance(record.args, tuple):
            question, attempt = record.args
            if type(question) is int and type(attempt) is int:
                return f"正在请求第 {question} 题答案（第 {attempt} 次尝试）"
        return None
    if record.name == "linkforge.platforms.chaoxing.recovery":
        return message if message.startswith("课程问题：") else None
    if record.name == "linkforge.platforms.chaoxing.navigation":
        if message == "Following the selected Chaoxing course page":
            return "检测到课程页面切换，正在跟随当前选择的内容"
        return None
    if record.name == "linkforge.platforms.chaoxing.assignment_handler":
        return {
            "作业暂存响应已确认": "作业暂存响应已确认",
            "已点击作业暂存，但未收到保存确认，请检查页面上的保存状态": (
                "已点击作业暂存，但未收到保存确认，请检查页面上的保存状态"
            ),
            "Standalone assignment answers verified; submitting through normal UI": (
                "独立作业选项已核验，正在提交"
            ),
            "Standalone assignment submission confirmed": "当前独立作业提交已确认",
        }.get(message)
    if record.name == "linkforge.platforms.chaoxing.startup":
        return {
            "Chaoxing manual login required": "等待登录：请在浏览器中完成学习通登录，进入课程后将自动继续",
            "Waiting for Chaoxing course page": "正在等待课程页面加载",
            "Returning to requested Chaoxing course after login": "登录页面已退出，正在返回课程页面",
            "Chaoxing course page ready": "课程页面已就绪，开始课程任务",
            "Chaoxing standalone assignment page ready": "独立作业页面已就绪，开始检查作业状态",
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
            "Application model request cancelled": "模型请求已取消",
        }.get(message)

    if record.name == "linkforge.application.task_runner":
        prefix = "Detected task type: "
        if message.startswith(prefix):
            task_type = message.removeprefix(prefix)
            return f"当前任务：{_TASK_NAMES.get(task_type, task_type)}"
        if message == "Task runner stopped at task boundary":
            return "已在安全任务边界停止"
        if message == "Task runner reached COMPLETE":
            return "当前任务流程已完成"

    for module_suffix, display_name in _HANDLER_NAMES.items():
        if record.name.endswith(module_suffix):
            if message == "Video stall recovery requested":
                return "视频播放暂时停滞，已尝试暂停后继续播放"
            if message == "Video handler stopped":
                return "视频任务已停止，未完成的视频保留待续播"
            if message == "Quiz handler stopped":
                return "测验处理已停止，未继续作答或提交"
            if message.endswith("handler started"):
                return f"{display_name}开始"
            if message.endswith("handler completed"):
                return f"{display_name}完成"
            if message.endswith("handler failed"):
                return f"{display_name}发生错误"
    return None
