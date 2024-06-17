from .agent_library import library
from typing import Any, Callable, Dict, List, Optional, Annotated
import autogen
from autogen.cache import Cache
from autogen import (
    ConversableAgent,
    AssistantAgent,
    UserProxyAgent,
    GroupChat,
    GroupChatManager,
    register_function,
)
from collections import defaultdict
from functools import partial
from abc import ABC, abstractmethod
from ..toolkits import register_toolkits
from ..functional.rag import get_rag_function
from .utils import *
from .prompts import leader_system_message, role_system_message


class FinRobot(AssistantAgent):

    def __init__(
        self,
        agent_config: str | Dict[str, Any],
        system_message: str | None = None,  # overwrites previous config
        toolkits: List[Callable | dict | type] = [],  # overwrites previous config
        proxy: UserProxyAgent | None = None,
        **kwargs,
    ):
        orig_name = ""
        if isinstance(agent_config, str):
            orig_name = agent_config
            name = orig_name.replace("_Shadow", "")
            assert name in library, f"FinRobot {name} not found in agent library."
            agent_config = library[name]

        agent_config = self._preprocess_config(agent_config)

        assert agent_config, f"agent_config is required."
        assert agent_config.get("name", ""), f"name needs to be in config."

        name = orig_name if orig_name else agent_config["name"]
        default_system_message = agent_config.get("profile", None)
        default_toolkits = agent_config.get("toolkits", [])

        system_message = system_message or default_system_message
        self.toolkits = toolkits or default_toolkits

        name = name.replace(" ", "_").strip()

        super().__init__(
            name, system_message, description=agent_config["description"], **kwargs
        )

        if proxy is not None:
            self.register_proxy(proxy)

    def _preprocess_config(self, config):

        role_prompt, leader_prompt, responsibilities = "", "", ""

        if "responsibilities" in config:
            title = config["title"] if "title" in config else config.get("name", "")
            if "name" not in config:
                config["name"] = config["title"]
            responsibilities = config["responsibilities"]
            responsibilities = (
                "\n".join([f" - {r}" for r in responsibilities])
                if isinstance(responsibilities, list)
                else responsibilities
            )
            role_prompt = role_system_message.format(
                title=title,
                responsibilities=responsibilities,
            )

        name = config.get("name", "")
        description = (
            f"Name: {name}\nResponsibility:\n{responsibilities}"
            if responsibilities
            else f"Name: {name}"
        )
        config["description"] = description.strip()

        if "group_desc" in config:
            group_desc = config["group_desc"]
            leader_prompt = leader_system_message.format(group_desc=group_desc)

        config["profile"] = (
            (role_prompt + "\n\n").strip()
            + (leader_prompt + "\n\n").strip()
            + config.get("profile", "")
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
        self.user_proxy = UserProxyAgent(
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


class SingleAssistantRAG(SingleAssistant):

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
        retrieve_config={},
        rag_description="",
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
        assert retrieve_config, "retrieve config cannot be empty for RAG Agent."
        rag_func, rag_assistant = get_rag_function(retrieve_config, rag_description)
        self.rag_assistant = rag_assistant
        register_function(
            rag_func,
            caller=self.assistant,
            executor=self.user_proxy,
            description=rag_description if rag_description else rag_func.__doc__,
        )

    def reset(self):
        super().reset()
        self.rag_assistant.reset()


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
        agent_configs: List[
            Dict[str, Any] | str | ConversableAgent
        ] = [],  # overwrites previous config
        llm_config: Dict[str, Any] = {},
        user_proxy: UserProxyAgent | None = None,
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
        if user_proxy is None:
            self.user_proxy = UserProxyAgent(
                name="User_Proxy",
                is_termination_msg=is_termination_msg,
                human_input_mode=human_input_mode,
                max_consecutive_auto_reply=max_consecutive_auto_reply,
                code_execution_config=code_execution_config,
                **kwargs,
            )
        else:
            self.user_proxy = user_proxy
        self.agent_configs = agent_configs or group_config.get("agents", [])
        assert self.agent_configs, f"agent_configs is required."
        self.agents = []
        self._init_agents()
        self.representative = self._get_representative()

    def _init_single_agent(self, agent_config):
        if isinstance(agent_config, ConversableAgent):
            return agent_config
        else:
            return FinRobot(
                agent_config,
                llm_config=self.llm_config,
                proxy=self.user_proxy,
            )

    def _init_agents(self):

        agent_dict = defaultdict(list)
        for c in self.agent_configs:
            agent = self._init_single_agent(c)
            agent_dict[agent.name].append(agent)

        # add index indicator for duplicate name/title
        for name, agent_list in agent_dict.items():
            if len(agent_list) == 1:
                self.agents.append(agent_list[0])
                continue
            for idx, agent in enumerate(agent_list):
                agent._name = f"{name}_{idx+1}"
                self.agents.append(agent)

    @abstractmethod
    def _get_representative(self) -> ConversableAgent:
        pass

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
        self.user_proxy.reset()
        self.representative.reset()
        for agent in self.agents:
            agent.reset()


class MultiAssistant(MultiAssistantBase):
    """
    Group Chat Workflow with multiple agents.
    """

    def _get_representative(self):

        def custom_speaker_selection_func(
            last_speaker: autogen.Agent, groupchat: autogen.GroupChat
        ):
            """Define a customized speaker selection function.
            A recommended way is to define a transition for each speaker in the groupchat.

            Returns:
                Return an `Agent` class or a string from ['auto', 'manual', 'random', 'round_robin'] to select a default method to use.
            """
            messages = groupchat.messages
            if len(messages) <= 1:
                return groupchat.agents[0]
            if last_speaker is self.user_proxy:
                return groupchat.agent_by_name(messages[-2]["name"])
            elif "tool_calls" in messages[-1] or messages[-1]["content"].endswith(
                "TERMINATE"
            ):
                return self.user_proxy
            else:
                return groupchat.next_agent(last_speaker, groupchat.agents[:-1])

        self.group_chat = GroupChat(
            self.agents + [self.user_proxy],
            messages=[],
            speaker_selection_method=custom_speaker_selection_func,
            send_introductions=True,
        )
        manager_name = (self.group_config.get("name", "") + "_chat_manager").strip("_")
        manager = GroupChatManager(
            self.group_chat, name=manager_name, llm_config=self.llm_config
        )
        return manager


class MultiAssistantWithLeader(MultiAssistantBase):
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
        need_suffix = (
            len(set([c["title"] for c in self.agent_configs if isinstance(c, dict)]))
            == 1
        )

        group_desc = ""
        for i, c in enumerate(self.agent_configs):
            if isinstance(c, ConversableAgent):
                group_desc += c.description + "\n\n"
            else:
                name = c["title"] if "title" in c else c.get("name", "")
                name = name.replace(" ", "_").strip() + (
                    f"_{i+1}" if need_suffix else ""
                )
                responsibilities = (
                    "\n".join([f" - {r}" for r in c.get("responsibilities", [])]),
                )
                group_desc += f"Name: {name}\nResponsibility:\n{responsibilities}\n\n"

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
