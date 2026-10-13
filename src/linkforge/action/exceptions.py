"""动作层异常。"""


class ActionError(RuntimeError):
    """动作失败的基础异常。"""


class ActionExecutionError(ActionError):
    """当动作无法被执行时抛出。"""
