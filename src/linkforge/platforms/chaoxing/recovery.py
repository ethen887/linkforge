"""在可验证的课程卡片之间跳过失败内容，保留待补做的问题清单。"""

import json
import logging
from collections.abc import Callable

from linkforge.application.issues import RunIssue
from linkforge.application.task_runner import TaskType, UnknownTaskError
from linkforge.browser.base import Browser
from linkforge.browser.exceptions import BrowserClosedError, BrowserError
from linkforge.platforms.chaoxing.content_handler import ChaoxingContentTaskHandler
from linkforge.platforms.chaoxing.dom import FRAME_PATH_SCRIPT, inspect_chaoxing_page
from linkforge.platforms.chaoxing.exceptions import (
    ChaoxingCommentError,
    ChaoxingCommentRecoveryError,
    ChaoxingDocumentError,
    ChaoxingInspectionError,
    ChaoxingQuizError,
    ChaoxingTaskError,
    ContentNavigationError,
    VideoPlaybackError,
    VideoTaskError,
    VideoTimeoutError,
)
from linkforge.platforms.chaoxing.models import ChaoxingPageState
from linkforge.platforms.chaoxing.navigation import ChaoxingNavigationMonitor
from linkforge.platforms.chaoxing.video_state import VideoSession

logger = logging.getLogger(__name__)

_TASK_NAMES = {
    TaskType.VIDEO: "视频",
    TaskType.DOCUMENT: "文档",
    TaskType.COMMENT: "讨论",
    TaskType.QUIZ: "测验",
    TaskType.CONTENT: "课程内容",
    TaskType.UNKNOWN: "未知模块",
}


class ChaoxingTaskRecovery:
    """只在原课程卡片身份仍一致时尝试向前导航，每个卡片最多一次。"""

    def __init__(
        self,
        browser: Browser,
        navigator: ChaoxingContentTaskHandler,
        *,
        video_session: VideoSession,
        navigation: ChaoxingNavigationMonitor | None = None,
    ) -> None:
        self._browser = browser
        self._navigator = navigator
        self._video_session = video_session
        self._navigation = navigation or ChaoxingNavigationMonitor(browser)
        self._checkpoint: ChaoxingPageState | None = None
        self._attempted: set[tuple[str, int]] = set()
        self._locations: dict[tuple[str, int], int] = {}
        self._deferred_index = -1
        self.issues: list[RunIssue] = []

    def checkpoint(self) -> None:
        self._checkpoint = None
        try:
            self._checkpoint = inspect_chaoxing_page(self._browser)
        except (BrowserError, ChaoxingInspectionError):
            pass

    def recover(
        self, task_type: TaskType, error: Exception, should_stop: Callable[[], bool] | None
    ) -> bool:
        if not isinstance(error, (ChaoxingTaskError, BrowserError, UnknownTaskError)):
            return False
        state = self._checkpoint
        if (
            state is not None
            and not self._fatal(error)
            and not (should_stop is not None and should_stop())
            and self._navigation.follow_if_changed(state, should_stop=should_stop)
        ):
            return True
        location = "位置无法确认"
        key = None
        if state is not None:
            key = (state.content_frame_url, state.active_tab_index)
            number = self._locations.setdefault(key, len(self._locations) + 1)
            location = f"本次第 {number} 个问题页面，第 {state.active_tab_index + 1} 张卡片"

        reason = next(
            (
                description
                for kind, description in (
                    (VideoPlaybackError, "视频无法正常播放"),
                    (VideoTimeoutError, "视频播放或完成确认超时"),
                    (VideoTaskError, "视频任务状态异常"),
                    (UnknownTaskError, "模块暂不支持或页面未就绪"),
                    (ChaoxingDocumentError, "文档加载、阅读或进度确认失败"),
                    (ChaoxingQuizError, "测验读取、答题或提交确认失败"),
                    (ChaoxingCommentError, "讨论处理或返回课程失败"),
                    (ContentNavigationError, "后续内容切换失败"),
                    (ChaoxingInspectionError, "课程页面状态无法确认"),
                    (BrowserError, "浏览器页面操作失败"),
                )
                if isinstance(error, kind)
            ),
            "任务处理失败，需检查页面后补做",
        )
        outcome = "未能继续，请手动检查"
        recovered = False
        if should_stop is not None and should_stop():
            outcome = "用户已停止，保留待补做"
            recovered = True
        elif state is not None and key not in self._attempted and not self._fatal(error):
            assert key is not None
            self._attempted.add(key)
            try:
                if (
                    task_type is TaskType.VIDEO
                    and isinstance(error, VideoTaskError)
                    and self._defer_video(state, should_stop)
                ):
                    location += f"，第 {self._deferred_index + 1} 个模块"
                    self._attempted.remove(key)
                    recovered = True
                    outcome = "已暂缓该视频，继续后续内容，待补做"
                else:
                    advanced = self._navigator.skip_failed_card(state, should_stop=should_stop)
                    recovered = True
                    outcome = "已跳过该卡片剩余内容，待补做" if advanced else "用户已停止，保留待补做"
            except (ChaoxingTaskError, BrowserError):
                pass
        issue = RunIssue(location, _TASK_NAMES.get(task_type, "课程任务"), reason, outcome)
        self.issues.append(issue)
        # 不记录原始异常、URL、DOM 或凭据；界面与文件日志使用相同的受控摘要。
        logger.warning("课程问题：%s", issue.describe())
        return recovered

    def _defer_video(self, expected: ChaoxingPageState, should_stop: Callable[[], bool] | None) -> bool:
        fresh = inspect_chaoxing_page(self._browser)
        if (
            fresh.content_frame_url != expected.content_frame_url
            or fresh.active_tab_index != expected.active_tab_index
            or tuple((m.url, m.frame_path) for m in fresh.modules)
            != tuple((m.url, m.frame_path) for m in expected.modules)
        ):
            return False
        for index, module in enumerate(fresh.modules):
            if "/ananas/modules/video/" not in module.url or (module.has_job_icon and module.finished):
                continue
            if self._video_session.is_handled(fresh, index) or self._video_session.is_deferred(
                fresh, index
            ):
                continue
            if should_stop is not None and should_stop():
                return False
            # 暂停失败视频，防止继续处理同卡片内容时产生后台播放。
            script = f"""() => {{
                {FRAME_PATH_SCRIPT}
                if (location.href !== {json.dumps(module.url)}
                    || ({json.dumps(module.frame_path)} !== null
                        && JSON.stringify(framePath)
                            !== JSON.stringify({json.dumps(module.frame_path)}))) {{
                    return {{matched: false}};
                }}
                for (const video of document.querySelectorAll('video')) video.pause();
                return {{matched: true, paused: true}};
            }}"""
            self._browser.evaluate_in_frames(script)
            self._video_session.defer(fresh, index)
            self._deferred_index = index
            return True
        return False

    @staticmethod
    def _fatal(error: BaseException) -> bool:
        seen: set[int] = set()
        current: BaseException | None = error
        while current is not None and id(current) not in seen:
            seen.add(id(current))
            if isinstance(current, (BrowserClosedError, ChaoxingCommentRecoveryError)):
                return True
            current = current.__cause__ or current.__context__
        return False
