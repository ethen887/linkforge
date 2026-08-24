from typing import Any, Callable

from linkforge.llm.base import LLM


class AgentTool:
    def __init__(
        self,
        name: str,
        parameters: dict[str, Any],
        description: str,
        function: Callable[..., Any],
    ):
        self.name = name
        self.parameters = parameters
        self.description = description
        self.function = function

    def func_json(self) -> dict[str, Any]:
        """Create the JSON tool specification sent to the model."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "parameters": self.parameters,
                "description": self.description,
            },
        }


class RecAgent:
    """Agent that handles tasks according to a specific system prompt."""

    def __init__(
        self,
        system_prompt: str,
        client: LLM,
        tools: list[AgentTool],
        model: str,
    ):
        self.system_prompt = system_prompt
        self.client = client
        self.tools = tools
        self.model = model

        self.tools_map = {tool.name: tool for tool in tools}
        self.tools_json = [tool.func_json() for tool in tools]

    def run(self, prompt: str, max_steps: int = 5) -> str | None:
        """Run the agent for at most ``max_steps`` iterations."""
        history = [
            self.client._convert_messages(
                role="system",
                content=self.system_prompt,
            ),
            self.client._convert_messages(
                role="user",
                content=prompt,
            ),
        ]

        for _ in range(max_steps):
            response = self.client.call_model(
                self.model,
                history,
                tools=self.tools_json,
            )

            text = response.content
            tool_calls = response.tool_calls

            if tool_calls:
                history.append(
                    self.client._convert_messages(
                        role="assistant",
                        tool_calls=tool_calls,
                        content=text,
                    )
                )

                for tool_call in tool_calls:
                    tool_name = tool_call.name

                    try:
                        tool_arguments = tool_call.arguments
                        tool = self.tools_map[tool_name]
                        result = tool.function(**tool_arguments)

                        print(
                            "Tool call successful, "
                            f"tool name: {tool_name}, "
                            f"arguments: {tool_arguments}, "
                            f"result: {result}"
                        )
                    except Exception as e:
                        result = f"Error: {e}, tool execution failed"
                        print(result)

                    history.append(
                        self.client._convert_messages(
                            role="tool",
                            content=str(result),
                            tool_call_id=tool_call.id,
                        )
                    )

            else:
                history.append(
                    self.client._convert_messages(
                        role="assistant",
                        content=text,
                    )
                )

                print(
                    "No function was called for this task, "
                    f"model only outputs text content: {text}"
                )
                return text

        return f"Task execution exceeded {max_steps} steps, task failed"
