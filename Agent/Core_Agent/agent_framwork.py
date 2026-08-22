import json
from Model_Interface.openai_llm import OpenAIInterface
from Model_Interface.anthropic_llm import AnthropicInterface
from typing import List, Dict, Any, Callable
from Model_Interface.basic_llm import LLM

class AgentTool:
    def __init__(self, name: str, parameters: dict, description: str, function: Callable):
        self.name = name
        self.parameters = parameters
        self.description = description
        self.function = function
    def func_json(self) -> Dict[str, Any]: #制作工具对象的json说明书, 让模型知道这个工具可以做什么
        return {
            "type": "function",
            "function":
            {
                "name":self.name,
                "parameters":self.parameters,
                "description":self.description
            }
        }
    
class RecAgent:  # 一个ReAgent类负责一类对应的问题, 具体和什么相关, 由这个系统提示词决定
    def __init__(self, system_prompt: str, client: LLM, tools: List[AgentTool], model: str):
        self.system_prompt = system_prompt
        self.client = client
        self.tools = tools
        self.model = model
        self.tools_map = {tool.name: tool for tool in tools} # 将tools列表中的每个工具的name属性作为键，tool对象本身作为值，制作一张工具索引表
        self.tools_json = [tool.func_json() for tool in tools] # 将tools列表中的每个工具对象转换为json格式, 发送给模型, 让模型知道有哪些工具可以使用
    def run(self, prompt: str, max_steps: int = 5) -> str: # 默认某项工作最多五步就可以完成
        history = [self.client._convert_messages(role = "system", content = self.system_prompt),
                   self.client._convert_messages(role = "user",   content = prompt)
                  ]  # 初始化历史记录, 将系统提示词(这个agent的核心任务)和用户提问(此次任务的具体内容)添加到历史记录中
        for step in range(max_steps):
            response = self.client.call_model(self.model, history, tools=self.tools_json)
            text = response.content
            tool_calls = response.tool_calls
            if tool_calls: # 有工具调用
                history.append(self.client._convert_messages
                               (role = "assistant", tool_calls = tool_calls, content = text)
                              ) # 将工具调用信息添加到历史记录中
                for tool_call in tool_calls:
                    tool_name = tool_call.name
                    try:
                        tool_arguments = tool_call.arguments
                        tool = self.tools_map[tool_name] # 根据工具索引表, 找到对应工具的函数地址
                        result = tool.function(**tool_arguments) # 调用工具函数, 并将参数传入
                        print(f"工具调用成功, 工具名称:{tool_name}, 参数:{tool_arguments}, 结果:{result}")
                    except Exception as e:
                        result = f"Error: {e}, 执行工具失败"
                        print(f"Error: {e},执行工具失败")
                    history.append(self.client._convert_messages
                        (role = "tool", content = str(result), tool_call_id = tool_call.id)   
                                  ) # 将工具调用结果添加到历史记录中
                    continue
            else: # 没有工具调用
                history.append(self.client._convert_messages
                               (role = "assistant", content = text)
                               )
                print(f"此次任务没有调用任何函数,模型只输出文本内容:{text}")
                return text
        return f"任务执行超过{max_steps}步, 任务失败"
    
            
        
