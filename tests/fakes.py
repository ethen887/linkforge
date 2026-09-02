"""Test doubles for external LinkForge interfaces."""

from typing import Any

from linkforge.action.base import ActionExecutor
from linkforge.action.models import Action
from linkforge.agent.browser import BrowserAgent
from linkforge.agent.models import BrowserDecision
from linkforge.browser.base import Browser
from linkforge.browser.exceptions import BrowserElementError, BrowserError
from linkforge.browser.models import InteractiveElement
from linkforge.llm.base import LLM, LLMMessage, LLMResponse
from linkforge.observation.base import Observer
from linkforge.observation.models import Observation


class FakeObserver(Observer):
    """Return scripted observations while recording loop events."""

    def __init__(
        self,
        observations: list[Observation],
        *,
        events: list[str] | None = None,
    ) -> None:
        self.observations = observations
        self.events = events if events is not None else []
        self.call_count = 0

    def observe(self) -> Observation:
        self.events.append("observe")
        if self.call_count >= len(self.observations):
            raise AssertionError("No scripted observation remains.")

        observation = self.observations[self.call_count]
        self.call_count += 1
        return observation


class FakeBrowserAgent(BrowserAgent):
    """Return scripted browser decisions while recording received observations."""

    def __init__(
        self,
        decisions: list[BrowserDecision],
        *,
        events: list[str] | None = None,
    ) -> None:
        self.decisions = decisions
        self.events = events if events is not None else []
        self.observations: list[Observation] = []
        self.call_count = 0

    def decide(self, observation: Observation) -> BrowserDecision:
        self.events.append("decide")
        self.observations.append(observation)
        if self.call_count >= len(self.decisions):
            raise AssertionError("No scripted browser decision remains.")

        decision = self.decisions[self.call_count]
        self.call_count += 1
        return decision


class FakeActionExecutor(ActionExecutor):
    """Record actions without interacting with a real execution target."""

    def __init__(self, *, events: list[str] | None = None) -> None:
        self.events = events if events is not None else []
        self.actions: list[Action] = []

    def execute(self, action: Action) -> None:
        self.events.append("execute")
        self.actions.append(action)


class FakeBrowser(Browser):
    """A deterministic Browser implementation that does not launch a real browser."""

    def __init__(
        self,
        *,
        url: str = "about:blank",
        title: str = "",
        text: str = "",
        interactive_elements: tuple[InteractiveElement, ...] = (),
        observation_error: BrowserError | None = None,
        action_error: BrowserError | None = None,
    ) -> None:
        self.url = url
        self.page_title = title
        self.page_text = text
        self.page_interactive_elements = interactive_elements
        self.observation_error = observation_error
        self.action_error = action_error
        self.action_calls: list[tuple[object, ...]] = []
        self._active_target_ids: set[int] = set()

    def start(self) -> None:
        pass

    def open(self, url: str) -> None:
        self._raise_action_error()
        self.url = url
        self._active_target_ids.clear()
        self.action_calls.append(("open", url))

    def current_url(self) -> str:
        self._raise_observation_error()
        return self.url

    def title(self) -> str:
        self._raise_observation_error()
        return self.page_title

    def text(self) -> str:
        self._raise_observation_error()
        return self.page_text

    def interactive_elements(self) -> tuple[InteractiveElement, ...]:
        self._raise_observation_error()
        self._active_target_ids = {element.target_id for element in self.page_interactive_elements}
        return self.page_interactive_elements

    def click_target(self, target_id: int) -> None:
        self._require_target(target_id)
        self._raise_action_error()
        self.action_calls.append(("click_target", target_id))

    def fill_target(self, target_id: int, text: str) -> None:
        self._require_target(target_id)
        self._raise_action_error()
        self.action_calls.append(("fill_target", target_id, text))

    def press_target(self, target_id: int, key: str) -> None:
        self._require_target(target_id)
        self._raise_action_error()
        self.action_calls.append(("press_target", target_id, key))

    def click(self, selector: str) -> None:
        self._raise_action_error()
        self.action_calls.append(("click", selector))

    def fill(self, selector: str, text: str) -> None:
        self._raise_action_error()
        self.action_calls.append(("fill", selector, text))

    def press(self, selector: str, key: str) -> None:
        self._raise_action_error()
        self.action_calls.append(("press", selector, key))

    def scroll(self, delta_y: int) -> None:
        self._raise_action_error()
        self.action_calls.append(("scroll", delta_y))

    def close(self) -> None:
        self._active_target_ids.clear()

    def _raise_observation_error(self) -> None:
        if self.observation_error is not None:
            raise self.observation_error

    def _raise_action_error(self) -> None:
        if self.action_error is not None:
            raise self.action_error

    def _require_target(self, target_id: int) -> None:
        if target_id not in self._active_target_ids:
            raise BrowserElementError(f"Unknown or stale target_id: {target_id}")


class FakeLLM(LLM):
    """A deterministic fake LLM that returns predefined responses for testing."""

    def __init__(self, scripted_responses: list[LLMResponse] | None = None):
        self.scripted_responses = scripted_responses or []
        self.call_count = 0
        self.received_messages = []
        self.received_tools = []
        self.received_model = None

    def add_response(self, response: LLMResponse):
        """Add a response to the scripted sequence."""
        self.scripted_responses.append(response)

    def call_model(
        self,
        model: str,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]],
    ) -> LLMResponse:
        """Return the next scripted response."""
        self.received_model = model
        self.received_messages = list(messages)
        self.received_tools = list(tools)

        if self.call_count >= len(self.scripted_responses):
            return LLMResponse(content="No more scripted responses")

        response = self.scripted_responses[self.call_count]
        self.call_count += 1
        return response


class RecordingFakeLLM(FakeLLM):
    """A fake LLM that records all calls for assertions."""

    def __init__(
        self,
        scripted_responses: list[LLMResponse] | None = None,
        *,
        events: list[str] | None = None,
    ):
        super().__init__(scripted_responses)
        self.calls = []
        self.events = events

    def call_model(
        self,
        model: str,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]],
    ) -> LLMResponse:
        if self.events is not None:
            self.events.append("llm")
        self.calls.append(
            {
                "model": model,
                "messages": list(messages),
                "tools": list(tools),
            }
        )
        return super().call_model(model, messages, tools)
