"""处理确定性学习通课程任务时抛出的各类失败。"""


class ChaoxingTaskError(RuntimeError):
    """学习通任务处理失败的基础异常类。"""


class ChaoxingQuizError(ChaoxingTaskError):
    """基于截图的测验工作流的基础异常。"""


class ChaoxingQuizStateError(ChaoxingQuizError):
    """测验 frame、题目结构或选择状态不可靠。"""


class ChaoxingWrittenStateError(ChaoxingQuizStateError):
    """大题状态错误；仅使用程序内固定说明，禁止传入页面、模型或 SDK 原始文本。"""


class ChaoxingQuizCaptureError(ChaoxingQuizError):
    """完整的题目无法被截取为图像。"""


class ChaoxingQuizAnswerError(ChaoxingQuizError):
    """题目类型或模型答案不受支持、不一致或无效。"""


class ChaoxingQuizSolverError(ChaoxingQuizError):
    """视觉模型请求失败。"""


class ChaoxingQuizSubmissionError(ChaoxingQuizError):
    """正常的 UI 提交失败或提交生命周期未得到验证。"""


class ChaoxingQuizCompletionError(ChaoxingQuizError):
    """平台完成状态无法被独立验证。"""


class ChaoxingInspectionError(ChaoxingTaskError):
    """当前学习通 DOM 状态无法被无歧义地读取。"""


class VideoTaskError(ChaoxingTaskError):
    """当前学习通视频任务无法被可靠处理。"""


class VideoPlaybackError(VideoTaskError):
    """目标视频无法通过正常的媒体播放启动。"""


class VideoTimeoutError(VideoTaskError):
    """视频生命周期在平台完成前已超时。"""


class ContentNavigationError(ChaoxingTaskError):
    """当前内容无法被可靠地前进并验证。"""


class ChaoxingCommentError(ChaoxingTaskError):
    """受支持的学习通评论工作流的基础异常。"""


class ChaoxingCommentStateError(ChaoxingCommentError):
    """当前讨论的身份或 DOM 契约存在歧义。"""


class ChaoxingCommentRecoveryError(ChaoxingCommentError):
    """原始课程页面无法被可靠恢复。"""


class ChaoxingCommentGenerationError(ChaoxingCommentError):
    """评论正文无法被生成或验证。"""


class ChaoxingDocumentError(ChaoxingTaskError):
    """确定性学习通文档工作流的基础异常。"""


class ChaoxingDocumentInspectionError(ChaoxingDocumentError):
    """当基于浏览器的文档检查失败时抛出。"""


class ChaoxingDocumentStateError(ChaoxingDocumentError):
    """当观察到的文档状态违背 DOM 契约时抛出。"""


class ChaoxingDocumentNotFoundError(ChaoxingDocumentError):
    """当没有待处理文档时抛出。"""


class ChaoxingDocumentViewerReadyTimeoutError(ChaoxingDocumentError):
    """当目标 PDF 阅读器未及时就绪时抛出。"""


class ChaoxingDocumentProgressTimeoutError(ChaoxingDocumentError):
    """当反复的真实滚动动作未产生可观察的进度时抛出。"""


class ChaoxingDocumentTimeoutError(ChaoxingDocumentError):
    """当单个文档工作流超过其整体故障超时时抛出。"""
