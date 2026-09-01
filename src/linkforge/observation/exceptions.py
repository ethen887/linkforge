"""Observation-layer exceptions."""


class ObservationError(RuntimeError):
    """Base exception for observation failures."""


class ObservationCaptureError(ObservationError):
    """Raised when an observation source cannot be captured."""
