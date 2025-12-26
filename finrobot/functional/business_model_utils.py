"""
Business Model Analysis Utilities for FinRobot.

This module provides utilities for analyzing company business models,
revenue generation mechanisms, unit economics, and competitive positioning.
"""

from typing import Annotated
from textwrap import dedent

from finrobot.data_source import SECUtils, YFinanceUtils, FMPUtils
from finrobot.functional.analyzer import combine_prompt, save_to_file, filter_by_fiscal_year


class BusinessModelAnalysisUtils:
    """Utilities for analyzing company business models and revenue generation."""

    @staticmethod
    def analyze_revenue_streams(
        ticker_symbol: Annotated[str, "Stock ticker symbol (e.g., 'AAPL')"],
        fyear: Annotated[str, "Fiscal year for analysis (e.g., '2024')"],
        save_path: Annotated[str, "Path to save the analysis output"]
    ) -> str:
        """
        Analyze company revenue streams from SEC filings and financial data.

        Extracts:
        - Revenue segment breakdown
        - Geographic distribution
        - Product vs service mix
        - Recurring vs non-recurring revenue
        """
        # Get SEC 10-K Item 1 (Business Description)
        business_desc = SECUtils.get_10k_section(ticker_symbol, fyear, 1)
        if business_desc is None:
            business_desc = "(Business description not available - SEC API key may not be configured)"

        # Get SEC 10-K Item 7 (MD&A) for segment analysis
        mda_section = SECUtils.get_10k_section(ticker_symbol, fyear, 7)
        if mda_section is None:
            mda_section = "(MD&A section not available - SEC API key may not be configured)"

        # Get income statement for revenue data
        income_stmt = YFinanceUtils.get_income_stmt(ticker_symbol)
        income_stmt = filter_by_fiscal_year(income_stmt, fyear)
        df_string = f"Income statement for FY{fyear} (and prior years for comparison):\n" + income_stmt.to_string().strip()
        df_string += f"\n\nNOTE: Use ONLY FY{fyear} data for the analysis. Prior years are for comparison only."

        instruction = dedent(
            """
            Analyze the revenue streams for this company. Provide a structured breakdown:

            1. PRIMARY REVENUE STREAMS:
               - List each major product/service line
               - Include revenue amount and percentage of total if available
               - Note year-over-year growth for each stream

            2. REVENUE MODEL CLASSIFICATION:
               - Identify the primary revenue model type(s):
                 * Subscription/SaaS (recurring fees)
                 * Licensing (IP/software licenses)
                 * Transaction fees (per-transaction revenue)
                 * Advertising (ad-supported)
                 * Hardware sales (product sales)
                 * Professional services (consulting/implementation)
                 * Freemium (free tier + paid upgrades)
                 * Marketplace (platform fees)
                 * Hybrid (combination)

            3. GEOGRAPHIC DISTRIBUTION:
               - Revenue by region/country if disclosed
               - Key growth markets

            4. PRODUCT vs SERVICE MIX:
               - Percentage from products
               - Percentage from services
               - Trend direction

            Use specific numbers from the financial data. Be factual and concise.
            """
        )

        section_text = (
            "Resource: Business Description (10-K Item 1):\n"
            + business_desc
            + "\n\n"
            + "Resource: Management's Discussion and Analysis (10-K Item 7):\n"
            + mda_section
        )

        prompt = combine_prompt(instruction, section_text, df_string)
        save_to_file(prompt, save_path)
        return f"Revenue streams analysis saved to {save_path}"

    @staticmethod
    def analyze_unit_economics(
        ticker_symbol: Annotated[str, "Stock ticker symbol"],
        fyear: Annotated[str, "Fiscal year for analysis"],
        save_path: Annotated[str, "Path to save the analysis output"]
    ) -> str:
        """
        Analyze unit economics and key business drivers.

        Calculates (where data available):
        - Gross margin analysis
        - Operating leverage
        - Revenue per employee
        - R&D intensity
        - SG&A efficiency
        """
        # Get income statement
        income_stmt = YFinanceUtils.get_income_stmt(ticker_symbol)
        income_stmt = filter_by_fiscal_year(income_stmt, fyear)
        df_string = f"Income statement for FY{fyear}:\n" + income_stmt.to_string().strip()

        # Get company profile for employee count
        try:
            profile = FMPUtils.get_company_profile(ticker_symbol)
            profile_text = f"Company Profile:\n{profile}" if profile else ""
        except Exception:
            profile_text = ""

        # Get MD&A for context
        mda_section = SECUtils.get_10k_section(ticker_symbol, fyear, 7)
        if mda_section is None:
            mda_section = "(MD&A not available)"

        instruction = dedent(
            """
            Analyze the unit economics and key business drivers. Calculate and assess:

            1. MARGIN ANALYSIS:
               - Gross Margin: (Revenue - COGS) / Revenue
               - Operating Margin: Operating Income / Revenue
               - Net Margin: Net Income / Revenue
               - Trend vs prior years

            2. OPERATING LEVERAGE:
               - Fixed vs variable cost structure
               - How margins scale with revenue growth
               - Break-even dynamics

            3. EFFICIENCY METRICS:
               - Revenue per Employee (if employee count available)
               - R&D as % of Revenue (R&D intensity)
               - SG&A as % of Revenue (sales efficiency)

            4. CAPITAL EFFICIENCY:
               - Return on invested capital indicators
               - Asset turnover insights

            5. KEY BUSINESS DRIVERS:
               - What drives revenue growth?
               - What drives margin expansion/contraction?
               - Scalability assessment

            Provide specific calculations with numbers. Note any concerning trends.
            """
        )

        section_text = profile_text + "\n\nMD&A Context:\n" + mda_section[:5000] if mda_section else profile_text

        prompt = combine_prompt(instruction, section_text, df_string)
        save_to_file(prompt, save_path)
        return f"Unit economics analysis saved to {save_path}"

    @staticmethod
    def classify_business_model(
        ticker_symbol: Annotated[str, "Stock ticker symbol"],
        fyear: Annotated[str, "Fiscal year for analysis"],
        save_path: Annotated[str, "Path to save the analysis output"]
    ) -> str:
        """
        Classify the company's business model using Business Model Canvas framework.

        Analyzes 9 building blocks:
        1. Customer Segments
        2. Value Propositions
        3. Channels
        4. Customer Relationships
        5. Revenue Streams
        6. Key Resources
        7. Key Activities
        8. Key Partnerships
        9. Cost Structure
        """
        # Get business description
        business_desc = SECUtils.get_10k_section(ticker_symbol, fyear, 1)
        if business_desc is None:
            business_desc = "(Business description not available)"

        # Get MD&A
        mda_section = SECUtils.get_10k_section(ticker_symbol, fyear, 7)
        if mda_section is None:
            mda_section = "(MD&A not available)"

        # Get income statement for cost structure
        income_stmt = YFinanceUtils.get_income_stmt(ticker_symbol)
        income_stmt = filter_by_fiscal_year(income_stmt, fyear)
        df_string = f"Income statement for FY{fyear}:\n" + income_stmt.to_string().strip()

        instruction = dedent(
            """
            Classify this company's business model using the Business Model Canvas framework.
            Analyze each of the 9 building blocks:

            1. CUSTOMER SEGMENTS:
               - Who are the key customers?
               - B2B, B2C, or both?
               - Market segments served

            2. VALUE PROPOSITIONS:
               - What unique value does the company provide?
               - Why do customers choose this company?

            3. CHANNELS:
               - How does the company reach customers?
               - Direct sales, retail, online, partners?

            4. CUSTOMER RELATIONSHIPS:
               - How does the company acquire and retain customers?
               - Self-service, dedicated support, community?

            5. REVENUE STREAMS:
               - How does the company make money?
               - Pricing models and monetization strategies

            6. KEY RESOURCES:
               - What assets are essential? (IP, brand, talent, infrastructure)

            7. KEY ACTIVITIES:
               - What must the company do well to succeed?

            8. KEY PARTNERSHIPS:
               - Critical suppliers, alliances, joint ventures

            9. COST STRUCTURE:
               - Major cost drivers
               - Fixed vs variable costs
               - Economies of scale

            Provide a structured analysis with evidence from the filings.
            """
        )

        section_text = (
            "Business Description:\n" + business_desc[:8000]
            + "\n\nMD&A:\n" + mda_section[:5000]
        )

        prompt = combine_prompt(instruction, section_text, df_string)
        save_to_file(prompt, save_path)
        return f"Business model classification saved to {save_path}"

    @staticmethod
    def compare_operating_models(
        ticker_symbol: Annotated[str, "Primary company ticker"],
        competitors: Annotated[str, "Comma-separated list of competitor tickers (e.g., 'MSFT,GOOGL')"],
        fyear: Annotated[str, "Fiscal year for comparison"],
        save_path: Annotated[str, "Path to save the comparison output"]
    ) -> str:
        """
        Compare operating models with competitors.

        Comparison dimensions:
        - Revenue model type
        - Gross margin profile
        - Operating margin
        - R&D intensity
        - Growth rate
        """
        competitor_list = [t.strip() for t in competitors.split(",")]
        all_tickers = [ticker_symbol] + competitor_list

        comparison_data = []
        for ticker in all_tickers:
            try:
                income_stmt = YFinanceUtils.get_income_stmt(ticker)
                income_stmt = filter_by_fiscal_year(income_stmt, fyear)
                comparison_data.append(f"\n{ticker} Income Statement FY{fyear}:\n" + income_stmt.to_string().strip())
            except Exception as e:
                comparison_data.append(f"\n{ticker}: Data not available ({str(e)})")

        df_string = "\n".join(comparison_data)

        # Get business descriptions for context
        descriptions = []
        for ticker in all_tickers[:3]:  # Limit to avoid too much text
            try:
                desc = SECUtils.get_10k_section(ticker, fyear, 1)
                if desc:
                    descriptions.append(f"{ticker} Business:\n{desc[:2000]}")
            except Exception:
                pass

        section_text = "\n\n".join(descriptions) if descriptions else "Business descriptions not available"

        instruction = dedent(
            f"""
            Compare the operating models of {ticker_symbol} with competitors: {competitors}

            Create a comparison table and analysis covering:

            1. REVENUE MODEL COMPARISON:
               | Company | Primary Revenue Model | Secondary Models |
               |---------|----------------------|------------------|

            2. MARGIN COMPARISON:
               | Company | Gross Margin | Operating Margin | Net Margin |
               |---------|--------------|------------------|------------|

            3. EFFICIENCY COMPARISON:
               | Company | R&D % Revenue | SG&A % Revenue |
               |---------|---------------|----------------|

            4. GROWTH COMPARISON:
               - Revenue growth rates
               - Margin trends

            5. COMPETITIVE POSITIONING:
               - Key differentiators
               - Relative strengths/weaknesses
               - Moat assessment

            Use specific numbers. Identify the leader in each category.
            """
        )

        prompt = combine_prompt(instruction, section_text, df_string)
        save_to_file(prompt, save_path)
        return f"Operating model comparison saved to {save_path}"

    @staticmethod
    def analyze_revenue_quality(
        ticker_symbol: Annotated[str, "Stock ticker symbol"],
        fyear: Annotated[str, "Fiscal year for analysis"],
        save_path: Annotated[str, "Path to save the analysis output"]
    ) -> str:
        """
        Assess revenue quality and sustainability.

        Evaluates:
        - Recurring revenue percentage
        - Customer concentration (top customers %)
        - Contract backlog
        - Deferred revenue trends
        - Revenue recognition policies
        """
        # Get business description for customer info
        business_desc = SECUtils.get_10k_section(ticker_symbol, fyear, 1)
        if business_desc is None:
            business_desc = "(Business description not available)"

        # Get MD&A for revenue policies
        mda_section = SECUtils.get_10k_section(ticker_symbol, fyear, 7)
        if mda_section is None:
            mda_section = "(MD&A not available)"

        # Get Risk Factors (Item 1A) for concentration risks
        risk_factors = SECUtils.get_10k_section(ticker_symbol, fyear, "1A")
        if risk_factors is None:
            risk_factors = "(Risk factors not available)"

        # Get balance sheet for deferred revenue
        try:
            balance_sheet = YFinanceUtils.get_balance_sheet(ticker_symbol)
            bs_string = f"Balance Sheet:\n" + balance_sheet.to_string().strip()
        except Exception:
            bs_string = "Balance sheet not available"

        # Get income statement
        income_stmt = YFinanceUtils.get_income_stmt(ticker_symbol)
        income_stmt = filter_by_fiscal_year(income_stmt, fyear)
        is_string = f"Income Statement FY{fyear}:\n" + income_stmt.to_string().strip()

        instruction = dedent(
            """
            Assess the quality and sustainability of this company's revenue. Analyze:

            1. RECURRING vs NON-RECURRING REVENUE:
               - What percentage is recurring/subscription?
               - What percentage is one-time/transactional?
               - Visibility into future revenue

            2. CUSTOMER CONCENTRATION:
               - Top customer dependency (if disclosed)
               - Top 10 customers as % of revenue
               - Concentration risk assessment

            3. CONTRACT BACKLOG:
               - Remaining performance obligations
               - Backlog trend
               - Contract duration

            4. DEFERRED REVENUE:
               - Deferred revenue balance
               - Trend (growing or shrinking?)
               - What it indicates about future revenue

            5. REVENUE RECOGNITION:
               - Key revenue recognition policies
               - Any aggressive recognition practices?
               - Timing of revenue recognition

            6. REVENUE QUALITY SCORE:
               - Rate overall revenue quality (High/Medium/Low)
               - Key risks to revenue sustainability
               - Positive quality indicators

            Be specific with numbers and cite sources from the filings.
            """
        )

        section_text = (
            "Business Description:\n" + business_desc[:4000]
            + "\n\nMD&A:\n" + mda_section[:4000]
            + "\n\nRisk Factors:\n" + risk_factors[:3000]
        )

        df_string = is_string + "\n\n" + bs_string

        prompt = combine_prompt(instruction, section_text, df_string)
        save_to_file(prompt, save_path)
        return f"Revenue quality analysis saved to {save_path}"
