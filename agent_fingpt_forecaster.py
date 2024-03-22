# from IPython import get_ipython

import autogen
from autogen.cache import Cache
from autogen.agentchat import register_function

from utils import get_current_date
from finnhub_utils import FinnHubUtils

config_list = autogen.config_list_from_json(
    "OAI_CONFIG_LIST",
    filter_dict={
        "model": ["gpt-4"],# "gpt-3.5-turbo", "gpt-3.5-turbo-16k"],
    },
)
llm_config = {
    "config_list": config_list,
    "timeout": 120,
    "temperature": 0
}
analyst = autogen.AssistantAgent(
    name="Market_Analyst",
    system_message="As a Market Analyst, one must possess strong analytical and problem-solving abilities, collect necessary financial information and aggregate them based on client's requirement."
        "For coding tasks, only use the functions you have been provided with. Reply TERMINATE when the task is done.",
    llm_config=llm_config,
)

# create a UserProxyAgent instance named "user_proxy"
user_proxy = autogen.UserProxyAgent(
    name="User_Proxy",
    is_termination_msg=lambda x: x.get("content", "") and x.get("content", "").rstrip().rstrip(".").endswith("TERMINATE"),
    human_input_mode="NEVER",
    max_consecutive_auto_reply=10,
    code_execution_config={
        "work_dir": "coding",
        "use_docker": False,
    },  # Please set use_docker=True if docker is available to run the generated code. Using docker is safer than running the generated code directly.
)

register_function(
    FinnHubUtils.get_company_profile,
    caller=analyst,
    executor=user_proxy,
    name="get_company_profile",
    description="get a company's profile information",
)

register_function(
    FinnHubUtils.get_company_news,
    caller=analyst,
    executor=user_proxy,
    name="get_company_news",
    description="retrieve market news related to designated company",
)

register_function(
    FinnHubUtils.get_financial_basics,
    caller=analyst,
    executor=user_proxy,
    name="get_financial_basics",
    description="get latest financial basics for a designated company",
)

register_function(
    FinnHubUtils.get_stock_data,
    caller=analyst,
    executor=user_proxy,
    name="get_stock_data",
    description="retrieve stock price data for designated ticker symbol",
)

# company = "Tesla"
company = "APPLE"

with Cache.disk() as cache:
    # start the conversation
    user_proxy.initiate_chat(
        analyst,
        message=f"Based on all the information available upon {get_current_date()}, let's first analyze the positive developments and potential concerns for {company}. "
            "Come up with 2-4 most important factors respectively and keep them concise. Most factors should be inferred from company related news. "
            f"Then make a rough prediction (e.g. up/down by 2-3%) of the {company} stock price movement for next week. Provide a summary analysis to support your prediction.",
        cache=cache,
    )