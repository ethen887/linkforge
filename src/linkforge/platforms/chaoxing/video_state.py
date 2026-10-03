"""Run-scoped completion of ordinary videos without platform task points."""

from linkforge.platforms.chaoxing.models import ChaoxingPageState


class VideoSession:
    """Remember genuinely ended ordinary videos within their original card."""

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
        """Task points always require fresh platform completion evidence."""
        return (
            not state.modules[module_index].has_job_icon
            and self._identity(state, module_index) in self._handled
        )

    def mark_handled(self, state: ChaoxingPageState, module_index: int) -> None:
        """Record completion after the handler has observed real media ending."""
        self._handled.add(self._identity(state, module_index))
