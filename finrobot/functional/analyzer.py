import os
from textwrap import dedent
from typing import Annotated
from datetime import timedelta, datetime
from ..data_source import YFinanceUtils, SECUtils, FMPUtils


def combine_prompt(instruction, resource, table_str=None):
    if table_str:
        prompt = f"{table_str}\n\nResource: {resource}\n\nInstruction: {instruction}"
    else:
        prompt = f"Resource: {resource}\n\nInstruction: {instruction}"
    return prompt


def save_to_file(data: str, file_path: str):
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    with open(file_path, "w") as f:
        f.write(data)


class ReportAnalysisUtils:

    def analyze_income_stmt(
        ticker_symbol: Annotated[str, "ticker symbol"],
        fyear: Annotated[str, "fiscal year of the 10-K report"],
        save_path: Annotated[str, "txt file path, to which the returned instruction & resources are written."]
    ) -> str:
        """
        Retrieve the income statement for the given ticker symbol with the related section of its 10-K report.
        Then return with an instruction on how to analyze the income statement.
        """
        # Retrieve the income statement
        income_stmt = YFinanceUtils.get_income_stmt(ticker_symbol)
        df_string = "Income statement:\n" + income_stmt.to_string().strip()

        # Analysis instruction
        instruction = dedent(
            """
            Conduct a comprehensive analysis of the company's income statement for the current fiscal year. 
            Start with an overall revenue record, including Year-over-Year or Quarter-over-Quarter comparisons, 
            and break down revenue sources to identify primary contributors and trends. Examine the Cost of 
            Goods Sold for potential cost control issues. Review profit margins such as gross, operating, 
            and net profit margins to evaluate cost efficiency, operational effectiveness, and overall profitability. 
            Analyze Earnings Per Share to understand investor perspectives. Compare these metrics with historical 
            data and industry or competitor benchmarks to identify growth patterns, profitability trends, and 
            operational challenges. The output should be a strategic overview of the company’s financial health 
            in a single paragraph, less than 130 words, summarizing the previous analysis into 4-5 key points under 
            respective subheadings with specific discussion and strong data support.
            """
        )

        # Retrieve the related section from the 10-K report
        section_text = SECUtils.get_10k_section(ticker_symbol, fyear, 7)

        # Combine the instruction, section text, and income statement
        prompt = combine_prompt(instruction, section_text, df_string)

        save_to_file(prompt, save_path)
        return f"instruction & resources saved to {save_path}"

    def analyze_balance_sheet(
        ticker_symbol: Annotated[str, "ticker symbol"],
        fyear: Annotated[str, "fiscal year of the 10-K report"],
        save_path: Annotated[str, "txt file path, to which the returned instruction & resources are written."]
    ) -> str:
        """
        Retrieve the balance sheet for the given ticker symbol with the related section of its 10-K report.
        Then return with an instruction on how to analyze the balance sheet.
        """
        balance_sheet = YFinanceUtils.get_balance_sheet(ticker_symbol)
        df_string = "Balance sheet:\n" + balance_sheet.to_string().strip()

        instruction = dedent(
            """
            Delve into a detailed scrutiny of the company's balance sheet for the most recent fiscal year, pinpointing 
            the structure of assets, liabilities, and shareholders' equity to decode the firm's financial stability and 
            operational efficiency. Focus on evaluating the liquidity through current assets versus current liabilities, 
            the solvency via long-term debt ratios, and the equity position to gauge long-term investment potential. 
            Contrast these metrics with previous years' data to highlight financial trends, improvements, or deteriorations. 
            Finalize with a strategic assessment of the company's financial leverage, asset management, and capital structure, 
            providing insights into its fiscal health and future prospects in a single paragraph. Less than 130 words.
            """
        )

        section_text = SECUtils.get_10k_section(ticker_symbol, fyear, 7)
        prompt = combine_prompt(instruction, section_text, df_string)
        save_to_file(prompt, save_path)
        return f"instruction & resources saved to {save_path}"

    def analyze_cash_flow(
        ticker_symbol: Annotated[str, "ticker symbol"],
        fyear: Annotated[str, "fiscal year of the 10-K report"],
        save_path: Annotated[str, "txt file path, to which the returned instruction & resources are written."]
    ) -> str:
        """
        Retrieve the cash flow statement for the given ticker symbol with the related section of its 10-K report.
        Then return with an instruction on how to analyze the cash flow statement.
        """
        cash_flow = YFinanceUtils.get_cash_flow(ticker_symbol)
        df_string = "Cash flow statement:\n" + cash_flow.to_string().strip()

        instruction = dedent(
            """
            Dive into a comprehensive evaluation of the company's cash flow for the latest fiscal year, focusing on cash inflows 
            and outflows across operating, investing, and financing activities. Examine the operational cash flow to assess the 
            core business profitability, scrutinize investing activities for insights into capital expenditures and investments, 
            and review financing activities to understand debt, equity movements, and dividend policies. Compare these cash movements 
            to prior periods to discern trends, sustainability, and liquidity risks. Conclude with an informed analysis of the company's 
            cash management effectiveness, liquidity position, and potential for future growth or financial challenges in a single paragraph. 
            Less than 130 words.
            """
        )

        section_text = SECUtils.get_10k_section(ticker_symbol, fyear, 7)
        prompt = combine_prompt(instruction, section_text, df_string)
        save_to_file(prompt, save_path)
        return f"instruction & resources saved to {save_path}"

    def analyze_segment_stmt(
        ticker_symbol: Annotated[str, "ticker symbol"],
        fyear: Annotated[str, "fiscal year of the 10-K report"],
        save_path: Annotated[str, "txt file path, to which the returned instruction & resources are written."]
    ) -> str:
        """
        Retrieve the income statement and the related section of its 10-K report for the given ticker symbol.
        Then return with an instruction on how to create a segment analysis.
        """
        income_stmt = YFinanceUtils.get_income_stmt(ticker_symbol)
        df_string = (
            "Income statement (Segment Analysis):\n" + income_stmt.to_string().strip()
        )

        instruction = dedent(
            """
            Identify the company's business segments and create a segment analysis using the Management's Discussion and Analysis 
            and the income statement, subdivided by segment with clear headings. Address revenue and net profit with specific data, 
            and calculate the changes. Detail strategic partnerships and their impacts, including details like the companies or organizations. 
            Describe product innovations and their effects on income growth. Quantify market share and its changes, or state market position 
            and its changes. Analyze market dynamics and profit challenges, noting any effects from national policy changes. Include the cost side, 
            detailing operational costs, innovation investments, and expenses from channel expansion, etc. Support each statement with evidence, 
            keeping each segment analysis concise and under 60 words, accurately sourcing information. For each segment, consolidate the most 
            significant findings into one clear, concise paragraph, excluding less critical or vaguely described aspects to ensure clarity and 
            reliance on evidence-backed information. For each segment, the output should be one single paragraph within 150 words.
            """
        )
        section_text = SECUtils.get_10k_section(ticker_symbol, fyear, 7)
        prompt = combine_prompt(instruction, section_text, df_string)
        save_to_file(prompt, save_path)
        return f"instruction & resources saved to {save_path}"

    def income_summarization(
        ticker_symbol: Annotated[str, "ticker symbol"],
        fyear: Annotated[str, "fiscal year of the 10-K report"],
        income_stmt_analysis: Annotated[str, "in-depth income statement analysis"],
        segment_analysis: Annotated[str, "in-depth segment analysis"],
        save_path: Annotated[str, "txt file path, to which the returned instruction & resources are written."]
    ) -> str:
        """
        With the income statement and segment analysis for the given ticker symbol.
        Then return with an instruction on how to synthesize these analyses into a single coherent paragraph.
        """
        # income_stmt_analysis = analyze_income_stmt(ticker_symbol)
        # segment_analysis = analyze_segment_stmt(ticker_symbol)

        instruction = dedent(
            f"""
            Income statement analysis: {income_stmt_analysis},
            Segment analysis: {segment_analysis},
            Synthesize the findings from the in-depth income statement analysis and segment analysis into a single, coherent paragraph. 
            It should be fact-based and data-driven. First, present and assess overall revenue and profit situation, noting significant 
            trends and changes. Second, examine the performance of the various business segments, with an emphasis on their revenue and 
            profit changes, revenue contributions and market dynamics. For information not covered in the first two areas, identify and 
            integrate key findings related to operation, potential risks and strategic opportunities for growth and stability into the analysis. 
            For each part, integrate historical data comparisons and provide relevant facts, metrics or data as evidence. The entire synthesis 
            should be presented as a continuous paragraph without the use of bullet points. Use subtitles and numbering for each key point. 
            The total output should be less than 160 words.
            """
        )

        section_text = SECUtils.get_10k_section(ticker_symbol, fyear, 7)
        prompt = combine_prompt(instruction, section_text, "")
        save_to_file(prompt, save_path)
        return f"instruction & resources saved to {save_path}"

    def get_risk_assessment(
        ticker_symbol: Annotated[str, "ticker symbol"],
        fyear: Annotated[str, "fiscal year of the 10-K report"],
        save_path: Annotated[str, "txt file path, to which the returned instruction & resources are written."]
    ) -> str:
        """
        Retrieve the risk factors for the given ticker symbol with the related section of its 10-K report.
        Then return with an instruction on how to summarize the top 3 key risks of the company.
        """
        company_name = YFinanceUtils.get_stock_info(ticker_symbol)["shortName"]
        risk_factors = SECUtils.get_10k_section(ticker_symbol, fyear, "1A")
        section_text = (
            "Company Name: "
            + company_name
            + "\n\n"
            + "Risk factors:\n"
            + risk_factors
            + "\n\n"
        )
        instruction = "According to the given information, summarize the top 3 key risks of the company. Less than 100 words."
        prompt = combine_prompt(instruction, section_text, "")
        save_to_file(prompt, save_path)
        return f"instruction & resources saved to {save_path}"

    def analyze_business_highlights(
        ticker_symbol: Annotated[str, "ticker symbol"],
        fyear: Annotated[str, "fiscal year of the 10-K report"],
        save_path: Annotated[str, "txt file path, to which the returned instruction & resources are written."]
    ) -> str:
        """
        Retrieve the business summary and related section of its 10-K report for the given ticker symbol.
        Then return with an instruction on how to describe the performance highlights per business of the company.
        """
        business_summary = SECUtils.get_10k_section(ticker_symbol, fyear, 1)
        section_7 = SECUtils.get_10k_section(ticker_symbol, fyear, 7)
        section_text = (
            "Business summary:\n"
            + business_summary
            + "\n\n"
            + "Management's Discussion and Analysis of Financial Condition and Results of Operations:\n"
            + section_7
        )
        instruction = dedent(
            """
            According to the given information, describe the performance highlights per business of the company. 
            Each business description should contain one sentence of a summarization and one sentence of explanation. 
            Less than 130 words.
            """
        )
        prompt = combine_prompt(instruction, section_text, "")
        save_to_file(prompt, save_path)
        return f"instruction & resources saved to {save_path}"

    def analyze_company_description(
        ticker_symbol: Annotated[str, "ticker symbol"],
        fyear: Annotated[str, "fiscal year of the 10-K report"],
        save_path: Annotated[str, "txt file path, to which the returned instruction & resources are written."]
    ) -> str:
        """
        Retrieve the company description and related sections of its 10-K report for the given ticker symbol.
        Then return with an instruction on how to describe the company's industry, strengths, trends, and strategic initiatives.
        """
        company_name = YFinanceUtils.get_stock_info(ticker_symbol).get(
            "shortName", "N/A"
        )
        business_summary = SECUtils.get_10k_section(ticker_symbol, fyear, 1)
        section_7 = SECUtils.get_10k_section(ticker_symbol, fyear, 7)
        section_text = (
            "Company Name: "
            + company_name
            + "\n\n"
            + "Business summary:\n"
            + business_summary
            + "\n\n"
            + "Management's Discussion and Analysis of Financial Condition and Results of Operations:\n"
            + section_7
        )
        instruction = dedent(
            """
            According to the given information, 
            1. Briefly describe the company’s industry,
            2. Highlight core strengths and competitive advantages key products or services,
            3. Identify current industry trends, opportunities, and challenges that influence the company’s strategy,
            4. Outline recent strategic initiatives such as product launches, acquisitions, or new partnerships, and describe the company's response to market conditions. 
            Less than 400 words.
            """
        )
        step_prompt = combine_prompt(instruction, section_text, "")
        instruction2 = "Summarize the analysis, less than 130 words."
        prompt = combine_prompt(instruction=instruction2, resource=step_prompt)
        save_to_file(prompt, save_path)
        return f"instruction & resources saved to {save_path}"

    def get_key_data(
        ticker_symbol: Annotated[str, "ticker symbol"],
        filing_date: Annotated[
            str | datetime, "the filing date of the financial report being analyzed"
        ],
    ) -> dict:
        """
        return key financial data used in annual report for the given ticker symbol and filing date
        """

        if not isinstance(filing_date, datetime):
            filing_date = datetime.strptime(filing_date, "%Y-%m-%d")

        # Fetch historical market data for the past 6 months
        start = (filing_date - timedelta(weeks=52)).strftime("%Y-%m-%d")
        end = filing_date.strftime("%Y-%m-%d")

        hist = YFinanceUtils.get_stock_data(ticker_symbol, start, end)

        # 获取其他相关信息
        info = YFinanceUtils.get_stock_info(ticker_symbol)
        close_price = hist["Close"].iloc[-1]

        # Calculate the average daily trading volume
        six_months_start = (filing_date - timedelta(weeks=26)).strftime("%Y-%m-%d")
        hist_last_6_months = hist[
            (hist.index >= six_months_start) & (hist.index <= end)
        ]

        # 计算这6个月的平均每日交易量
        avg_daily_volume_6m = (
            hist_last_6_months["Volume"].mean()
            if not hist_last_6_months["Volume"].empty
            else 0
        )

        fiftyTwoWeekLow = hist["High"].min()
        fiftyTwoWeekHigh = hist["Low"].max()

        # avg_daily_volume_6m = hist['Volume'].mean()

        # convert back to str for function calling
        filing_date = filing_date.strftime("%Y-%m-%d")

        # Print the result
        # print(f"Over the past 6 months, the average daily trading volume for {ticker_symbol} was: {avg_daily_volume_6m:.2f}")
        rating, _ = YFinanceUtils.get_analyst_recommendations(ticker_symbol)
        target_price = FMPUtils.get_target_price(ticker_symbol, filing_date)
        result = {
            "Rating": rating,
            "Target Price": target_price,
            f"6m avg daily vol ({info['currency']}mn)": "{:.2f}".format(
                avg_daily_volume_6m / 1e6
            ),
            f"Closing Price ({info['currency']})": "{:.2f}".format(close_price),
            f"Market Cap ({info['currency']}mn)": "{:.2f}".format(
                FMPUtils.get_historical_market_cap(ticker_symbol, filing_date) / 1e6
            ),
            f"52 Week Price Range ({info['currency']})": "{:.2f} - {:.2f}".format(
                fiftyTwoWeekLow, fiftyTwoWeekHigh
            ),
            f"BVPS ({info['currency']})": "{:.2f}".format(
                FMPUtils.get_historical_bvps(ticker_symbol, filing_date)
            ),
        }
        return result
