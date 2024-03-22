from config_api_keys import *

import finnhub

import autogen
from autogen.agentchat import register_function
from autogen import AssistantAgent, UserProxyAgent
from autogen.agentchat.contrib.multimodal_conversable_agent import MultimodalConversableAgent
from autogen.cache import Cache

from finnhub_utils import FinnHubUtils
from visual_utils import plot_candlestick_chart

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
    llm_config={"config_list": config_list_4v, "temperature": 0},#, "max_tokens": 300},
    system_message="""
        Your are a Market Analyst. Your task is to analyze the financial data and market news.
        Reply "TERMINATE" in the end when everything is done.
        """
)
data_provider = AssistantAgent(
    name="Data_Provider",
    llm_config={"config_list": config_list_gpt4, "temperature": 0},
    system_message="""
        You are a Data Provider. Your task is to provide data and information for the market analyst.
        Reply "TERMINATE" in the end when everything is done.
        """
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


register_function(
    FinnHubUtils.get_company_news,
    caller=data_provider,
    executor=user_proxy,
    name="get_company_news",
    description="retrieve market news related to designated company",
)

register_function(
    plot_candlestick_chart,
    caller=data_provider,
    executor=user_proxy,
    name="plot_candlestick_chart",
    description="plot stock price chart for a company"
)

groupchat = autogen.GroupChat(agents=[data_provider, market_analyst, user_proxy], messages=[])
manager = autogen.GroupChatManager(groupchat=groupchat, llm_config={"config_list": config_list_gpt4, "temperature": 0})


# company = "Tesla"
company = "APPLE"

with Cache.disk() as cache: # image cannot be cached
    autogen.initiate_chats(
    [
        {
            "sender": user_proxy,
            "recipient": data_provider,
            "message": f"""
                Gather information available upon {get_current_date()} for {company}, 
                including its recent market news and a candlestick chart of the stock 
                price trend. Save the chart as `result.jpg`
                """,
            "clear_history": True,
            "silent": False,
            "summary_method": "last_msg",
        },
        {
            "sender": user_proxy,
            "recipient": market_analyst,
            "message": """
                With the financial charts provided, along with recent market news related 
                to a company, provide a summary of your understanding of its current status 
                and forecast potential stock price fluctuations for next week. Reply 
                TERMINATE when the task is done.
                """,
            "max_turns": 1,  # max number of turns for the conversation 
            "summary_method": "last_msg",
            "carryover": "<img result.jpg>"     # kind of cheated here for stability
        }
    ]
    )