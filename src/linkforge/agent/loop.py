"""Browser-agent loop orchestration."""

from linkforge.action.base import ActionExecutor
from linkforge.agent.browser import BrowserAgent
from linkforge.agent.exceptions import MaxStepsExceededError
from linkforge.agent.models import FinishDecision
from linkforge.observation.base import Observer


class BrowserAgentLoop:
    """Coordinate the observe-decide-execute browser lifecycle."""

    def __init__(
        self,
        *,
        observer: Observer,
        agent: BrowserAgent,
        executor: ActionExecutor,
    ) -> None:
        self._observer = observer
        self._agent = agent
        self._executor = executor

    def run(self, *, max_steps: int = 10) -> None:
        """Run until the agent finishes or the maximum decision count is reached."""
        if max_steps <= 0:
            raise ValueError("max_steps must be greater than 0")

        for _ in range(max_steps):
            observation = self._observer.observe()
            decision = self._agent.decide(observation)

            if isinstance(decision, FinishDecision):
                return

            self._executor.execute(decision)

        raise MaxStepsExceededError(f"Browser agent exceeded the maximum of {max_steps} steps.")
