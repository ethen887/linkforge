"""Unit tests for the tools framework structure."""
import pytest
from linkforge.agent.framework import AgentTool
from linkforge.tools.weather import weather_tool


class TestAgentTool:
    def test_basic_construction(self):
        def my_func():
            return "result"

        tool = AgentTool(
            name="my_tool",
            parameters={"type": "object", "properties": {}},
            description="A test tool",
            function=my_func
        )
        assert tool.name == "my_tool"
        assert tool.description == "A test tool"
        assert tool.function is my_func

    def test_func_json_format(self):
        def my_func(x: int):
            return x

        tool = AgentTool(
            name="compute",
            parameters={
                "type": "object",
                "properties": {"x": {"type": "integer"}},
                "required": ["x"]
            },
            description="Compute something",
            function=my_func
        )
        json_spec = tool.func_json()
        assert json_spec["type"] == "function"
        assert json_spec["function"]["name"] == "compute"
        assert json_spec["function"]["description"] == "Compute something"
        assert json_spec["function"]["parameters"]["type"] == "object"
        assert "x" in json_spec["function"]["parameters"]["properties"]


class TestWeatherTool:
    def test_weather_tool_is_registered(self):
        """The weather tool should be importable as a singleton."""
        assert isinstance(weather_tool, AgentTool)

    def test_weather_tool_metadata(self):
        assert weather_tool.name == "get_seniverse_weather"
        # 项目以中文为主，描述使用中文
        assert "天气" in weather_tool.description
        # 参数必须声明 location 为必填项
        params = weather_tool.parameters
        assert "location" in params["properties"]
        assert "location" in params["required"]

    def test_weather_function_callable(self):
        """Calling the tool without a configured API key should fail gracefully."""
        result = weather_tool.function(location="Hangzhou")
        # No API key is configured in the test environment
        assert isinstance(result, str)
        assert "API" in result or "Error" in result or "失败" in result