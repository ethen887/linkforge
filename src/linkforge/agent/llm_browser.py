"""LLM-backed browser-agent decision implementation."""

import json
from typing import Any

from linkforge.action.models import (
    ClickAction,
    FillAction,
    OpenAction,
    PressAction,
    ScrollAction,
)
from linkforge.agent.browser import BrowserAgent
from linkforge.agent.exceptions import AgentDecisionError
from linkforge.agent.models import BrowserDecision, FinishDecision
from linkforge.llm.base import LLM, LLMMessage, ToolCall
from linkforge.observation.models import Observation

_SYSTEM_PROMPT = """You are the decision component of a browser agent.
Choose exactly one browser action for the current observation by calling exactly one provided tool.
For click, fill, and press, use only a target_id listed in the current observation.
Do not invent target IDs, selectors, DOM handles, XPath expressions, or additional actions."""

_BROWSER_ACTION_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "open",
            "description": "Open a URL in the browser.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The URL to open.",
                    }
                },
                "required": ["url"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "click",
            "description": "Click an interactive element from the current observation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "target_id": {
                        "type": "integer",
                        "description": "A target_id from the current observation.",
                    }
                },
                "required": ["target_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fill",
            "description": "Fill an interactive element with text.",
            "parameters": {
                "type": "object",
                "properties": {
                    "target_id": {
                        "type": "integer",
                        "description": "A target_id from the current observation.",
                    },
                    "text": {
                        "type": "string",
                        "description": "The text to enter.",
                    },
                },
                "required": ["target_id", "text"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "press",
            "description": "Send a key press to an interactive element.",
            "parameters": {
                "type": "object",
                "properties": {
                    "target_id": {
                        "type": "integer",
                        "description": "A target_id from the current observation.",
                    },
                    "key": {
                        "type": "string",
                        "description": "The key to press, such as Enter or Escape.",
                    },
                },
                "required": ["target_id", "key"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "scroll",
            "description": "Scroll the browser vertically by a CSS pixel delta.",
            "parameters": {
                "type": "object",
                "properties": {
                    "delta_y": {
                        "type": "integer",
                        "description": "Vertical distance in CSS pixels; positive scrolls down.",
                    }
                },
                "required": ["delta_y"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finish",
            "description": "Finish the browser-agent loop because the task is complete.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
        },
    },
]


class LLMBrowserAgent(BrowserAgent):
    """Choose one browser decision with one provider-neutral LLM request."""

    def __init__(self, *, llm: LLM, model: str) -> None:
        self._llm = llm
        self._model = model

    def decide(self, observation: Observation) -> BrowserDecision:
        """Return exactly one decision from exactly one model inference."""
        messages = [
            LLMMessage(role="system", content=_SYSTEM_PROMPT),
            LLMMessage(role="user", content=self._serialize_observation(observation)),
        ]
        response = self._llm.call_model(self._model, messages, _BROWSER_ACTION_TOOLS)

        if len(response.tool_calls) != 1:
            raise AgentDecisionError(
                "LLM response must contain exactly one browser action tool call; "
                f"received {len(response.tool_calls)}."
            )

        return self._to_decision(response.tool_calls[0])

    @staticmethod
    def _serialize_observation(observation: Observation) -> str:
        observation_data = {
            "url": observation.url,
            "title": observation.title,
            "text": observation.text,
            "interactive_elements": [
                {
                    "target_id": element.target_id,
                    "role": element.role,
                    "name": element.name,
                }
                for element in observation.interactive_elements
            ],
        }
        return "Current browser observation:\n" + json.dumps(
            observation_data,
            ensure_ascii=False,
            indent=2,
        )

    @classmethod
    def _to_decision(cls, tool_call: ToolCall) -> BrowserDecision:
        arguments = tool_call.arguments
        if not isinstance(arguments, dict):
            raise AgentDecisionError(f"Tool '{tool_call.name}' arguments must be an object.")

        if tool_call.name == "open":
            cls._require_arguments(tool_call, {"url": str})
            return OpenAction(url=arguments["url"])

        if tool_call.name == "click":
            cls._require_arguments(tool_call, {"target_id": int})
            return ClickAction(target_id=arguments["target_id"])

        if tool_call.name == "fill":
            cls._require_arguments(tool_call, {"target_id": int, "text": str})
            return FillAction(target_id=arguments["target_id"], text=arguments["text"])

        if tool_call.name == "press":
            cls._require_arguments(tool_call, {"target_id": int, "key": str})
            return PressAction(target_id=arguments["target_id"], key=arguments["key"])

        if tool_call.name == "scroll":
            cls._require_arguments(tool_call, {"delta_y": int})
            return ScrollAction(delta_y=arguments["delta_y"])

        if tool_call.name == "finish":
            cls._require_arguments(tool_call, {})
            return FinishDecision()

        raise AgentDecisionError(f"Unsupported browser action tool: '{tool_call.name}'.")

    @staticmethod
    def _require_arguments(tool_call: ToolCall, expected: dict[str, type]) -> None:
        arguments = tool_call.arguments
        if set(arguments) != set(expected):
            expected_names = ", ".join(expected) or "none"
            raise AgentDecisionError(
                f"Tool '{tool_call.name}' requires exactly these arguments: {expected_names}."
            )

        for name, expected_type in expected.items():
            value = arguments[name]
            if not isinstance(value, expected_type) or (expected_type is int and isinstance(value, bool)):
                raise AgentDecisionError(
                    f"Tool '{tool_call.name}' argument '{name}' must be {expected_type.__name__}."
                )
