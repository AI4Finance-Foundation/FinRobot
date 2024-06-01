from .agent_library import library
from typing import Any, Callable, Dict, List, Optional, Annotated
import autogen
from autogen.cache import Cache
from autogen.agentchat.contrib.retrieve_user_proxy_agent import RetrieveUserProxyAgent

# from autogen.agentchat.contrib.retrieve_assistant_agent import RetrieveAssistantAgent
from collections import defaultdict
from functools import partial
from abc import ABC, abstractmethod
from ..toolkits import register_toolkits
from .utils import *
from .prompts import leader_system_message, role_system_message


class FinRobot(autogen.AssistantAgent):

    def __init__(
        self,
        agent_config: str | Dict[str, Any],
        system_message: str | None = None,  # overwrites previous config
        toolkits: List[Callable | dict | type] = [],  # overwrites previous config
        proxy: autogen.UserProxyAgent | None = None,
        **kwargs,
    ):
        if isinstance(agent_config, str):
            orig_name = agent_config
            name = orig_name.replace("_Shadow", "")
            assert name in library, f"FinRobot {name} not found in agent library."
            agent_config = library[name]

        agent_config = self._preprocess_config(agent_config)

        assert agent_config, f"agent_config is required."
        assert name in agent_config, f"name needs to be in config."

        name = agent_config["name"]
        default_system_message = agent_config.get("profile", None)
        default_toolkits = agent_config.get("toolkits", [])

        system_message = system_message or default_system_message
        self.toolkits = toolkits or default_toolkits

        super().__init__(orig_name, system_message, **kwargs)

        if proxy is not None:
            self.register_toolkits(proxy)

    def _preprocess_config(self, config):

        role_prompt, leader_prompt = "", ""

        if "reponsibilities" in config:
            title = config["title"] if "title" in config else config.get("name", "")
            if "name" not in config:
                config["name"] = config["title"]
            responsibilities = config["reponsibilities"]
            responsibilities = (
                "\n".join([f" - {r}" for r in responsibilities])
                if isinstance(responsibilities, list)
                else responsibilities
            )
            role_prompt = role_system_message.format(
                title=title,
                responsibilities=responsibilities,
            )

        if "group_desc" in config:
            group_desc = config["group_desc"]
            leader_prompt = leader_system_message.format(group_desc=group_desc)

        config["profile"] = (
            role_prompt + "\n\n" + leader_prompt + "\n\n" + config.get("profile", "")
        ).strip()

        return config

    def register_proxy(self, proxy):
        register_toolkits(self.toolkits, self, proxy)


class SingleAssistantBase(ABC):

    def __init__(
        self,
        agent_config: str | Dict[str, Any],
        llm_config: Dict[str, Any] = {},
    ):
        self.assistant = FinRobot(
            agent_config=agent_config,
            llm_config=llm_config,
            proxy=None,
        )

    @abstractmethod
    def chat(self):
        pass

    @abstractmethod
    def reset(self):
        pass


class SingleAssistant(SingleAssistantBase):

    def __init__(
        self,
        agent_config: str | Dict[str, Any],
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
        super().__init__(agent_config, llm_config=llm_config)
        self.user_proxy = autogen.UserProxyAgent(
            name="User_Proxy",
            is_termination_msg=is_termination_msg,
            human_input_mode=human_input_mode,
            max_consecutive_auto_reply=max_consecutive_auto_reply,
            code_execution_config=code_execution_config,
            **kwargs,
        )
        self.assistant.register_proxy(self.user_proxy)

    def chat(self, message: str, use_cache=False, **kwargs):
        with Cache.disk() as cache:
            self.user_proxy.initiate_chat(
                self.assistant,
                message=message,
                cache=cache if use_cache else None,
                **kwargs,
            )

        print("Current chat finished. Resetting agents ...")
        self.reset()

    def reset(self):
        self.user_proxy.reset()
        self.assistant.reset()


class SingleAssistantRAG(SingleAssistantBase):

    def __init__(
        self,
        agent_config: str | Dict[str, Any],
        llm_config: Dict[str, Any] = {},
        is_termination_msg=lambda x: x.get("content", "")
        and x.get("content", "").endswith("TERMINATE"),
        human_input_mode="NEVER",
        max_consecutive_auto_reply=10,
        code_execution_config={
            "work_dir": "coding",
            "use_docker": False,
        },
        retrieve_config=None,
        **kwargs,
    ):
        super().__init__(agent_config, llm_config=llm_config)
        self.user_proxy = RetrieveUserProxyAgent(
            name="User_Proxy",
            is_termination_msg=is_termination_msg,
            human_input_mode=human_input_mode,
            max_consecutive_auto_reply=max_consecutive_auto_reply,
            code_execution_config=code_execution_config,
            retrieve_config=retrieve_config,
            **kwargs,
        )
        self.assistant.register_proxy(self.user_proxy)

    def chat(self, message: str, use_cache=False, **kwargs):
        with Cache.disk() as cache:
            self.user_proxy.initiate_chat(
                self.assistant,
                message=self.user_proxy.message_generator,
                problem=message,
                cache=cache if use_cache else None,
                **kwargs,
            )

        print("Current chat finished. Resetting agents ...")
        self.reset()

    def reset(self):
        self.user_proxy.reset()
        self.assistant.reset()


class SingleAssistantShadow(SingleAssistant):

    def __init__(
        self,
        agent_config: str | Dict[str, Any],
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
            agent_config,
            llm_config=llm_config,
            is_termination_msg=is_termination_msg,
            human_input_mode=human_input_mode,
            max_consecutive_auto_reply=max_consecutive_auto_reply,
            code_execution_config=code_execution_config,
            **kwargs,
        )
        if isinstance(agent_config, dict):
            agent_config_shadow = agent_config.copy()
            agent_config_shadow["name"] = agent_config["name"] + "_Shadow"
            agent_config_shadow["toolkits"] = []
        else:
            agent_config_shadow = agent_config + "_Shadow"

        self.assistant_shadow = FinRobot(
            agent_config,
            toolkits=[],
            llm_config=llm_config,
            proxy=None,
        )
        self.assistant.register_nested_chats(
            [
                {
                    "sender": self.assistant,
                    "recipient": self.assistant_shadow,
                    "message": instruction_message,
                    "summary_method": "last_msg",
                    "max_turns": 2,
                    "silent": True,  # mute the chat summary
                }
            ],
            trigger=instruction_trigger,
        )


"""
Multi Agent Workflows
"""


class MultiAssistantBase(ABC):

    def __init__(
        self,
        group_config: str | dict,
        agent_configs: List[Dict[str, Any] | str] = [],  # overwrites previous config
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
        self.group_config = group_config
        self.llm_config = llm_config
        self.user_proxy = autogen.UserProxyAgent(
            name="User_Proxy",
            is_termination_msg=is_termination_msg,
            human_input_mode=human_input_mode,
            max_consecutive_auto_reply=max_consecutive_auto_reply,
            code_execution_config=code_execution_config,
            **kwargs,
        )
        self.agent_configs = group_config.get("agents", []) or agent_configs
        assert self.agent_configs, f"agent_configs is required."
        self.agents = []
        self._init_agents()
        self.representative = self._get_representative()

    @abstractmethod
    def _init_single_agent(self, agent_config):
        return FinRobot(
            self._preprocess_config(agent_config),
            llm_config=self.llm_config,
            proxy=self.user_proxy,
        )

    @abstractmethod
    def _init_agents(self, agent_configs):

        agent_dict = defaultdict(list)
        for c in enumerate(agent_configs):
            agent = self._init_single_agent(c)
            agent_dict[agent.name].append(agent)

        # add index indicator for duplicate name/title
        for name, agent_list in agent_dict.items():
            if len(agent) == 1:
                self.agents.append(agent_list[0])
                continue
            for idx, agent in enumerate(agent_list):
                agent.name = f"{name}_{idx+1}"
                self.agents.append(agent)

    @abstractmethod
    def _get_representative(self):
        pass

    @abstractmethod
    def chat(self):
        pass

    @abstractmethod
    def reset(self):
        self.user_proxy
        for agent in self.agents:
            agent.reset()


class MultiAssistant(MultiAssistantBase):
    """
    Group Chat Workflow with multiple agents.
    """

    def __init__(
        self,
        group_name: str,
        agent_configs: List[Dict[str, Any] | str],
        llm_config: Dict[str, Any],
        is_termination_msg=lambda x: x.get("content", "")
        and x.get("content", "").endswith("TERMINATE"),
        human_input_mode="NEVER",
        max_consecutive_auto_reply=10,
        code_execution_config={"work_dir": "coding", "use_docker": False},
        speaker_selection_method="round_robin",
        **kwargs,
    ):
        self.speaker_selection_method = speaker_selection_method
        super().__init__(
            group_name,
            agent_configs,
            llm_config,
            is_termination_msg,
            human_input_mode,
            max_consecutive_auto_reply,
            code_execution_config,
            **kwargs,
        )

    def _get_representative(self):
        self.group_chat = autogen.GroupChat(
            self.agents + [self.user_proxy],
            messages=[],
            speaker_selection_method=self.speaker_selection_method,
        )
        manager_name = (self.group_config.get("name", "") + "_chat_manager").strip("_")
        manager = autogen.GroupChatManager(
            self.group_chat, name=manager_name, llm_config=self.llm_config
        )
        return manager

    def chat(self, message: str, use_cache=False, **kwargs):
        with Cache.disk() as cache:
            self.user_proxy.initiate_chat(
                self.representative,
                message=message,
                cache=cache if use_cache else None,
                **kwargs,
            )

        print("Current chat finished. Resetting agents ...")
        self.reset()

    def reset(self):
        super().reset()
        self.representative.reset()


class MultiAssistantWithLeader(MultiAssistant):
    """
    Leader based Workflow with multiple agents connected to a leader agent through nested chats.

    Group config has to follow the following structure:
    {
        "leader": {
            "title": "Leader Title",
            "responsibilities": ["responsibility 1", "responsibility 2"]
        },
        "agents": [
            {
                "title": "Employee Title",
                "responsibilities": ["responsibility 1", "responsibility 2"]
            }, ...
        ]
    }
    """

    def _get_representative(self):

        assert (
            "leader" in self.group_config and "agents" in self.group_config
        ), "Leader and Agents has to be explicitly defined in config."

        assert (
            self.agent_configs
        ), "At least one agent has to be defined in the group config."

        # We consider only two situations for now: all same name / title or all different
        need_suffix = len(set([c["title"] for c in self.agent_configs])) == 1

        group_desc = ""
        for i, c in enumerate(self.agent_configs):
            name = c["title"] if "title" in c else c.get("name", "")
            name = name + (f"_{i+1}" if need_suffix else "")
            responsibilities = (
                "\n".join([f" - {r}" for r in c.get("responsibilities", [])]),
            )
            group_descs += f"Name: {name}\nResponsibility:\n{responsibilities}\n\n"

        self.leader_config = self.group_config["leader"]
        self.leader_config["group_desc"] = group_desc.strip()

        # Initialize Leader
        leader = self._init_single_agent(self.leader_config)

        # Register Leader - Agents connections
        for agent in self.agents:
            self.user_proxy.register_nested_chats(
                [
                    {
                        "sender": self.user_proxy,
                        "recipient": agent,
                        "message": partial(order_message, agent.name),
                        "summary_method": "reflection_with_llm",
                        "max_turns": 10,
                        "max_consecutive_auto_reply": 3,
                    }
                ],
                trigger=partial(
                    order_trigger, name=leader.name, pattern=f"[{agent.name}]"
                ),
            )
        return leader
