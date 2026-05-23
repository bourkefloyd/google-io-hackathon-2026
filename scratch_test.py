import copy
from pydantic import BaseModel
from typing import List, Callable, Any

class CustomConfig(BaseModel):
    tools: List[Any]

class DeviceAgentTools:
    def __init__(self):
        self.recorded_actions = []
    def tap(self):
        self.recorded_actions.append("tap")

session_tools = DeviceAgentTools()
config = CustomConfig(tools=[session_tools.tap])

print("Original session_tools ID:", id(session_tools))
print("Original method __self__ ID:", id(session_tools.tap.__self__))

copied_config = config.model_copy(deep=True)
copied_method = copied_config.tools[0]
print("Copied method __self__ ID:", id(copied_method.__self__))
print("Are they the same instance?", session_tools is copied_method.__self__)

copied_method()
print("Original recorded_actions:", session_tools.recorded_actions)
print("Copied recorded_actions:", copied_method.__self__.recorded_actions)
