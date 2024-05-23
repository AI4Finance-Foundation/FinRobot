from .agent_library import library
from typing import Any, Callable, Dict, List, Literal
import autogen
from autogen.cache import Cache

from ..toolkits import register_toolkits
from .utils import *


class FinRobot(autogen.AssistantAgent):

    def __init__(
        self,
        name: str,
        system_message: str | None = None,
        toolkits: List[Callable | dict | type] = [],
        proxy: autogen.UserProxyAgent | None = None,
        **kwargs,
    ):
        orig_name = name
        name = name.replace("_Shadow", "")
        assert name in library, f"FinRobot {name} not found in agent library."

        default_toolkits = library[name].get("toolkits", [])
        default_system_message = library[name].get("profile", "")

        self.toolkits = toolkits or default_toolkits
        system_message = system_message or default_system_message

        assert bool(system_message), f"System message is required for {name}."

        super().__init__(orig_name, system_message, **kwargs)
        if proxy is not None:
            register_toolkits(self.toolkits, self, proxy)


class SingleAssistant:

    def __init__(
        self,
        name: str,
        llm_config: Dict[str, Any] = {},
        is_termination_msg=lambda x: x.get("content", "")
        and x.get("content", "").endswith("TERMINATE"),
        human_input_mode="NEVER",
        max_consecutive_auto_reply=10,
        code_execution_config={
            "work_dir": "coding",
            "use_docker": False,
        },
        **kwargs,
    ):
        self.user_proxy = autogen.UserProxyAgent(
            name="User_Proxy",
            is_termination_msg=is_termination_msg,
            human_input_mode=human_input_mode,
            max_consecutive_auto_reply=max_consecutive_auto_reply,
            code_execution_config=code_execution_config,
            **kwargs,
        )
        self.assistant = FinRobot(
            name,
            llm_config=llm_config,
            proxy=self.user_proxy,
        )

    def chat(self, message: str, use_cache=False, **kwargs):
        with Cache.disk() as cache:
            self.user_proxy.initiate_chat(
                self.assistant,
                message=message,
                cache=cache if use_cache else None,
                **kwargs,
            )


class SingleAssistantShadow(SingleAssistant):

    def __init__(
        self,
        name: str,
        llm_config: Dict[str, Any] = {},
        is_termination_msg=lambda x: x.get("content", "")
        and x.get("content", "").endswith("TERMINATE"),
        human_input_mode="NEVER",
        max_consecutive_auto_reply=10,
        code_execution_config={
            "work_dir": "coding",
            "use_docker": False,
        },
        **kwargs,
    ):
        super().__init__(
            name,
            llm_config=llm_config,
            is_termination_msg=is_termination_msg,
            human_input_mode=human_input_mode,
            max_consecutive_auto_reply=max_consecutive_auto_reply,
            code_execution_config=code_execution_config,
            **kwargs,
        )
        self.assistant = FinRobot(
            name,
            llm_config=llm_config,
            is_termination_msg=lambda x: x.get("content", "")
            and x.get("content", "").endswith("TERMINATE"),
            proxy=self.user_proxy,
        )
        self.assistant_shadow = FinRobot(
            name + "_Shadow",
            toolkits=[],
            llm_config=llm_config,
            proxy=None,
        )
        self.assistant.register_nested_chats(
            [
                {
                    "sender": self.assistant,
                    "recipient": self.assistant_shadow,
                    "message": order_message,
                    "summary_method": "last_msg",
                    "max_turns": 2,
                    "silent": True,  # mute the chat summary
                }
            ],
            trigger=order_trigger,
        )
