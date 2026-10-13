"""智能体编排异常。"""


class AgentLoopError(RuntimeError):
    """智能体循环失败的基础异常。"""


class MaxStepsExceededError(AgentLoopError):
    """当智能体循环未在其步数限制内结束时抛出。"""


class AgentDecisionError(AgentLoopError):
    """当智能体无法产生有效的浏览器决策时抛出。"""
