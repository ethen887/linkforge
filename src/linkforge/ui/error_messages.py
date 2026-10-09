"""Translate internal failures into safe, actionable Chinese UI messages."""

from __future__ import annotations

from dataclasses import dataclass

from linkforge.action.exceptions import ActionExecutionError
from linkforge.agent.exceptions import AgentDecisionError, MaxStepsExceededError
from linkforge.application.task_runner import UnknownTaskError
from linkforge.browser.exceptions import (
    BrowserClosedError,
    BrowserElementError,
    BrowserNavigationError,
    BrowserStartError,
    BrowserTimeoutError,
)
from linkforge.llm.errors import ModelRequestError
from linkforge.platforms.chaoxing.exceptions import (
    ChaoxingCommentGenerationError,
    ChaoxingCommentRecoveryError,
    ChaoxingCommentStateError,
    ChaoxingDocumentInspectionError,
    ChaoxingDocumentNotFoundError,
    ChaoxingDocumentProgressTimeoutError,
    ChaoxingDocumentStateError,
    ChaoxingDocumentTimeoutError,
    ChaoxingDocumentViewerReadyTimeoutError,
    ChaoxingInspectionError,
    ChaoxingQuizAnswerError,
    ChaoxingQuizCaptureError,
    ChaoxingQuizCompletionError,
    ChaoxingQuizSolverError,
    ChaoxingQuizStateError,
    ChaoxingQuizSubmissionError,
    ContentNavigationError,
    VideoPlaybackError,
    VideoTaskError,
    VideoTimeoutError,
)
from linkforge.platforms.chaoxing.startup import ChaoxingStartupTimeoutError


@dataclass(frozen=True, slots=True)
class UserErrorMessage:
    category: str
    summary: str


def _causes(exc: BaseException) -> tuple[BaseException, ...]:
    result: list[BaseException] = []
    current: BaseException | None = exc
    while current is not None and current not in result and len(result) < 12:
        result.append(current)
        current = current.__cause__ or current.__context__
    return tuple(result)


def _first(causes: tuple[BaseException, ...], kind: type[BaseException]) -> BaseException | None:
    return next((item for item in causes if isinstance(item, kind)), None)


def user_error_message(exc: BaseException) -> UserErrorMessage:
    """Return a Chinese explanation without exposing provider response bodies."""
    causes = _causes(exc)

    model_error = _first(causes, ModelRequestError)
    if isinstance(model_error, ModelRequestError):
        return UserErrorMessage("模型调用失败", model_error.reason)
    if isinstance(exc, ChaoxingQuizSolverError):
        summary = str(exc).strip()
        if summary.startswith("第 ") and "模型" in summary:
            return UserErrorMessage("模型调用失败", summary)
        return UserErrorMessage("模型调用失败", "模型未能生成测验答案，请检查模型配置后重试。")
    if isinstance(exc, ChaoxingCommentGenerationError):
        return UserErrorMessage("模型调用失败", "模型未能生成讨论内容，请检查模型配置后重试。")

    if isinstance(exc, UnknownTaskError):
        return UserErrorMessage(
            "暂不支持的课程模块",
            "当前页面包含 LinkForge 暂不支持的任务，或页面尚未加载完成。"
            "请确认页面加载正常；若该模块尚未支持，请手动完成或跳过后重试。",
        )
    if isinstance(exc, ChaoxingStartupTimeoutError):
        return UserErrorMessage(
            "课程页面加载超时",
            "未能进入可识别的学习通课程页面。请检查登录状态、课程地址和网络后重试。",
        )

    if isinstance(exc, BrowserStartError):
        return UserErrorMessage("浏览器启动失败", "浏览器未能启动，请关闭残留浏览器进程后重试。")
    if isinstance(exc, BrowserNavigationError):
        return UserErrorMessage("页面打开失败", "课程页面无法打开，请检查网络、课程地址和登录状态。")
    if isinstance(exc, BrowserClosedError):
        return UserErrorMessage("浏览器已关闭", "运行中的浏览器或课程标签页已被关闭，请重新开始。")
    if isinstance(exc, BrowserTimeoutError):
        return UserErrorMessage("页面响应超时", "页面在限定时间内没有响应，请检查网络和当前页面后重试。")
    if isinstance(exc, BrowserElementError):
        return UserErrorMessage("页面内容发生变化", "未能定位或操作当前页面元素，请刷新课程页面后重试。")

    if isinstance(exc, ContentNavigationError):
        return UserErrorMessage(
            "课程页面切换失败",
            "页面没有成功切换到下一项内容。请检查是否有弹窗、遮挡或尚未完成的任务后重试。",
        )
    if isinstance(exc, ChaoxingQuizCaptureError):
        return UserErrorMessage("测验题目读取失败", "题目或图片尚未完整加载，请等待页面加载完成后重试。")
    if isinstance(exc, ChaoxingQuizAnswerError):
        return UserErrorMessage("测验答案无效", "模型返回的题型或选项无法用于当前题目，请重试或更换模型。")
    if isinstance(exc, ChaoxingQuizSubmissionError):
        return UserErrorMessage("测验提交失败", "未能可靠完成测验提交，请检查页面并手动确认当前提交状态。")
    if isinstance(exc, ChaoxingQuizCompletionError):
        return UserErrorMessage("测验完成状态未知", "测验已尝试提交，但平台未确认完成，请检查页面状态。")
    if isinstance(exc, ChaoxingQuizStateError):
        return UserErrorMessage(
            "测验页面尚未就绪",
            "没有找到稳定的题目页面，或答题过程中页面发生变化。请等待加载完成后重试。",
        )

    if isinstance(exc, ChaoxingDocumentViewerReadyTimeoutError):
        return UserErrorMessage("文档加载超时", "文档阅读器未能完成加载，请检查网络后重试。")
    if isinstance(exc, ChaoxingDocumentProgressTimeoutError):
        return UserErrorMessage("文档阅读无进展", "文档页面无法继续滚动，请检查页面是否被弹窗或遮挡。")
    if isinstance(exc, ChaoxingDocumentTimeoutError):
        return UserErrorMessage("文档处理超时", "文档任务耗时过长，请检查阅读器状态后重试。")
    if isinstance(exc, ChaoxingDocumentNotFoundError):
        return UserErrorMessage("未找到文档任务", "当前页面中的文档任务已经消失或发生切换，请重新检测。")
    if isinstance(exc, (ChaoxingDocumentInspectionError, ChaoxingDocumentStateError)):
        return UserErrorMessage("文档页面无法识别", "文档阅读器状态异常，请刷新课程页面后重试。")

    if isinstance(exc, VideoPlaybackError):
        return UserErrorMessage("视频无法播放", "平台拒绝播放或播放器尚未就绪，请检查页面后重试。")
    if isinstance(exc, VideoTimeoutError):
        return UserErrorMessage("视频处理超时", "视频未在限定时间内开始或完成，请检查网络和播放器状态。")
    if isinstance(exc, VideoTaskError):
        return UserErrorMessage("视频任务异常", "无法可靠识别当前视频任务，请刷新课程页面后重试。")

    if isinstance(exc, ChaoxingCommentRecoveryError):
        return UserErrorMessage("讨论页面返回失败", "处理讨论后未能返回课程页面，请手动返回课程后重试。")
    if isinstance(exc, ChaoxingCommentStateError):
        return UserErrorMessage("讨论任务无法识别", "当前讨论入口或页面状态不明确，请检查页面后重试。")
    if isinstance(exc, ChaoxingInspectionError):
        return UserErrorMessage("课程页面无法识别", "当前课程页面结构不明确，请刷新页面或重新进入课程。")

    if isinstance(exc, MaxStepsExceededError):
        return UserErrorMessage("操作步骤过多", "自动操作未能在限定步骤内完成，请检查当前页面后重试。")
    if isinstance(exc, AgentDecisionError):
        return UserErrorMessage("模型操作指令无效", "模型未能生成可执行的页面操作，请重试或更换模型。")
    if isinstance(exc, ActionExecutionError):
        return UserErrorMessage("页面操作失败", "浏览器未能执行模型选择的操作，请检查页面状态后重试。")

    return UserErrorMessage(
        "运行异常",
        "LinkForge 遇到了尚未分类的问题。请重试；如果问题持续出现，请查看最新日志。",
    )
