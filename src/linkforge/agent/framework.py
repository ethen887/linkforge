import json
from linkforge.llm.base import LLM, LLMResponse, ToolCall
from typing import List, Dict, Any, Callable


class AgentTool:
    def __init__(self, name: str, parameters: dict, description: str, function: Callable):
        self.name = name
        self.parameters = parameters
        self.description = description
        self.function = function
    
    def func_json(self) -> Dict[str, Any]:  # Create JSON specification for tool, so model knows what it can do
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "parameters": self.parameters,
                "description": self.description
            }
        }


class RecAgent:  # An agent class handles a specific type of questions, determined by system prompt
    def __init__(self, system_prompt: str, client: LLM, tools: List[AgentTool], model: str):
        self.system_prompt = system_prompt
        self.client = client
        self.tools = tools
        self.model = model
        self.tools_map = {tool.name: tool for tool in tools}  # Create tool index map with tool names as keys and tool objects as values
        self.tools_json = [tool.func_json() for tool in tools]  # Convert each tool in tools list to JSON format to send to model
    
    def run(self, prompt: str, max_steps: int = 5) -> str:  # Default to 5 steps maximum for a task
        history = [
            self.client._convert_messages(role="system", content=self.system_prompt),
            self.client._convert_messages(role="user", content=prompt)
        ]  # Initialize history with system prompt and user input
        
        for step in range(max_steps):
            response = self.client.call_model(self.model, history, tools=self.tools_json)
            text = response.content
            tool_calls = response.tool_calls
            
            if tool_calls:  # Has tool calls
                history.append(
                    self.client._convert_messages(
                        role="assistant", 
                        tool_calls=tool_calls, 
                        content=text
                    )
                )  # Add tool call info to history
                
                for tool_call in tool_calls:
                    tool_name = tool_call.name
                    try:
                        tool_arguments = tool_call.arguments
                        tool = self.tools_map[tool_name]  # Get tool function from index map
                        result = tool.function(**tool_arguments)  # Call tool function with arguments
                        print(f"Tool call successful, tool name: {tool_name}, arguments: {tool_arguments}, result: {result}")
                    except Exception as e:
                        result = f"Error: {e}, tool execution failed"
                        print(f"Error: {e}, tool execution failed")
                    
                    history.append(
                        self.client._convert_messages(
                            role="tool", 
                            content=str(result), 
                            tool_call_id=tool_call.id
                        )
                    )  # Add tool call result to history
                    continue
            else:  # No tool calls
                history.append(
                    self.client._convert_messages(role="assistant", content=text)
                )
                print(f"No function was called for this task, model only outputs text content: {text}")
                return text
        
        return f"Task execution exceeded {max_steps} steps, task failed"