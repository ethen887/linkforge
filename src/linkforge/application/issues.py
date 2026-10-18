"""单次运行中待用户检查的问题摘要。"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RunIssue:
    """仅保存经过脱敏的位置、原因和处理结果。"""

    location: str
    task: str
    reason: str
    outcome: str

    def describe(self) -> str:
        return f"{self.location} · {self.task}：{self.reason}（{self.outcome}）"
