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


class ChaoxingCommentError(ChaoxingTaskError):
    """Base error for the supported Chaoxing comment workflow."""


class ChaoxingCommentStateError(ChaoxingCommentError):
    """The current discussion identity or DOM contract is ambiguous."""


class ChaoxingCommentRecoveryError(ChaoxingCommentError):
    """The original course page could not be restored reliably."""


class ChaoxingCommentGenerationError(ChaoxingCommentError):
    """A comment body could not be generated or validated."""


class ChaoxingDocumentError(ChaoxingTaskError):
    """Base error for the deterministic Chaoxing document workflow."""


class ChaoxingDocumentInspectionError(ChaoxingDocumentError):
    """Raised when browser-backed document inspection fails."""


class ChaoxingDocumentStateError(ChaoxingDocumentError):
    """Raised when the observed document state violates the DOM contract."""


class ChaoxingDocumentNotFoundError(ChaoxingDocumentError):
    """Raised when no pending document is present."""


class ChaoxingDocumentViewerReadyTimeoutError(ChaoxingDocumentError):
    """Raised when the target PDF viewer does not become ready in time."""


class ChaoxingDocumentProgressTimeoutError(ChaoxingDocumentError):
    """Raised when repeated real scroll actions make no observable progress."""


class ChaoxingDocumentTimeoutError(ChaoxingDocumentError):
    """Raised when one document workflow exceeds its overall fault timeout."""
