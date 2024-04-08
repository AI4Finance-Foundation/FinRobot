
# from IPython import get_ipython

from typing import Any, Callable, Dict, List, Literal
import autogen
from autogen.cache import Cache
from autogen.agentchat import register_function

from finrobot.utils import get_current_date
from finrobot.data_source.finnhub_utils import FinnHubUtils


def data_agent():
    agent = autogen.AssistantAgent(
        name="Financial_Data_Downloader",
        system_message="""
            As a Financial Data Downloader, you are responsible for collecting and aggregating financial data based on client's requirement. 
            For coding tasks, only use the functions you have been provided with. Reply TERMINATE when the task is done.
            """,
        llm_config=llm_config,
    )


class DataAgent:

    def __init__(self, name: str, 
                 system_message: str | List | None = ...,
                 llm_config: Dict | None | Literal[False] = None, 
                 is_termination_msg: Callable[[Dict], bool] | None = None, 
                 max_consecutive_auto_reply: int | None = None, 
                 human_input_mode: Literal['ALWAYS'] | Literal['TERMINATE'] | Literal['NEVER'] = "ALWAYS", 
                 code_execution_config: Dict | Literal[False] = ..., 
                 default_auto_reply: str | Dict | None = "", 
                 description: str | None = None):
        self.agent = autogen.AssistantAgent(
            name, system_message, llm_config, is_termination_msg, max_consecutive_auto_reply, "NEVER", description)         
        self.executor = autogen.UserProxyAgent(
            name=name, max_consecutive_auto_reply=max_consecutive_auto_reply,
            human_input_mode=human_input_mode, code_execution_config, default_auto_reply, llm_config=False, system_message, description)


    def __init__(self, name: str, system_message: str | None = ..., 
                 llm_config: Dict | None | Literal[False] = None, 
                 is_termination_msg: Callable[[Dict], bool] | None = None, 
                 max_consecutive_auto_reply: int | None = None, 
                 human_input_mode: str | None = "NEVER", 
                 description: str | None = None, **kwargs):
        super().__init__(name, system_message, llm_config, is_termination_msg, max_consecutive_auto_reply, human_input_mode, description, **kwargs)

    def register_tools(self, user_proxy: autogen.UserProxyAgent):

        user_proxy.register_for_execution(
            self.register_for_llm(
                FinnHubUtils.get_company_profile,
                name="get_company_profile",
                description="get a company's profile information",
            )
        )

