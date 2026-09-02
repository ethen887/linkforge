"""Action-layer exceptions."""


class ActionError(RuntimeError):
    """Base exception for action failures."""


class ActionExecutionError(ActionError):
    """Raised when an action cannot be executed."""
