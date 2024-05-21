
from .agent_library import library
from typing import Any, Callable, Dict, List, Literal
import autogen

from ..toolkits import register_toolkits


class FinRobot(autogen.AssistantAgent):

    def __init__(self, name: str, system_message: str|None = None, toolkits: List[Callable|dict|type] = [], proxy: autogen.UserProxyAgent|None = None, **kwargs):
        
        assert name in library, f"FinRobot {name} not found in agent library."

        default_toolkits = library["name"].get("toolkits", [])
        default_system_message = library["name"].get("profile", "")

        self.tookits = toolkits or default_toolkits
        self.system_message = system_message or default_system_message

        assert bool(self.system_message), f"System message is required for {name}."

        super().__init__(name, self.system_message, **kwargs)
        if proxy is not None:
            register_toolkits(proxy)


