"""Unit tests for the LLM-backed browser agent."""

import json
from typing import Any

import pytest

from linkforge.action.models import (
    ClickAction,
    FillAction,
    OpenAction,
    PressAction,
    ScrollAction,
)
from linkforge.agent.browser import BrowserAgent
from linkforge.agent.exceptions import AgentDecisionError
from linkforge.agent.llm_browser import LLMBrowserAgent
from linkforge.agent.models import BrowserDecision, FinishDecision
from linkforge.browser.models import InteractiveElement
from linkforge.llm.base import LLM, LLMMessage, LLMResponse, ToolCall
from linkforge.observation.models import Observation


class RecordingLLM(LLM):
    """Return one scripted response and record provider-neutral requests."""

    def __init__(self, response: LLMResponse) -> None:
        self.response = response
        self.calls: list[tuple[str, list[LLMMessage], list[dict[str, Any]]]] = []

    def call_model(
        self,
        model: str,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]],
    ) -> LLMResponse:
        self.calls.append((model, messages, tools))
        return self.response


def _observation() -> Observation:
    return Observation(
        url="https://example.com/form",
        title="Example Form",
        text="Enter your name",
        interactive_elements=(
            InteractiveElement(target_id=4, role="textbox", name="Name"),
            InteractiveElement(target_id=7, role="button", name="Submit"),
        ),
    )


def _agent_for(tool_call: ToolCall) -> tuple[LLMBrowserAgent, RecordingLLM]:
    llm = RecordingLLM(LLMResponse(tool_calls=[tool_call]))
    return LLMBrowserAgent(llm=llm, model="test-model"), llm


def test_decide_sends_provider_neutral_observation_and_browser_tool_schemas() -> None:
    agent, llm = _agent_for(ToolCall(id="call-1", name="finish", arguments={}))

    agent.decide(_observation())

    assert len(llm.calls) == 1
    model, messages, tools = llm.calls[0]
    assert model == "test-model"
    assert [message.role for message in messages] == ["system", "user"]
    assert messages[0].content is not None
    assert "exactly one" in messages[0].content
    assert "only a target_id listed" in messages[0].content

    observation_content = messages[1].content
    assert observation_content is not None
    payload = json.loads(observation_content.removeprefix("Current browser observation:\n"))
    assert payload == {
        "url": "https://example.com/form",
        "title": "Example Form",
        "text": "Enter your name",
        "interactive_elements": [
            {"target_id": 4, "role": "textbox", "name": "Name"},
            {"target_id": 7, "role": "button", "name": "Submit"},
        ],
    }

    functions = {tool["function"]["name"]: tool["function"] for tool in tools}
    assert set(functions) == {"open", "click", "fill", "press", "scroll", "finish"}
    assert functions["fill"]["parameters"]["required"] == ["target_id", "text"]
    assert all(function["parameters"]["additionalProperties"] is False for function in functions.values())


def test_empty_observation_fields_are_serialized_normally() -> None:
    agent, llm = _agent_for(ToolCall(id="call-1", name="finish", arguments={}))
    observation = Observation(url="", title="", text="", interactive_elements=())

    agent.decide(observation)

    content = llm.calls[0][1][1].content
    assert content is not None
    payload = json.loads(content.removeprefix("Current browser observation:\n"))
    assert payload == {"url": "", "title": "", "text": "", "interactive_elements": []}


@pytest.mark.parametrize(
    ("name", "arguments", "expected"),
    [
        ("open", {"url": "https://example.com"}, OpenAction(url="https://example.com")),
        ("click", {"target_id": 7}, ClickAction(target_id=7)),
        ("fill", {"target_id": 4, "text": "Ada"}, FillAction(target_id=4, text="Ada")),
        ("press", {"target_id": 4, "key": "Enter"}, PressAction(target_id=4, key="Enter")),
        ("scroll", {"delta_y": 600}, ScrollAction(delta_y=600)),
        ("finish", {}, FinishDecision()),
    ],
)
def test_supported_tool_call_maps_to_one_browser_decision(
    name: str,
    arguments: dict[str, Any],
    expected: BrowserDecision,
) -> None:
    agent, llm = _agent_for(ToolCall(id="call-1", name=name, arguments=arguments))

    decision = agent.decide(_observation())

    assert decision == expected
    assert len(llm.calls) == 1


def test_agent_implements_browser_agent_without_browser_or_executor() -> None:
    agent, _ = _agent_for(ToolCall(id="call-1", name="finish", arguments={}))

    assert isinstance(agent, BrowserAgent)
    assert agent.decide(_observation()) == FinishDecision()


def test_unknown_tool_is_rejected() -> None:
    agent, llm = _agent_for(ToolCall(id="call-1", name="hover", arguments={"target_id": 7}))

    with pytest.raises(AgentDecisionError, match="Unsupported browser action tool: 'hover'"):
        agent.decide(_observation())

    assert len(llm.calls) == 1


@pytest.mark.parametrize(
    ("name", "arguments", "error"),
    [
        ("click", {}, "requires exactly these arguments: target_id"),
        ("fill", {"target_id": 4}, "requires exactly these arguments: target_id, text"),
        ("press", {"target_id": "4", "key": "Enter"}, "argument 'target_id' must be int"),
        ("scroll", {"delta_y": True}, "argument 'delta_y' must be int"),
        ("finish", {"reason": "done"}, "requires exactly these arguments: none"),
    ],
)
def test_invalid_or_missing_arguments_are_rejected(
    name: str,
    arguments: dict[str, Any],
    error: str,
) -> None:
    agent, llm = _agent_for(ToolCall(id="call-1", name=name, arguments=arguments))

    with pytest.raises(AgentDecisionError, match=error):
        agent.decide(_observation())

    assert len(llm.calls) == 1


def test_non_object_arguments_are_rejected() -> None:
    tool_call = ToolCall(id="call-1", name="click", arguments=None)  # type: ignore[arg-type]
    agent, llm = _agent_for(tool_call)

    with pytest.raises(AgentDecisionError, match="arguments must be an object"):
        agent.decide(_observation())

    assert len(llm.calls) == 1


@pytest.mark.parametrize(
    "response",
    [
        LLMResponse(),
        LLMResponse(content="I am finished."),
    ],
)
def test_response_without_tool_call_is_rejected(response: LLMResponse) -> None:
    llm = RecordingLLM(response)
    agent = LLMBrowserAgent(llm=llm, model="test-model")

    with pytest.raises(AgentDecisionError, match="received 0"):
        agent.decide(_observation())

    assert len(llm.calls) == 1


def test_multiple_tool_calls_are_rejected_without_partial_decision() -> None:
    llm = RecordingLLM(
        LLMResponse(
            tool_calls=[
                ToolCall(id="call-1", name="fill", arguments={"target_id": 4, "text": "Ada"}),
                ToolCall(id="call-2", name="click", arguments={"target_id": 7}),
            ]
        )
    )
    agent = LLMBrowserAgent(llm=llm, model="test-model")

    with pytest.raises(AgentDecisionError, match="received 2"):
        agent.decide(_observation())

    assert len(llm.calls) == 1
