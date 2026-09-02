"""Agent orchestration exceptions."""


class AgentLoopError(RuntimeError):
    """Base exception for agent-loop failures."""


class MaxStepsExceededError(AgentLoopError):
    """Raised when an agent loop does not finish within its step limit."""
