import autogen
from finrobot.agents.workflow import MultiAssistant, MultiAssistantWithLeader
from finrobot.functional import get_rag_function
from finrobot.utils import register_keys_from_json
from textwrap import dedent
from autogen import register_function
from investment_group import group_config


llm_config = {
    "config_list": autogen.config_list_from_json(
        "../OAI_CONFIG_LIST",
        filter_dict={
            "model": ["gpt-4-0125-preview"],
        },
    ),
    "cache_seed": 42,
    "temperature": 0,
}

register_keys_from_json("../config_api_keys")

# group_config = json.load(open("investment_group.json"))

user_proxy = autogen.UserProxyAgent(
    name="User",
    # human_input_mode="ALWAYS",
    human_input_mode="NEVER",
    is_termination_msg=lambda x: x.get("content", "")
    and "TERMINATE" in x.get("content", ""),
    code_execution_config={
        "last_n_messages": 3,
        "work_dir": "quant",
        "use_docker": False,
    },
)

rag_func = get_rag_function(
    retrieve_config={
        "task": "qa",
        "docs_path": "https://www.sec.gov/Archives/edgar/data/1737806/000110465923049927/pdd-20221231x20f.htm",
        "chunk_token_size": 1000,
        "collection_name": "pdd2022",
        "get_or_create": True,
    },
)

with_leader_config = {
    "Market Sentiment Analysts": True,
    "Risk Assessment Analysts": True,
    "Fundamental Analysts": True,
}

representatives = []

for group_name, single_group_config in group_config["groups"].items():

    with_leader = with_leader_config.get(group_name)
    if with_leader:
        group_members = single_group_config["with_leader"]
        group_members["agents"] = group_members.pop("employees")
        group = MultiAssistantWithLeader(
            group_members, llm_config=llm_config, user_proxy=user_proxy
        )
    else:
        group_members = single_group_config["without_leader"]
        group_members["agents"] = group_members.pop("employees")
        group = MultiAssistant(
            group_members, llm_config=llm_config, user_proxy=user_proxy
        )

    for agent in group.agents:
        register_function(
            rag_func,
            caller=agent,
            executor=group.user_proxy,
            description="retrieve content from PDD's 2022 20-F Sec Filing for QA",
        )

    representatives.append(group.representative)


cio_config = group_config["CIO"]
main_group_config = {"leader": cio_config, "agents": representatives}
main_group = MultiAssistantWithLeader(
    main_group_config, llm_config=llm_config, user_proxy=user_proxy
)

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

# task = dedent(
#     """
#     As the Chief Investment Officer, your task is to evaluate the potential investment in Company ABC based on the provided data. You will need to coordinate with the Market Sentiment Analysts, Risk Assessment Analysts, and Fundamental Analysts to gather and analyze the relevant information. Your final deliverable should include a comprehensive evaluation and a recommendation on whether to invest in Company ABC.

#     Specific Instructions:

#     Coordinate with Market Sentiment Analysts:

#     Task: Calculate the sentiment score based on the provided market sentiment data.
#     Data: Positive mentions (80), Negative mentions (20)
#     Formula: Sentiment Score = (Positive Mentions - Negative Mentions) / Total Mentions
#     Expected Output: Sentiment Score (percentage)

#     Coordinate with Risk Assessment Analysts:

#     Task: Calculate the risk score using the provided financial ratios.
#     Data:
#     Debt-to-Equity Ratio: 1.5
#     Current Ratio: 2.0
#     Return on Equity (ROE): 0.1 (10%)
#     Weights: Debt-to-Equity (0.5), Current Ratio (0.3), ROE (0.2)
#     Formula: Risk Score = 0.5 * Debt-to-Equity + 0.3 * (1 / Current Ratio) - 0.2 * ROE
#     Expected Output: Risk Score

#     Coordinate with Fundamental Analysts:

#     Task: Calculate the Profit Margin and Return on Assets (ROA) based on the provided financial data.
#     Data:
#     Revenue: $1,000,000
#     Net Income: $100,000
#     Total Assets: $500,000
#     Formulas:
#     Profit Margin = (Net Income / Revenue) * 100
#     ROA = (Net Income / Total Assets) * 100
#     Expected Outputs: Profit Margin (percentage) and ROA (percentage)

#     Final Deliverable:
#     Integrate Findings: Compile the insights from all three groups to get a holistic view of Company ABC's potential.
#     Evaluation and Recommendation: Based on the integrated analysis, provide a recommendation on whether to invest in Company ABC, including the rationale behind your decision.
# """
# )

main_group.chat(message=task, use_cache=True)
