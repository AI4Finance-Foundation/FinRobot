from typing_extensions import Annotated
from config_api_keys import *

import finnhub
import pandas as pd
import yfinance as yf
from collections import defaultdict
from datetime import datetime

import random
import json

import autogen
from autogen import AssistantAgent, UserProxyAgent
from autogen.agentchat.contrib.multimodal_conversable_agent import MultimodalConversableAgent
from autogen.cache import Cache

from utils import get_current_date

config_list_4v = autogen.config_list_from_json(
    "OAI_CONFIG_LIST",
    filter_dict={
        "model": ["gpt-4-vision-preview"],
    },
)
config_list_gpt4 = autogen.config_list_from_json(
    "OAI_CONFIG_LIST",
    filter_dict={
        "model": ["gpt-4"],
    },
)

finnhub_client = finnhub.Client(api_key=FINNHUB_API_KEY)

market_analyst = MultimodalConversableAgent(
    name="Market_Analyst",
    max_consecutive_auto_reply=10,
    system_message="With the financial charts provided, along with recent financial reports and market news related to a company, provide a summary of your understanding of its current status and forecast potential stock price fluctuations for next week. Reply TERMINATE when the task is done.",
    llm_config={"config_list": config_list_4v, "temperature": 0}#, "max_tokens": 300},
)
data_provider = AssistantAgent(
    name="Data_Provider",
    system_message="Your task is to collect necessary financial data and aggregate them based on client's requirement with the functions you have been provided with. For stock price, plot charts visualizing the recent trend and save the figure in `result.jpg` file by programming. Tell other agents it is in the <img result.jpg> file. Reply ALL DONE when all data processes are done.",
    llm_config={"config_list": config_list_gpt4, "temperature": 0}
)

user_proxy = UserProxyAgent(
    name="User_proxy",
    human_input_mode="NEVER", 
    max_consecutive_auto_reply=10,
    is_termination_msg=lambda x: x.get("content", "") and x.get("content", "").rstrip().rstrip(".").endswith("TERMINATE"),
    code_execution_config={
        "work_dir": "coding",
        "use_docker": False
    },  # Please set use_docker=True if docker is available to run the generated code. Using docker is safer than running the generated code directly.
)



from autogen import Agent
from typing import List, Dict


def custom_speaker_selection_func(last_speaker: Agent, groupchat: autogen.GroupChat):
    """Define a customized speaker selection function.
    A recommended way is to define a transition for each speaker in the groupchat.

    Returns:
        Return an `Agent` class or a string from ['auto', 'manual', 'random', 'round_robin'] to select a default method to use.
    """
    messages = groupchat.messages

    if len(messages) <= 1:
        return data_provider

    if last_speaker is user_proxy:
        return data_provider
    elif last_speaker is data_provider:
        if "ALL DONE" in messages[-1]["content"]:
            return market_analyst
        else:
            return "auto"
    
    else:
        return "auto"
    # elif last_speaker is engineer:
    #     if "```python" in messages[-1]["content"]:
    #         # If the last message is a python code block, let the executor to speak
    #         return executor
    #     else:
    #         # Otherwise, let the engineer to continue
    #         return engineer

    # elif last_speaker is executor:
    #     if "exitcode: 1" in messages[-1]["content"]:
    #         # If the last message indicates an error, let the engineer to improve the code
    #         return engineer
    #     else:
    #         # Otherwise, let the scientist to speak
    #         return scientist

    # elif last_speaker is scientist:
    #     # Always let the user to speak after the scientist
    #     return user_proxy

    # else:
    #     return "random"
    

groupchat = autogen.GroupChat(agents=[data_provider, market_analyst, user_proxy], messages=[], speaker_selection_method=custom_speaker_selection_func)#, max_round=20)
manager = autogen.GroupChatManager(groupchat=groupchat, llm_config={"config_list": config_list_gpt4, "temperature": 0})


# company = "Tesla"
company = "APPLE"

with Cache.disk() as cache:
    user_proxy.initiate_chat(
        manager,
        message=f"Gather all the information available upon {get_current_date()} for {company}, then analyze the positive developments and potential concerns. "
                "Come up with 2-4 most important factors respectively and concisely. "
                f"Then make a rough prediction (e.g. up/down by 2-3%) of the {company} stock price movement for next week. Provide a summary analysis to support your prediction.",
    )