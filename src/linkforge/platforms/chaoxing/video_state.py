"""无平台任务点的普通视频在单次运行内的完成度记忆。"""

from linkforge.platforms.chaoxing.models import ChaoxingPageState


class VideoSession:
    """记住在其原始卡片内真正播放结束的普通视频。"""

    def __init__(self) -> None:
        self._handled: set[tuple[str, int, int, str]] = set()

    @staticmethod
    def _identity(state: ChaoxingPageState, module_index: int) -> tuple[str, int, int, str]:
        return (
            state.content_frame_url,
            state.active_tab_index,
            module_index,
            state.modules[module_index].url,
        )

    def is_handled(self, state: ChaoxingPageState, module_index: int) -> bool:
        """带任务点的视频始终需要新的平台完成证据。"""
        return (
            not state.modules[module_index].has_job_icon
            and self._identity(state, module_index) in self._handled
        )

    def mark_handled(self, state: ChaoxingPageState, module_index: int) -> None:
        """在处理器观察到真实媒体播放结束后记录其已完成。"""
        self._handled.add(self._identity(state, module_index))
