"""Unit tests for browser-agent loop orchestration."""

import pytest

from linkforge.action.models import ClickAction, FillAction, ScrollAction
from linkforge.agent.exceptions import MaxStepsExceededError
from linkforge.agent.loop import BrowserAgentLoop
from linkforge.agent.models import FinishDecision
from linkforge.browser.models import InteractiveElement
from linkforge.observation.models import Observation
from tests.fakes import FakeActionExecutor, FakeBrowserAgent, FakeObserver


def _observation(
    text: str,
    *elements: InteractiveElement,
) -> Observation:
    return Observation(
        url="https://example.com",
        title="Example",
        text=text,
        interactive_elements=elements,
    )


def test_loop_runs_observe_decide_execute_in_order_until_finish() -> None:
    events: list[str] = []
    observations = [
        _observation("Empty form", InteractiveElement(1, "textbox", "Name")),
        _observation("Name entered", InteractiveElement(5, "button", "Submit")),
        _observation("Completed"),
    ]
    decisions = [
        FillAction(target_id=1, text="LinkForge"),
        ClickAction(target_id=5),
        FinishDecision(),
    ]
    observer = FakeObserver(observations, events=events)
    agent = FakeBrowserAgent(decisions, events=events)
    executor = FakeActionExecutor(events=events)

    BrowserAgentLoop(observer=observer, agent=agent, executor=executor).run(max_steps=3)

    assert events == [
        "observe",
        "decide",
        "execute",
        "observe",
        "decide",
        "execute",
        "observe",
        "decide",
    ]
    assert agent.observations == observations
    assert executor.actions == decisions[:2]


def test_finish_stops_without_execute_or_another_observation() -> None:
    events: list[str] = []
    observer = FakeObserver([_observation("Completed")], events=events)
    agent = FakeBrowserAgent([FinishDecision()], events=events)
    executor = FakeActionExecutor(events=events)

    BrowserAgentLoop(observer=observer, agent=agent, executor=executor).run(max_steps=5)

    assert events == ["observe", "decide"]
    assert observer.call_count == 1
    assert executor.actions == []


def test_max_steps_stops_an_unfinished_loop() -> None:
    events: list[str] = []
    observer = FakeObserver(
        [_observation("Step 1"), _observation("Step 2")],
        events=events,
    )
    agent = FakeBrowserAgent(
        [ScrollAction(delta_y=100), ScrollAction(delta_y=100)],
        events=events,
    )
    executor = FakeActionExecutor(events=events)

    with pytest.raises(MaxStepsExceededError):
        BrowserAgentLoop(observer=observer, agent=agent, executor=executor).run(max_steps=2)

    assert events == ["observe", "decide", "execute"] * 2
    assert observer.call_count == 2
    assert len(executor.actions) == 2


@pytest.mark.parametrize("max_steps", [0, -1])
def test_loop_rejects_non_positive_max_steps(max_steps: int) -> None:
    events: list[str] = []
    loop = BrowserAgentLoop(
        observer=FakeObserver([], events=events),
        agent=FakeBrowserAgent([], events=events),
        executor=FakeActionExecutor(events=events),
    )

    with pytest.raises(ValueError, match="max_steps must be greater than 0"):
        loop.run(max_steps=max_steps)

    assert events == []
