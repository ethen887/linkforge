"""Chaoxing workflow exceptions."""


class ChaoxingDocumentError(RuntimeError):
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
