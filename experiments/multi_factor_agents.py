import re
import json
import autogen
from autogen.cache import Cache

# from finrobot.utils import create_inner_assistant

from functools import partial


config_list_gpt4 = autogen.config_list_from_json(
    "OAI_CONFIG_LIST",
    filter_dict={
        "model": ["gpt-4-0125-preview"],
    },
)

llm_config = {
    "config_list": config_list_gpt4,
    "cache_seed": 42,
    "temperature": 0,
}

quant_group_config = json.load(open("quantitative_investment_group_config.json"))

# user_proxy = autogen.UserProxyAgent(
#     name="User",
#     # human_input_mode="ALWAYS",
#     human_input_mode="NEVER",
#     code_execution_config=False
# )

group_descs = "\n\n".join(
    [
        "Name: {} \nResponsibility: {}".format(c["name"], c["profile"])
        for c in quant_group_config
    ]
)

group_leader = autogen.AssistantAgent(
    name="Group_Leader",
    system_message="""
    As a group leader, you are responsible for coordinating the team's efforts to achieve the project's objectives. 
    You must ensure that the team is working together effectively and efficiently. 
    Summarize the status of the whole project progess every time you respond, and assign task to one of the group members to progress the project. 
    Orders should follow the format: \"[<name of staff>] <order>\" and appear at the end of your response.
    After receiving feedback from the team members, check the progress of the task, and make sure the task is well completed before proceding to th next order.
    If the task is not well completed, your order should be to provide assistance and guidance for the team members to complete it again.
    Reply TERMINATE only when the whole project is done. Your team members are as follows:\n\n
    """
    + group_descs,
    llm_config=llm_config,
)

executor = autogen.UserProxyAgent(
    name="Executor",
    human_input_mode="NEVER",
    # human_input_mode="ALWAYS",
    is_termination_msg=lambda x: x.get("content", "")
    and "TERMINATE" in x.get("content", ""),
    # max_consecutive_auto_reply=3,
    code_execution_config={
        "last_n_messages": 3,
        "work_dir": "quant",
        "use_docker": False,
    },
)

quant_group = {
    c["name"]: autogen.agentchat.AssistantAgent(
        name=c["name"],
        system_message=c["profile"],
        llm_config=llm_config,
    )
    for c in quant_group_config
}


def order_trigger(pattern, sender):
    # print(pattern)
    # print(sender.last_message()['content'])
    return pattern in sender.last_message()["content"]


def order_message(pattern, recipient, messages, sender, config):
    full_order = recipient.chat_messages_for_summary(sender)[-1]["content"]
    pattern = rf"\[{pattern}\](?::)?\s*(.+?)(?=\n\[|$)"
    match = re.search(pattern, full_order, re.DOTALL)
    if match:
        order = match.group(1).strip()
    else:
        order = full_order
    return f"""
    Follow leader's order and complete the following task: {order}.
    For coding tasks, provide python scripts and executor will run it for you.
    Save your results or any intermediate data locally and let group leader know how to read them.
    DO NOT include TERMINATE in your response until you have received the results from the execution of the Python scripts.
    If the task cannot be done currently or need assistance from other members, report the reasons or requirements to group leader ended with TERMINATE. 
    """
    # For coding tasks, only use the functions you have been provided with.


for name, agent in quant_group.items():
    executor.register_nested_chats(
        [
            {
                "sender": executor,
                "recipient": agent,
                "message": partial(order_message, name),
                "summary_method": "reflection_with_llm",
                "max_turns": 10,
                "max_consecutive_auto_reply": 3,
            }
        ],
        trigger=partial(order_trigger, f"[{name}]"),
    )

quant_task = "Develop and test the feasibility of a quantitative investment strategy focusing on the Dow Jones 30 stocks, utilizing your multi-factor analysis expertise to identify potential investment opportunities and optimize the portfolio's performance. Ensure the strategy is robust, data-driven, and aligns with our risk management principles."

with Cache.disk() as cache:
    executor.initiate_chat(group_leader, message=quant_task, cache=cache)
