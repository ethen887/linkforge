"""Typed Chaoxing DOM state shared by deterministic platform adapters."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ChaoxingModuleState:
    """One embedded module in DOM order inside the current content card."""

    url: str
    has_job_icon: bool
    finished: bool


@dataclass(frozen=True, slots=True)
class ChaoxingVideoState:
    """Provider-neutral HTMLMediaElement state from one video module frame."""

    frame_url: str
    paused: bool
    ended: bool
    current_time: float
    duration: float | None
    ready_state: int


@dataclass(frozen=True, slots=True)
class ChaoxingPageState:
    """Validated snapshot of the active Chaoxing card and its video frames."""

    content_frame_url: str
    knowledge_id: str | None
    active_tab_index: int
    has_next_tab: bool
    modules: tuple[ChaoxingModuleState, ...]
    videos: tuple[ChaoxingVideoState, ...]
