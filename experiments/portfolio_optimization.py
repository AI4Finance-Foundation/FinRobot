import re
import json
import autogen
from autogen.cache import Cache
from finrobot.agents.workflow import MultiAssistant, MultiAssistantWithLeader
from textwrap import dedent


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


group_config = json.load(open("investment_group.json"))

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

    representatives.append(group.representative)


cio_config = group_config["CIO"]
main_group_config = {"leader": cio_config, "agents": representatives}
main_group = MultiAssistantWithLeader(
    main_group_config, llm_config=llm_config, user_proxy=user_proxy
)

task = dedent(
    """
    As the Chief Investment Officer, your task is to optimize our current investment portfolio based on the latest annual reports. This will involve coordinating with the Market Sentiment Analysts, Risk Assessment Analysts, and Fundamental Analysts to gather and analyze the relevant data. The goal is to ensure our portfolio is well-positioned for growth while managing risks effectively.

    Specific Steps:

    [Review New Annual Reports]:
    Collect the latest annual reports from companies within our portfolio and potential new investments.

    [Coordinate with Market Sentiment Analysts]:
    Task: Analyze the market sentiment for these companies based on recent trends and news.
    Deliverable: Provide a comprehensive report on market sentiment and investor behavior for each company.

    [Coordinate with Risk Assessment Analysts]:
    Task: Evaluate the risks associated with each company and their sectors.
    Deliverable: Develop a risk assessment report highlighting potential risks and proposed mitigation strategies.

    [Coordinate with Fundamental Analysts]:
    Task: Perform a detailed financial analysis of each company, including key financial metrics, trends, and forecasts.
    Deliverable: Provide a summary of financial health and growth prospects for each company.
    
    [Integrate Findings]:
    Combine insights from all three groups to get a holistic view of each company’s potential.
    Evaluate how these insights impact our current portfolio and identify any necessary adjustments.
    
    [Optimize Portfolio]:
    Based on the integrated analysis, recommend adjustments to the portfolio.
    Ensure the portfolio is balanced, with an optimal mix of high-growth, stable, and low-risk investments.

    [Report and Implement]:
    Present your final recommendations and the rationale behind them.
    Oversee the implementation of the approved portfolio adjustments.

    [Expected Outcome]:
    A revised portfolio that leverages the latest financial insights and market sentiment to maximize growth and manage risks effectively.

    If you have any questions or need additional resources, please let me know.
"""
)

task = dedent(
    """
    As the Chief Investment Officer, your task is to evaluate the potential investment in Company ABC based on the provided data. You will need to coordinate with the Market Sentiment Analysts, Risk Assessment Analysts, and Fundamental Analysts to gather and analyze the relevant information. Your final deliverable should include a comprehensive evaluation and a recommendation on whether to invest in Company ABC.

    Specific Instructions:
    
    Coordinate with Market Sentiment Analysts:

    Task: Calculate the sentiment score based on the provided market sentiment data.
    Data: Positive mentions (80), Negative mentions (20)
    Formula: Sentiment Score = (Positive Mentions - Negative Mentions) / Total Mentions
    Expected Output: Sentiment Score (percentage)
    
    Coordinate with Risk Assessment Analysts:

    Task: Calculate the risk score using the provided financial ratios.
    Data:
    Debt-to-Equity Ratio: 1.5
    Current Ratio: 2.0
    Return on Equity (ROE): 0.1 (10%)
    Weights: Debt-to-Equity (0.5), Current Ratio (0.3), ROE (0.2)
    Formula: Risk Score = 0.5 * Debt-to-Equity + 0.3 * (1 / Current Ratio) - 0.2 * ROE
    Expected Output: Risk Score

    Coordinate with Fundamental Analysts:

    Task: Calculate the Profit Margin and Return on Assets (ROA) based on the provided financial data.
    Data:
    Revenue: $1,000,000
    Net Income: $100,000
    Total Assets: $500,000
    Formulas:
    Profit Margin = (Net Income / Revenue) * 100
    ROA = (Net Income / Total Assets) * 100
    Expected Outputs: Profit Margin (percentage) and ROA (percentage)
    
    Final Deliverable:
    Integrate Findings: Compile the insights from all three groups to get a holistic view of Company ABC's potential.
    Evaluation and Recommendation: Based on the integrated analysis, provide a recommendation on whether to invest in Company ABC, including the rationale behind your decision.
"""
)

main_group.chat(message=task, use_cache=True)
