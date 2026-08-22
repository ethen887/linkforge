"""Unit tests for the agent framework, using a Fake LLM."""
import pytest
from linkforge.agent.framework import RecAgent, AgentTool
from linkforge.llm.base import LLMResponse, ToolCall
from tests.fakes import FakeLLM, RecordingFakeLLM


def make_weather_tool():
    """A simple weather tool for testing, no API calls."""
    def get_weather(location: str) -> str:
        return f"Weather in {location}: sunny, 25C"

    return AgentTool(
        name="get_weather",
        parameters={
            "type": "object",
            "properties": {
                "location": {"type": "string", "description": "City name"}
            },
            "required": ["location"]
        },
        description="Get the current weather for a city",
        function=get_weather
    )


class TestAgentRequiresLLMAbstraction:
    """Verify that the agent framework does NOT depend on concrete LLM implementations."""

    def test_agent_accepts_any_llm_subclass(self):
        fake = FakeLLM([LLMResponse(content="hi")])
        agent = RecAgent(
            system_prompt="test",
            client=fake,
            tools=[],
            model="fake-model"
        )
        result = agent.run("hello")
        assert result == "hi"

    def test_agent_uses_fake_llm_not_real_api(self):
        """The agent must work with a fake LLM (proves no hard-coded API calls)."""
        recording = RecordingFakeLLM()
        recording.add_response(LLMResponse(content="Mock response"))

        agent = RecAgent(
            system_prompt="You are a test agent.",
            client=recording,
            tools=[],
            model="any-model"
        )

        agent.run("test prompt")

        # Verify the FakeLLM was actually called
        assert len(recording.calls) == 1
        assert recording.calls[0]["model"] == "any-model"


class TestAgentToolCalling:
    """Test that tool calls work correctly with a fake LLM."""

    def test_agent_calls_tool_and_returns_result(self):
        # First response: tool call. Second response: final answer.
        fake = FakeLLM([
            LLMResponse(
                content=None,
                tool_calls=[ToolCall(
                    id="call_1",
                    name="get_weather",
                    arguments={"location": "Hangzhou"}
                )]
            ),
            LLMResponse(content="Hangzhou is sunny, 25C.")
        ])

        agent = RecAgent(
            system_prompt="Weather assistant",
            client=fake,
            tools=[make_weather_tool()],
            model="fake-model"
        )

        result = agent.run("What's the weather in Hangzhou?")

        assert "Hangzhou" in result or "sunny" in result.lower()
        assert fake.call_count == 2

    def test_agent_handles_unknown_tool_gracefully(self):
        fake = FakeLLM([
            LLMResponse(
                content=None,
                tool_calls=[ToolCall(
                    id="call_1",
                    name="nonexistent_tool",
                    arguments={}
                )]
            ),
            LLMResponse(content="Sorry, I cannot help with that.")
        ])

        agent = RecAgent(
            system_prompt="test",
            client=fake,
            tools=[make_weather_tool()],
            model="fake-model"
        )

        # Should not crash even with an unknown tool
        result = agent.run("do something")
        assert isinstance(result, str)

    def test_agent_respects_max_steps(self):
        """If the fake LLM keeps requesting tools, the agent should give up after max_steps."""
        fake = FakeLLM([
            LLMResponse(
                content=None,
                tool_calls=[ToolCall(
                    id=f"call_{i}",
                    name="get_weather",
                    arguments={"location": f"City{i}"}
                )]
            )
            for i in range(10)
        ])

        agent = RecAgent(
            system_prompt="test",
            client=fake,
            tools=[make_weather_tool()],
            model="fake-model"
        )

        result = agent.run("loop test", max_steps=3)

        assert "exceeded" in result.lower() or "failed" in result.lower()
        assert fake.call_count == 3  # Should stop at max_steps

    def test_agent_terminates_on_text_response(self):
        """If the LLM responds with text and no tool calls, the agent should stop."""
        fake = FakeLLM([LLMResponse(content="Just a plain text answer.")])

        agent = RecAgent(
            system_prompt="test",
            client=fake,
            tools=[make_weather_tool()],
            model="fake-model"
        )

        result = agent.run("simple question")

        assert result == "Just a plain text answer."
        assert fake.call_count == 1

    def test_agent_history_includes_system_prompt(self):
        """The first message sent to the LLM should be the system prompt."""
        fake = RecordingFakeLLM()
        fake.add_response(LLMResponse(content="ok"))

        agent = RecAgent(
            system_prompt="You are a helpful assistant.",
            client=fake,
            tools=[],
            model="model-x"
        )
        agent.run("hello")

        # First message should be the system prompt
        messages = fake.calls[0]["messages"]
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == "You are a helpful assistant."
        # Second message should be the user prompt
        assert messages[1]["role"] == "user"
        assert messages[1]["content"] == "hello"