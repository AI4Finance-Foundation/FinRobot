import autogen
from finrobot.agents.workflow import MultiAssistant, MultiAssistantWithLeader
from finrobot.functional import get_rag_function
from finrobot.utils import register_keys_from_json
from textwrap import dedent
from autogen import register_function
from investment_group import group_config
import agentops

# Initialize AgentOps
agentops.init("YOUR_AGENTOPS_API_KEY_HERE")

@agentops.record_function("setup_llm_config")
def setup_llm_config():
    return {
        "config_list": autogen.config_list_from_json(
            "../OAI_CONFIG_LIST",
            filter_dict={
                "model": ["gpt-4-0125-preview"],
            },
        ),
        "cache_seed": 42,
        "temperature": 0,
    }

llm_config = setup_llm_config()

register_keys_from_json("../config_api_keys")

@agentops.track_agent(name="UserProxy")
class EnhancedUserProxy(autogen.UserProxyAgent):
    @agentops.record_function("execute_code")
    def execute_code(self, code, **kwargs):
        return super().execute_code(code, **kwargs)

user_proxy = EnhancedUserProxy(
    name="User",
    human_input_mode="NEVER",
    is_termination_msg=lambda x: x.get("content", "") and "TERMINATE" in x.get("content", ""),
    code_execution_config={
        "last_n_messages": 3,
        "work_dir": "quant",
        "use_docker": False,
    },
)

@agentops.record_function("setup_rag_function")
def setup_rag_function():
    return get_rag_function(
        retrieve_config={
            "task": "qa",
            "docs_path": "https://www.sec.gov/Archives/edgar/data/1737806/000110465923049927/pdd-20221231x20f.htm",
            "chunk_token_size": 1000,
            "collection_name": "pdd2022",
            "get_or_create": True,
        },
    )

rag_func = setup_rag_function()

with_leader_config = {
    "Market Sentiment Analysts": True,
    "Risk Assessment Analysts": True,
    "Fundamental Analysts": True,
}

@agentops.record_function("create_group")
def create_group(group_name, single_group_config, with_leader):
    if with_leader:
        group_members = single_group_config["with_leader"]
        group_members["agents"] = group_members.pop("employees")
        return MultiAssistantWithLeader(
            group_members, llm_config=llm_config, user_proxy=user_proxy
        )
    else:
        group_members = single_group_config["without_leader"]
        group_members["agents"] = group_members.pop("employees")
        return MultiAssistant(
            group_members, llm_config=llm_config, user_proxy=user_proxy
        )

representatives = []

for group_name, single_group_config in group_config["groups"].items():
    with_leader = with_leader_config.get(group_name)
    group = create_group(group_name, single_group_config, with_leader)

    for agent in group.agents:
        register_function(
            rag_func,
            caller=agent,
            executor=group.user_proxy,
            description="retrieve content from PDD's 2022 20-F Sec Filing for QA",
        )

    representatives.append(group.representative)

@agentops.record_function("create_main_group")
def create_main_group():
    cio_config = group_config["CIO"]
    main_group_config = {"leader": cio_config, "agents": representatives}
    return MultiAssistantWithLeader(
        main_group_config, llm_config=llm_config, user_proxy=user_proxy
    )

main_group = create_main_group()

task = dedent(
    """
    Subject: Evaluate Investment Potential and Determine 6-Month Target Price for Pinduoduo (PDD)

    Task Description:

    Today is 2023-04-26. As the Chief Investment Officer, your task is to evaluate the potential investment in Pinduoduo (PDD) based on the newly released 2022 annual report and recent market news. You will need to coordinate with the Market Sentiment Analysts, Risk Assessment Analysts, and Fundamental Analysts to gather and analyze the relevant information. Your final deliverable should include a comprehensive evaluation, a 6-month target price for PDD's stock, and a recommendation on whether to invest in Pinduoduo. 

    Notes:

    All members in your group should be informed:
    - Do not use any data after 2023-04-26, which is cheating.


    Specific Instructions:

    [Coordinate with Market Sentiment Analysts]:
    Task: Analyze recent market sentiment surrounding PDD based on social media, news articles, and investor behavior.
    Deliverable: Provide a sentiment score based on positive and negative mentions in the past few months.
    
    [Coordinate with Risk Assessment Analysts]:
    Task: Assess the financial and operational risks highlighted in PDD's 2022 annual report (Form 20-F).
    Deliverable: Provide a risk score considering factors such as debt levels, liquidity, market volatility, regulatory risks, and any legal proceedings.

    [Coordinate with Fundamental Analysts]:
    Task: Perform a detailed analysis of PDD's financial health based on the 2022 annual report.
    Deliverable: Calculate key financial metrics such as Profit Margin, Return on Assets (ROA), and other relevant ratios.

    [Determine 6-Month Target Price]:
    Task: Based on the integrated analysis from all three groups, calculate a 6-month target price for PDD's stock.
    Considerations: Current stock price, market sentiment, risk assessment, and financial health as indicated in the annual report.

    [Final Deliverable]:
    Integrate Findings: Compile the insights from all three groups to get a holistic view of Pinduoduo's potential.
    Evaluation and 6-Month Target Price: Provide a 6-month target price for PDD's stock and a recommendation on whether to invest in Pinduoduo, including the rationale behind your decision.
    """
)

@agentops.record_function("run_investment_analysis")
def run_investment_analysis():
    main_group.chat(message=task, use_cache=True)

if __name__ == "__main__":
    run_investment_analysis()
    agentops.end_session('Success')