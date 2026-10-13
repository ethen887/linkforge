"""学习通课程卡片的确定性任务检测。"""

import logging
from urllib.parse import urljoin, urlsplit

from linkforge.application.task_runner import TaskDetector, TaskType
from linkforge.browser.base import Browser
from linkforge.browser.exceptions import BrowserError
from linkforge.platforms.chaoxing.catalog import knowledge_is_completed
from linkforge.platforms.chaoxing.comment_state import (
    COMMENT_MODULE_PATH,
    CommentIdentityError,
    CommentSession,
    comment_identity,
)
from linkforge.platforms.chaoxing.document_inspection import (
    document_viewer_is_ready,
    inspect_innerbook_viewers,
    parse_document_inspection,
    parse_module_basics,
)
from linkforge.platforms.chaoxing.dom import CHAOXING_CARD_STATE_SCRIPT, inspect_chaoxing_page
from linkforge.platforms.chaoxing.exceptions import ChaoxingInspectionError
from linkforge.platforms.chaoxing.innerbook import InnerbookSession, find_innerbook_viewer, is_innerbook
from linkforge.platforms.chaoxing.models import ChaoxingDocumentModuleState
from linkforge.platforms.chaoxing.video_state import VideoSession

_PDF_MODULE_PATH = "/ananas/modules/pdf/"

logger = logging.getLogger(__name__)

_MODULE_TASK_TYPES = {
    "/ananas/modules/video/": TaskType.VIDEO,
    _PDF_MODULE_PATH: TaskType.DOCUMENT,
    "/ananas/modules/work/": TaskType.QUIZ,
    "/ananas/modules/insertbbs/": TaskType.COMMENT,
}

# 仅用于诊断的词语表；命中某个词语并不代表该模块受支持。
_DIAGNOSTIC_MODULE_KINDS = frozenset(
    {"video", "pdf", "work", "insertbbs", "audio", "ppt", "read", "flash", "img", "book", "innerbook"}
)


def _diagnostic_module_kind(module_url: str) -> str:
    """返回在白名单内的路由标签，且不记录任意的 URL 数据。"""
    path = urlsplit(module_url).path
    _, separator, suffix = path.partition("/ananas/modules/")
    if not separator:
        return "unrecognized_route"
    kind = suffix.partition("/")[0]
    return kind if kind in _DIAGNOSTIC_MODULE_KINDS else "unrecognized_kind"


class ChaoxingTaskDetector(TaskDetector):
    """检测当前学习通内容 frame 中首个待处理模块。"""

    def __init__(
        self,
        browser: Browser,
        *,
        comment_session: CommentSession | None = None,
        video_session: VideoSession | None = None,
        innerbook_session: InnerbookSession | None = None,
    ) -> None:
        """保存浏览器引用与各会话对象，用于判断模块是否已被处理。"""
        self._browser = browser
        self._comment_session = comment_session
        self._video_session = video_session
        self._innerbook_session = innerbook_session or InnerbookSession()

    def detect(self) -> TaskType:
        """根据当前学习通卡片返回确定性的任务类型。"""
        stage = "frame_evaluation"
        module_index: int | None = None
        try:
            frame_results = self._browser.evaluate_in_frames(CHAOXING_CARD_STATE_SCRIPT)

            stage = "card_parsing"
            inspection = parse_document_inspection(frame_results)

            if inspection is None:
                return self._unknown("course_state_unavailable", stage=stage)

            stage = "catalog_completion"
            if knowledge_is_completed(frame_results, inspection.content_frame_url):
                logger.debug("Chaoxing completed knowledge: source=catalog_check; advancing to next node")
                return TaskType.CONTENT

            book_inspected = False
            for module_index, raw_module in enumerate(inspection.modules):
                stage = "module_parsing"
                module_url, has_job_icon, finished = parse_module_basics(raw_module)

                # PDF/文档在此使用 LinkForge 的真实阅读器状态，
                # 而不只依赖学习通的任务点标记。
                if _PDF_MODULE_PATH in module_url:
                    stage = "document_parsing"
                    document = ChaoxingDocumentModuleState.from_raw(
                        raw_module,
                        module_index=module_index,
                    )

                    # 带有学习通任务点且被明确标记为已完成的 PDF
                    # 无需再次处理。
                    if document.has_job_icon and document.finished:
                        continue

                    viewer = inspection.viewers.get(document.object_id)

                    # 已完整加载且已到达底部的真实阅读器，
                    # 视为已被 LinkForge 处理。
                    if (
                        viewer is not None
                        and document_viewer_is_ready(document, viewer)
                        and viewer.at_bottom
                    ):
                        continue

                    # 缺失或未就绪的阅读器有意保持为 DOCUMENT，
                    # 由处理器负责限时的阅读器就绪等待。
                    return TaskType.DOCUMENT

                # 非文档类任务点继续使用学习通的完成标记。
                if has_job_icon and finished:
                    continue

                if is_innerbook(module_url):
                    stage = "innerbook_inspection"
                    if not book_inspected:
                        inspection = inspect_innerbook_viewers(self._browser, inspection)
                        book_inspected = True
                    book_viewer = find_innerbook_viewer(raw_module, inspection.innerbook_viewers)
                    if not has_job_icon and self._innerbook_session.is_handled(
                        inspection.content_frame_url, module_index, module_url, book_viewer
                    ):
                        continue
                    # 已知的书籍视为文档；其就绪与完成检查由处理器负责。
                    return TaskType.DOCUMENT

                if "/ananas/modules/video/" in module_url and self._video_session is not None:
                    stage = "video_session_inspection"
                    state = inspect_chaoxing_page(self._browser)
                    if module_index >= len(state.modules):
                        return self._unknown("module_missing_between_observations", stage, module_index)
                    # 两次 frame 观察之间卡片可能发生变化。
                    if state.modules[module_index].url != urljoin(state.content_frame_url, module_url):
                        return self._unknown("module_changed_between_observations", stage, module_index)
                    if self._video_session.is_handled(state, module_index):
                        continue

                if COMMENT_MODULE_PATH in module_url and self._comment_session is not None:
                    stage = "comment_session_inspection"
                    state = inspect_chaoxing_page(self._browser)
                    if module_index >= len(state.modules) or state.modules[module_index].url != module_url:
                        return self._unknown("module_changed_between_observations", stage, module_index)
                    stage = "comment_identity"
                    identity = comment_identity(self._browser.current_url(), state, module_index)
                    if self._comment_session.is_handled(identity):
                        continue

                task_type = self._classify_module(module_url)
                if task_type is TaskType.UNKNOWN:
                    logger.debug(
                        "Chaoxing unsupported module: module_kind=%s module_index=%d "
                        "module_count=%d has_job_icon=%s finished=%s",
                        _diagnostic_module_kind(module_url),
                        module_index,
                        len(inspection.modules),
                        has_job_icon,
                        finished,
                    )
                    return self._unknown("unsupported_module_type", "module_classification", module_index)
                return task_type

        except BrowserError:
            return self._unknown("dom_inspection_failed", stage, module_index)
        except ChaoxingInspectionError:
            return self._unknown("page_state_inspection_failed", stage, module_index)
        except CommentIdentityError:
            return self._unknown("comment_identity_unavailable", stage, module_index)
        except ValueError:
            return self._unknown("malformed_state", stage, module_index)

        # 当前卡片中没有剩余的待处理模块。
        return TaskType.CONTENT

    @staticmethod
    def _unknown(reason: str, stage: str, module_index: int | None = None) -> TaskType:
        """仅记录受控标签与计数，绝不会记录原始 DOM 或异常文本。"""
        logger.debug(
            "Chaoxing UNKNOWN: reason=%s stage=%s module_index=%s",
            reason,
            stage,
            module_index,
        )
        return TaskType.UNKNOWN

    @staticmethod
    def _classify_module(module_url: str) -> TaskType:
        """将学习通模块 URL 映射到与提供方无关的任务类型。"""
        for module_path, task_type in _MODULE_TASK_TYPES.items():
            if module_path in module_url:
                return task_type

        return TaskType.UNKNOWN
