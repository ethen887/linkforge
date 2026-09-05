"""Failures raised while handling deterministic Chaoxing course tasks."""


class ChaoxingTaskError(RuntimeError):
    """Base class for Chaoxing task handling failures."""


class ChaoxingInspectionError(ChaoxingTaskError):
    """The current Chaoxing DOM state cannot be read unambiguously."""


class VideoTaskError(ChaoxingTaskError):
    """The current Chaoxing video task cannot be handled reliably."""


class VideoPlaybackError(VideoTaskError):
    """The target video cannot be started through normal media playback."""


class VideoTimeoutError(VideoTaskError):
    """A video lifecycle deadline expired before platform completion."""


class ContentNavigationError(ChaoxingTaskError):
    """The current content cannot be advanced and verified reliably."""
