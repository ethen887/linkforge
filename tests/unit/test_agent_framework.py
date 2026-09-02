"""Unit tests for the agent framework, using a Fake LLM."""

from linkforge.agent.framework import AgentTool, RecAgent
from linkforge.llm.base import LLMMessage, LLMResponse, ToolCall
from tests.fakes import FakeLLM, RecordingFakeLLM


def make_weather_tool():
    """A simple weather tool for testing, no API calls."""

    def get_weather(location: str) -> str:
        return f"Weather in {location}: sunny, 25C"

    return AgentTool(
        name="get_weather",
        parameters={
            "type": "object",
            "properties": {"location": {"type": "string", "description": "City name"}},
            "required": ["location"],
        },
        description="Get the current weather for a city",
        function=get_weather,
    )


class TestAgentRequiresLLMAbstraction:
    """Verify that the agent framework does NOT depend on concrete LLM implementations."""

    def test_agent_accepts_any_llm_subclass(self):
        fake = FakeLLM([LLMResponse(content="hi")])
        agent = RecAgent(system_prompt="test", client=fake, tools=[], model="fake-model")
        result = agent.run("hello")
        assert result == "hi"

    def test_agent_uses_fake_llm_not_real_api(self):
        """The agent must work with a fake LLM (proves no hard-coded API calls)."""
        recording = RecordingFakeLLM()
        recording.add_response(LLMResponse(content="Mock response"))

        agent = RecAgent(
            system_prompt="You are a test agent.", client=recording, tools=[], model="any-model"
        )

        agent.run("test prompt")

        # Verify the FakeLLM was actually called
        assert len(recording.calls) == 1
        assert recording.calls[0]["model"] == "any-model"


class TestAgentToolCalling:
    """Test that tool calls work correctly with a fake LLM."""

    def test_agent_calls_tool_and_returns_result(self):
        received_locations = []

        def get_weather(location: str) -> str:
            received_locations.append(location)
            return f"Weather in {location}: sunny, 25C"

        tool = AgentTool(
            name="get_weather",
            parameters={"type": "object", "properties": {}},
            description="Get weather",
            function=get_weather,
        )
        fake = RecordingFakeLLM(
            [
                LLMResponse(
                    content=None,
                    tool_calls=[
                        ToolCall(id="call_1", name="get_weather", arguments={"location": "Hangzhou"})
                    ],
                ),
                LLMResponse(content="Hangzhou is sunny, 25C."),
            ]
        )

        agent = RecAgent(
            system_prompt="Weather assistant",
            client=fake,
            tools=[tool],
            model="fake-model",
        )

        result = agent.run("What's the weather in Hangzhou?")

        assert result == "Hangzhou is sunny, 25C."
        assert received_locations == ["Hangzhou"]
        assert len(fake.calls) == 2

        second_call_messages = fake.calls[1]["messages"]
        assert [message.role for message in second_call_messages] == [
            "system",
            "user",
            "assistant",
            "tool",
        ]
        assert second_call_messages[2].tool_calls[0].id == "call_1"
        assert second_call_messages[3] == LLMMessage(
            role="tool",
            content="Weather in Hangzhou: sunny, 25C",
            tool_call_id="call_1",
        )

    def test_agent_executes_multiple_tool_calls_in_order_before_next_inference(self):
        events = []

        def get_weather(location: str) -> str:
            events.append(f"tool:{location}")
            return f"Weather in {location}"

        tool = AgentTool(
            name="get_weather",
            parameters={"type": "object", "properties": {}},
            description="Get weather",
            function=get_weather,
        )
        fake = RecordingFakeLLM(
            [
                LLMResponse(
                    content=None,
                    tool_calls=[
                        ToolCall(
                            id="call_1",
                            name="get_weather",
                            arguments={"location": "Hangzhou"},
                        ),
                        ToolCall(
                            id="call_2",
                            name="get_weather",
                            arguments={"location": "Shanghai"},
                        ),
                    ],
                ),
                LLMResponse(content="Both cities are sunny."),
            ],
            events=events,
        )
        agent = RecAgent(system_prompt="test", client=fake, tools=[tool], model="fake-model")

        result = agent.run("compare weather")

        assert result == "Both cities are sunny."
        assert events == ["llm", "tool:Hangzhou", "tool:Shanghai", "llm"]

        second_call_messages = fake.calls[1]["messages"]
        assert [message.role for message in second_call_messages] == [
            "system",
            "user",
            "assistant",
            "tool",
            "tool",
        ]
        assert [tool_call.id for tool_call in second_call_messages[2].tool_calls] == [
            "call_1",
            "call_2",
        ]
        assert [message.tool_call_id for message in second_call_messages[3:]] == [
            "call_1",
            "call_2",
        ]
        assert [message.content for message in second_call_messages[3:]] == [
            "Weather in Hangzhou",
            "Weather in Shanghai",
        ]

    def test_agent_handles_unknown_tool_gracefully(self):
        fake = RecordingFakeLLM(
            [
                LLMResponse(
                    content=None,
                    tool_calls=[ToolCall(id="call_1", name="nonexistent_tool", arguments={})],
                ),
                LLMResponse(content="Sorry, I cannot help with that."),
            ]
        )

        agent = RecAgent(system_prompt="test", client=fake, tools=[make_weather_tool()], model="fake-model")

        result = agent.run("do something")

        assert result == "Sorry, I cannot help with that."
        assert len(fake.calls) == 2
        assert fake.calls[1]["messages"][-1] == LLMMessage(
            role="tool",
            content="Error: 'nonexistent_tool', tool execution failed",
            tool_call_id="call_1",
        )

    def test_agent_returns_tool_execution_exception_to_model(self):
        def failing_tool(location: str) -> str:
            raise RuntimeError(f"weather backend unavailable for {location}")

        tool = AgentTool(
            name="get_weather",
            parameters={"type": "object", "properties": {}},
            description="Get weather",
            function=failing_tool,
        )
        fake = RecordingFakeLLM(
            [
                LLMResponse(
                    content=None,
                    tool_calls=[
                        ToolCall(
                            id="call_failure",
                            name="get_weather",
                            arguments={"location": "Hangzhou"},
                        )
                    ],
                ),
                LLMResponse(content="The weather service is unavailable."),
            ]
        )
        agent = RecAgent(system_prompt="test", client=fake, tools=[tool], model="fake-model")

        result = agent.run("get weather")

        assert result == "The weather service is unavailable."
        assert len(fake.calls) == 2
        assert fake.calls[1]["messages"][-1] == LLMMessage(
            role="tool",
            content="Error: weather backend unavailable for Hangzhou, tool execution failed",
            tool_call_id="call_failure",
        )

    def test_agent_respects_max_steps(self):
        """If the fake LLM keeps requesting tools, the agent should give up after max_steps."""
        executed_locations = []

        def get_weather(location: str) -> str:
            executed_locations.append(location)
            return f"Weather in {location}"

        tool = AgentTool(
            name="get_weather",
            parameters={"type": "object", "properties": {}},
            description="Get weather",
            function=get_weather,
        )
        fake = FakeLLM(
            [
                LLMResponse(
                    content=None,
                    tool_calls=[
                        ToolCall(id=f"call_{i}", name="get_weather", arguments={"location": f"City{i}"})
                    ],
                )
                for i in range(10)
            ]
        )

        agent = RecAgent(system_prompt="test", client=fake, tools=[tool], model="fake-model")

        result = agent.run("loop test", max_steps=3)

        assert result == "Task execution exceeded 3 steps, task failed"
        assert fake.call_count == 3
        assert executed_locations == ["City0", "City1", "City2"]

    def test_agent_terminates_on_text_response(self):
        """If the LLM responds with text and no tool calls, the agent should stop."""
        executed_locations = []

        def get_weather(location: str) -> str:
            executed_locations.append(location)
            return "unexpected"

        tool = AgentTool(
            name="get_weather",
            parameters={"type": "object", "properties": {}},
            description="Get weather",
            function=get_weather,
        )
        fake = FakeLLM([LLMResponse(content="Just a plain text answer.")])

        agent = RecAgent(system_prompt="test", client=fake, tools=[tool], model="fake-model")

        result = agent.run("simple question")

        assert result == "Just a plain text answer."
        assert fake.call_count == 1
        assert executed_locations == []

    def test_agent_history_includes_system_prompt(self):
        """The first message sent to the LLM should be the system prompt."""
        fake = RecordingFakeLLM()
        fake.add_response(LLMResponse(content="ok"))

        agent = RecAgent(
            system_prompt="You are a helpful assistant.", client=fake, tools=[], model="model-x"
        )
        agent.run("hello")

        # First message should be the system prompt
        messages = fake.calls[0]["messages"]
        assert messages[0].role == "system"
        assert messages[0].content == "You are a helpful assistant."
        # Second message should be the user prompt
        assert messages[1].role == "user"
        assert messages[1].content == "hello"
