import os
import autogen
from autogen.agentchat.contrib.agent_builder import AgentBuilder
from finrobot.utils import get_current_date
import agentops

# Initialize AgentOps
agentops.init('<INSERT YOUR API KEY HERE>')

config_file_or_env = "OAI_CONFIG_LIST"
llm_config = {"temperature": 0}

@agentops.track_agent(name='AgentBuilder')
class TrackedAgentBuilder(AgentBuilder):
    pass

builder = TrackedAgentBuilder(
    config_file_or_env=config_file_or_env,
    builder_model="gpt-4-0125-preview",
    agent_model="gpt-4-0125-preview",
)

config_list = autogen.config_list_from_json(
    config_file_or_env, filter_dict={"model": ["gpt-4-0125-preview"]}
)

building_task = "Gather information like company profile, recent stock price fluctuations, market news, and financial basics of a specified company (e.g. AAPL) by programming and analyze its current positive developments and potential concerns. Based on all the information, come up with a rough estimate (e.g. up by 2-3%) and give a summary of the reasons for next week's stock price. Each python program should execute on its own, and avoid plotting any chart."
config_path = "configs/save_config_forecaster.json"

if os.path.exists(config_path):
    agent_list, agent_config = builder.load(config_path)
else:
    agent_list, agent_configs = builder.build(
        building_task,
        llm_config,
        coding=True,
        code_execution_config={
            "work_dir": "coding",
            "use_docker": False,
        },
    )
    builder.save(config_path)

@agentops.track_agent(name='GroupChat')
class TrackedGroupChat(autogen.GroupChat):
    pass

@agentops.track_agent(name='GroupChatManager')
class TrackedGroupChatManager(autogen.GroupChatManager):
    pass

group_chat = TrackedGroupChat(agents=agent_list, messages=[], max_round=20)
manager = TrackedGroupChatManager(
    groupchat=group_chat, llm_config={"config_list": config_list, **llm_config}
)

@agentops.record_function('initiate_chat')
def initiate_chat(agent, manager, message):
    agent.initiate_chat(
        manager,
        message=message,
    )

initiate_chat(
    agent_list[0],
    manager,
    message=f"Today is {get_current_date()}, predict next week's stock price for Nvidia with its recent market news and stock price movements."
)

# End of program
agentops.end_session('Success')
