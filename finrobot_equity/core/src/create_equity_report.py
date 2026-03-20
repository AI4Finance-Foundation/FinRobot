#!/usr/bin/env python
# coding: utf-8

import argparse
import os
import pandas as pd
from datetime import datetime
import pytz

EASTERN_TZ = pytz.timezone('America/New_York')

from modules.common_utils import load_config, get_api_key
from modules.report_data_loader import load_analysis_csv, load_text_from_file
from modules.html_renderer import render_html_report, render_combined_html_report, HTML_TEMPLATE_PAGE_1, HTML_TEMPLATE_PAGE_2_FINANCIAL_SUMMARY, HTML_TEMPLATE_PAGE_3_PEER_COMPARISON, HTML_TEMPLATE_PAGE_4_SENSITIVITY_CATALYST, HTML_TEMPLATE_PAGE_5_NEWS_CHARTS, HTML_TEMPLATE_COMBINED, format_dataframe_to_html_table
from modules.html_template_professional import render_professional_html_report
from modules.chart_generator import (
    generate_revenue_ebitda_chart, 
    generate_ev_ebitda_peer_chart, 
    generate_eps_pe_chart,
    # 高级图表函数
    generate_stock_price_chart,
    generate_financial_radar_chart,
    generate_time_series_chart,
    generate_sensitivity_heatmap,
    generate_technical_indicators_chart,
    generate_valuation_waterfall_chart,
    generate_quarterly_comparison_chart,
    generate_cash_flow_chart
)
from modules.market_data_api import get_comprehensive_company_metrics

# Import the single, unified text generation function
from modules.text_generator_agents import generate_text_section

# 新增模块导入
from modules.enhanced_chart_generator import EnhancedChartGenerator, ChartConfig
from modules.valuation_engine import ValuationEngine
from modules.report_structure import ReportStructureManager
from modules.enhanced_text_generator import EnhancedTextGenerator

import pandas as pd

def load_credit_cashflow_metrics_from_csv(file_path: str) -> pd.DataFrame:
    """Load credit and cashflow metrics from a pre-computed CSV file."""
    if not file_path or not os.path.exists(file_path):
        print(f"Warning: Ratios CSV file not found at {file_path}")
        return pd.DataFrame()

    try:
        df = pd.read_csv(file_path)

        # Define the mapping from CSV columns to the desired metric names
        metric_mapping = {
            'debtEquityRatio': 'Debt/Equity',
            'debtRatio': 'Debt/Assets',
            'interestCoverage': 'EBITDA/Int Exp',
            'netProfitMargin': 'Net Margin',
            'currentRatio': 'Current Ratio',
            'cashFlowToDebtRatio': 'Cash Flow to Debt Ratio'
        }

        # Check if necessary columns exist
        if 'calendarYear' not in df.columns or not all(key in df.columns for key in metric_mapping.keys()):
            print("Warning: The ratios CSV file is missing required columns (e.g., 'calendarYear' or ratio columns).")
            return pd.DataFrame()

        # Reverse the DataFrame to have the latest year last
        df = df.sort_values(by='calendarYear').reset_index(drop=True)

        # Initialize the dictionary to hold the formatted data
        credit_metrics_data = {'metrics': list(metric_mapping.values())}

        year_cols = sorted(df['calendarYear'].unique())

        for year in year_cols:
            year_str = f"{year}A" # Append 'A' to match existing format
            credit_metrics_data[year_str] = []
            year_data = df[df['calendarYear'] == year].iloc[0]

            # Populate the data for the year based on the mapping
            credit_metrics_data[year_str].append(f"{year_data['debtEquityRatio']:.2f}" if pd.notna(year_data['debtEquityRatio']) else "N/A")
            credit_metrics_data[year_str].append(f"{year_data['debtRatio']:.2f}" if pd.notna(year_data['debtRatio']) else "N/A")
            credit_metrics_data[year_str].append(f"{year_data['interestCoverage']:.1f}x" if pd.notna(year_data['interestCoverage']) else "N/A")
            credit_metrics_data[year_str].append(f"{year_data['netProfitMargin']*100:.1f}%" if pd.notna(year_data['netProfitMargin']) else "N/A")
            credit_metrics_data[year_str].append(f"{year_data['currentRatio']:.1f}" if pd.notna(year_data['currentRatio']) else "N/A")
            credit_metrics_data[year_str].append(f"{year_data['cashFlowToDebtRatio']:.2f}" if pd.notna(year_data['cashFlowToDebtRatio']) else "N/A")


        return pd.DataFrame(credit_metrics_data)

    except Exception as e:
        print(f"An error occurred while loading credit metrics from CSV: {e}")
        return pd.DataFrame()


def filter_actual_years_only(df: pd.DataFrame) -> pd.DataFrame:
    """Filter DataFrame to include only actual years (ending with 'A'), excluding estimates."""
    if df is None or df.empty:
        return df

    # Get columns that are actual years (ending with 'A') and the metrics column
    actual_year_cols = [col for col in df.columns if isinstance(col, str) and col.endswith('A')]
    if 'metrics' in df.columns:
        cols_to_keep = ['metrics'] + actual_year_cols
    else:
        cols_to_keep = actual_year_cols

    # Filter to only include these columns
    return df[cols_to_keep]


def generate_major_takeaways(analysis_df: pd.DataFrame, company_ticker: str) -> dict:
    """Generate major takeaways from the financial analysis data."""
    takeaways = {}

    try:
        # Get recent years data (only actual years, no estimates)
        year_cols = [col for col in analysis_df.columns if col.endswith('A') and col != 'metrics']
        if len(year_cols) < 2:
            # Return default takeaways if not enough data
            return {
                "revenue_growth_takeaway": f"{company_ticker}'s revenue growth data requires additional analysis.",
                "gross_margin_takeaway": f"{company_ticker}'s gross profit margin trends require further evaluation.",
                "sga_margin_takeaway": f"{company_ticker}'s SG&A expense management efficiency needs assessment.",
                "ebitda_margin_takeaway": f"{company_ticker}'s EBITDA margin stability shows consistent performance."
            }

        # Revenue Growth analysis
        revenue_growth_rows = analysis_df[analysis_df['metrics'] == 'Revenue Growth']
        if not revenue_growth_rows.empty:
            latest_growth = str(revenue_growth_rows[year_cols[-1]].iloc[0])
            prev_growth = str(revenue_growth_rows[year_cols[-2]].iloc[0]) if len(year_cols) > 1 else "N/A"
            takeaways["revenue_growth_takeaway"] = f"{company_ticker}'s revenue growth of {latest_growth} in {year_cols[-1]} shows solid momentum compared to {prev_growth} in {year_cols[-2]}."

        # Contribution/Gross Margin analysis
        margin_rows = analysis_df[analysis_df['metrics'] == 'Contribution Margin']
        if not margin_rows.empty:
            latest_margin = str(margin_rows[year_cols[-1]].iloc[0])
            prev_margin = str(margin_rows[year_cols[-2]].iloc[0]) if len(year_cols) > 1 else "N/A"
            takeaways["gross_margin_takeaway"] = f"{company_ticker}'s contribution margin improved to {latest_margin} in {year_cols[-1]} from {prev_margin} in {year_cols[-2]}, indicating operational efficiency gains."

        # SG&A Margin analysis
        sga_rows = analysis_df[analysis_df['metrics'] == 'SG&A Margin']
        if not sga_rows.empty:
            latest_sga = str(sga_rows[year_cols[-1]].iloc[0])
            prev_sga = str(sga_rows[year_cols[-2]].iloc[0]) if len(year_cols) > 1 else "N/A"
            takeaways["sga_margin_takeaway"] = f"{company_ticker}'s SG&A margin of {latest_sga} in {year_cols[-1]} compared to {prev_sga} in {year_cols[-2]} demonstrates expense management focus."

        # EBITDA Margin analysis
        ebitda_rows = analysis_df[analysis_df['metrics'] == 'EBITDA Margin']
        if not ebitda_rows.empty:
            latest_ebitda = str(ebitda_rows[year_cols[-1]].iloc[0])
            prev_ebitda = str(ebitda_rows[year_cols[-2]].iloc[0]) if len(year_cols) > 1 else "N/A"
            takeaways["ebitda_margin_takeaway"] = f"{company_ticker}'s EBITDA margin of {latest_ebitda} in {year_cols[-1]} vs {prev_ebitda} in {year_cols[-2]} shows stable profitability."

    except Exception as e:
        print(f"Warning: Error generating takeaways: {e}")
        # Return default takeaways
        takeaways = {
            "revenue_growth_takeaway": f"{company_ticker}'s revenue growth shows consistent performance trends.",
            "gross_margin_takeaway": f"{company_ticker}'s gross profit margins demonstrate operational effectiveness.",
            "sga_margin_takeaway": f"{company_ticker}'s SG&A expense management shows disciplined cost control.",
            "ebitda_margin_takeaway": f"{company_ticker}'s EBITDA margin stability reflects strong underlying fundamentals."
        }

    return takeaways


def validate_and_fix_text_content(text_content: str, text_type: str, company_name: str, company_ticker: str) -> str:
    """Validate text content and provide basic validation without fallbacks."""
    if not text_content or text_content.strip() == "":
        print(f"⚠️ Warning: {text_type} is empty")
        return ""
    
    # Check if content looks like CSV data (especially for competitor_analysis and major_takeaways)
    if text_type in ["competitor_analysis", "major_takeaways"]:
        content_lower = text_content.lower().strip()
        # Detect CSV-like patterns (more robust detection)
        first_line = content_lower.split('\n')[0] if '\n' in content_lower else content_lower
        is_csv_like = (
            content_lower.startswith("year,") or 
            content_lower.startswith("ticker,") or
            content_lower.startswith("date,") or
            content_lower.count(",") > 20 or  # Many commas suggest CSV
            (first_line.count(",") >= 3 and not any(word in first_line for word in ["the", "and", "is", "are", "has", "have"]))  # CSV header pattern
        )
        if is_csv_like:
            print(f"⚠️ Warning: {text_type} contains CSV-like data, marking for regeneration")
            return ""  # Return empty to trigger regeneration
    
    print(f"✅ {text_type} validation passed ({len(text_content)} chars)")
    return text_content


def regenerate_text_if_needed(text_content: str, text_type: str, company_name: str, company_ticker: str, 
                             analysis_df: pd.DataFrame, peer_ebitda_df: pd.DataFrame, 
                             peer_ev_ebitda_df: pd.DataFrame, api_key: str = None) -> str:
    """Generate text content using AI, calling the single unified function."""
    
    # This function now handles all text types through the same logic if regeneration is enabled.
    if text_type in ["competitor_analysis", "major_takeaways"] and api_key:
        try:
            # Prepare data for generation
            data_for_generation = {
                "financial_metrics": analysis_df,
                "peer_ebitda": peer_ebitda_df,
                "peer_ev_ebitda": peer_ev_ebitda_df,
            }
            
            print(f"🤖 Regenerating '{text_type}' using AI...")
            # Call the single, unified text generation function
            generated_text = generate_text_section(
                data_for_generation, 
                text_type, 
                api_key, 
                company_name, 
                company_ticker
            )
            
            # Basic validation of the generated content
            if generated_text and len(generated_text.strip()) > 50:
                print(f"✅ Successfully regenerated '{text_type}' using AI")
                return generated_text
            else:
                print(f"❌ AI regenerated '{text_type}' is insufficient, using original content from file.")
                return validate_and_fix_text_content(text_content, text_type, company_name, company_ticker)
            
        except Exception as e:
            print(f"❌ Failed to regenerate '{text_type}' with AI: {e}")
            return validate_and_fix_text_content(text_content, text_type, company_name, company_ticker)
    
    # For other text types or if regeneration is off, just validate the content from the file.
    return validate_and_fix_text_content(text_content, text_type, company_name, company_ticker)


def process_text_content(args, analysis_df, peer_ebitda_df, peer_ev_ebitda_df, openai_api_key):
    """Process all text content with enhanced AI generation for competitor analysis and takeaways."""
    
    print("📖 Loading and processing text content...")
    
    # Load raw text content
    raw_texts = {
        "tagline": load_text_from_file(args.tagline_file),
        "company_overview": load_text_from_file(args.company_overview_file),
        "investment_overview": load_text_from_file(args.investment_overview_file),
        "valuation_overview": load_text_from_file(args.valuation_overview_file),
        "risks": load_text_from_file(args.risks_file),
        "competitor_analysis": load_text_from_file(args.competitor_analysis_file),
        "major_takeaways": load_text_from_file(args.major_takeaways_file),
        "news_summary": load_text_from_file(args.news_summary_file) if args.news_summary_file else ""
    }
    
    # Process text content
    processed_texts = {}
    for text_type, raw_content in raw_texts.items():
        print(f"📝 Processing {text_type}...")
        
        # Check if content looks like CSV data (for competitor_analysis and major_takeaways)
        if text_type in ["competitor_analysis", "major_takeaways"] and raw_content:
            content_lower = raw_content.lower().strip()
            first_line = content_lower.split('\n')[0] if '\n' in content_lower else content_lower
            is_csv_data = (
                content_lower.startswith("year,") or 
                content_lower.startswith("ticker,") or
                content_lower.startswith("date,") or
                content_lower.count(",") > 20 or
                (first_line.count(",") >= 3 and not any(word in first_line for word in ["the", "and", "is", "are", "has", "have"]))
            )
            
            # Force regeneration for CSV-like data even without the flag
            if is_csv_data and openai_api_key:
                print(f"⚠️ Detected CSV data in {text_type}, forcing AI regeneration...")
                processed_texts[text_type] = regenerate_text_if_needed(
                    raw_content or "", text_type, args.company_name, args.company_ticker,
                    analysis_df, peer_ebitda_df, peer_ev_ebitda_df, openai_api_key
                )
            # If no API key, provide a fallback
            elif is_csv_data:
                print(f"⚠️ CSV data detected in {text_type} but no API key available, using fallback...")
                if text_type == "competitor_analysis":
                    processed_texts[text_type] = f"{args.company_name} demonstrates competitive positioning within its industry sector through consistent financial performance and strategic market positioning relative to key competitors."
                else:  # major_takeaways
                    processed_texts[text_type] = f"Revenue Growth: {args.company_name}'s revenue growth shows consistent performance trends.\n\nGross Profit Margin: {args.company_name}'s gross profit margins demonstrate operational effectiveness.\n\nSG&A Expense Margin: {args.company_name}'s SG&A expense management shows disciplined cost control.\n\nEBITDA Margin Stability: {args.company_name}'s EBITDA margin stability reflects strong underlying fundamentals."
            else:
                # Regular flow for non-CSV data
                if args.enable_text_regeneration and openai_api_key:
                    processed_texts[text_type] = regenerate_text_if_needed(
                        raw_content or "", text_type, args.company_name, args.company_ticker,
                        analysis_df, peer_ebitda_df, peer_ev_ebitda_df, openai_api_key
                    )
                else:
                    processed_texts[text_type] = validate_and_fix_text_content(
                        raw_content or "", text_type, args.company_name, args.company_ticker
                    )
        else:
            # Regular flow for other text types
            if args.enable_text_regeneration and openai_api_key:
                processed_texts[text_type] = regenerate_text_if_needed(
                    raw_content or "", text_type, args.company_name, args.company_ticker,
                    analysis_df, peer_ebitda_df, peer_ev_ebitda_df, openai_api_key
                )
            else:
                processed_texts[text_type] = validate_and_fix_text_content(
                    raw_content or "", text_type, args.company_name, args.company_ticker
                )

    print(f"✅ All text content processed")
    return processed_texts


def main():
    parser = argparse.ArgumentParser(description="Create an equity research report in HTML format with auto-fetched market data.")

    # --- Command-line arguments ---
    # Required
    parser.add_argument("--company-ticker", type=str, required=True, help="Stock ticker.")
    parser.add_argument("--company-name", type=str, required=True, help="Full company name.")
    parser.add_argument("--analysis-csv", type=str, required=True, help="Path to the financial_metrics_and_forecasts.csv file.")
    parser.add_argument("--ratios-csv", type=str, required=True, help="Path to the ratios_raw_data.csv file.")
    parser.add_argument("--tagline-file", type=str, required=True, help="Path to a text file for the report tagline.")
    parser.add_argument("--company-overview-file", type=str, required=True, help="Path to a text file for the company overview.")
    parser.add_argument("--investment-overview-file", type=str, required=True, help="Path to a text file for the investment overview.")
    parser.add_argument("--valuation-overview-file", type=str, required=True, help="Path to a text file for the valuation section.")
    parser.add_argument("--risks-file", type=str, required=True, help="Path to a text file for the risks section.")
    parser.add_argument("--competitor-analysis-file", type=str, required=True, help="Path to a text file for the competitor analysis section.")
    parser.add_argument("--major-takeaways-file", type=str, required=True, help="Path to a text file for the major takeaways section.")
    parser.add_argument("--news-summary-file", type=str, required=False, default=None, help="Path to a text file for the news summary section (optional).")

    # Optional with defaults
    parser.add_argument("--report-date", type=str, default=datetime.now(EASTERN_TZ).strftime("%B %d, %Y"), help="Date for the report (Eastern Time).")
    parser.add_argument("--output-dir", type=str, default=None, help="Directory to save HTML reports. Default: ./output/[TICKER]/report/")
    parser.add_argument("--html-report-prefix", type=str, default="Equity_Report", help="Prefix for output HTML filenames.")
    parser.add_argument("--analyst-names", type=str, nargs="*", default=["Analyst Name"], help="List of analyst names.")
    parser.add_argument("--analyst-emails", type=str, nargs="*", default=["analyst@example.com"], help="List of analyst emails.")
    parser.add_argument("--research-source", type=str, default="AI4Finance Foundation FinRobot Equity Research", help="Source of the research.")
    parser.add_argument("--data-source-text", type=str, default="Company Filings, FMP, Yahoo Finance, AI4Finance Estimates", help="Text for data sources.")
    parser.add_argument("--disclaimer-text", type=str, default="Disclaimer: The information contained in this document is intended only for use by the person to whom it has been delivered and should not be disseminated or distributed to third parties without our prior written consent. Our firm accepts no liability whatsoever with respect to the use of this document or its contents.", help="Disclaimer text.")
    parser.add_argument("--closing-price-date", type=str, default=datetime.now(EASTERN_TZ).strftime("%B %d, %Y"), help="Date of the share price (Eastern Time).")

    # Market data - Optional (will be auto-fetched if not provided)
    parser.add_argument("--share-price", type=float, default=None, help="Current share price (will be auto-fetched if not provided).")
    parser.add_argument("--target-price", type=float, default=None, help="12-month target price (will be auto-fetched if not provided).")
    parser.add_argument("--rating", type=str, default=None, help="Analyst rating (will be auto-fetched if not provided).")
    parser.add_argument("--market-cap", type=float, default=None, help="Market cap in billions (will be auto-fetched if not provided).")
    parser.add_argument("--volume", type=float, default=None, help="Average daily volume in millions (will be auto-fetched if not provided).")
    parser.add_argument("--fwd-pe", type=float, default=None, help="Forward P/E ratio (will be auto-fetched if not provided).")
    parser.add_argument("--pb-ratio", type=float, default=None, help="Price to Book ratio (will be auto-fetched if not provided).")
    parser.add_argument("--dividend-yield", type=str, default=None, help="Dividend yield (will be auto-fetched if not provided).")
    parser.add_argument("--free-float", type=str, default=None, help="Free float percentage (will be auto-fetched if not provided).")
    parser.add_argument("--roe", type=str, default=None, help="Return on Equity (will be auto-fetched if not provided).")
    parser.add_argument("--net-debt-to-equity", type=str, default=None, help="Net Debt to Equity ratio (will be auto-fetched if not provided).")
    parser.add_argument("--sector", type=str, default=None, help="Company sector (will be auto-fetched if not provided).")

    # Configuration and paths
    parser.add_argument("--config-file", type=str, default=None, help="Path to config.ini file.")
    parser.add_argument("--logo-image-path", type=str, default="./assets/piclogo.png", help="Path to the logo image.")
    parser.add_argument("--revenue-chart-path", type=str, default=None, help="Path to a pre-generated revenue/EBITDA chart.")
    parser.add_argument("--ev-ebitda-chart-path", type=str, default=None, help="Path to a pre-generated EV/EBITDA peer comparison chart.")
    parser.add_argument("--peer-ebitda-csv", type=str, help="Path to peer_ebitda_comparison.csv.")
    parser.add_argument("--peer-ev-ebitda-csv", type=str, help="Path to peer_ev_ebitda_comparison.csv.")

    # Auto-fetch control
    parser.add_argument("--skip-auto-fetch", action="store_true", help="Skip automatic fetching of market data from FMP API.")
    
    # Text regeneration option
    parser.add_argument("--enable-text-regeneration", action="store_true", help="Enable AI text regeneration if content quality is poor.")
    
    # 新增增强功能选项
    parser.add_argument("--enable-enhanced-charts", action="store_true", help="Enable enhanced chart generation with 11 professional chart types.")
    parser.add_argument("--enable-valuation-analysis", action="store_true", help="Enable multi-method valuation analysis.")
    parser.add_argument("--sensitivity-analysis-file", type=str, default=None, help="Path to sensitivity analysis JSON file.")
    parser.add_argument("--catalyst-analysis-file", type=str, default=None, help="Path to catalyst analysis JSON file.")
    parser.add_argument("--enhanced-news-file", type=str, default=None, help="Path to enhanced news JSON file.")

    args = parser.parse_args()

    # --- Setup directories ---
    output_dir = args.output_dir or os.path.join(".", "output", args.company_ticker, "report")
    os.makedirs(output_dir, exist_ok=True)
    print(f"HTML reports will be saved to: {output_dir}")

    # --- Load configuration and API key ---
    openai_api_key = None
    try:
        config = load_config(args.config_file)
        fmp_api_key = get_api_key(config, "API_KEYS", "fmp_api_key")
        if args.enable_text_regeneration:
            try:
                openai_api_key = get_api_key(config, "API_KEYS", "openai_api_key")
                print("✅ OpenAI API key loaded for text regeneration")
            except Exception as e:
                print(f"⚠️ Warning: OpenAI API key not available: {e}")
                print("Text regeneration will be disabled")
    except Exception as e:
        print(f"Warning: Could not load FMP API key: {e}")
        fmp_api_key = None

    # --- Auto-fetch market data if not provided and API key available ---
    auto_fetched_metrics = {}
    if not args.skip_auto_fetch and fmp_api_key:
        print(f"Auto-fetching market data for {args.company_ticker}...")
        try:
            auto_fetched_metrics = get_comprehensive_company_metrics(args.company_ticker, fmp_api_key)
            print("✅ Successfully auto-fetched market data")
        except Exception as e:
            print(f"⚠️  Warning: Auto-fetch failed: {e}")
            print("Will use provided values or defaults")
    elif args.skip_auto_fetch:
        print("Skipping auto-fetch as requested")
    else:
        print("⚠️  No FMP API key found, skipping auto-fetch")

    # --- Determine final values (command line args override auto-fetched) ---
    def get_value(arg_value, auto_key, default_value, format_func=None):
        """Get the final value, prioritizing: command line arg > auto-fetched > default"""
        if arg_value is not None:
            return format_func(arg_value) if format_func else arg_value
        elif auto_key in auto_fetched_metrics and auto_fetched_metrics[auto_key] is not None:
            value = auto_fetched_metrics[auto_key]
            return format_func(value) if format_func else value
        else:
            return default_value

    # Apply the logic for each metric
    share_price = get_value(args.share_price, 'share_price', 0.0, lambda x: f"${x:.2f}")
    target_price = get_value(args.target_price, 'target_price', 0.0, lambda x: f"${x:.2f}")
    rating = get_value(args.rating, 'rating', "N/A")
    market_cap = get_value(args.market_cap, 'market_cap', 0.0, lambda x: f"${x:,.2f}B")
    volume = get_value(args.volume, 'volume', 0.0, lambda x: f"{x:.2f}M")
    fwd_pe = get_value(args.fwd_pe, 'fwd_pe', 0.0, lambda x: f"{x:.1f}x")
    pb_ratio = get_value(args.pb_ratio, 'pb_ratio', 0.0, lambda x: f"{x:.2f}x")
    dividend_yield = get_value(args.dividend_yield, 'dividend_yield', "N/A", lambda x: f"{x:.2f}%" if isinstance(x, (int, float)) else str(x))
    free_float = get_value(args.free_float, 'free_float', "N/A", lambda x: f"{x:.1f}%" if isinstance(x, (int, float)) else str(x))
    roe = get_value(args.roe, 'roe', "N/A", lambda x: f"{x:.1f}%" if isinstance(x, (int, float)) else str(x))
    net_debt_to_equity = get_value(args.net_debt_to_equity, 'net_debt_to_equity', "N/A", lambda x: f"{x:.2f}%" if isinstance(x, (int, float)) else str(x))
    sector = get_value(args.sector, 'sector', "Industrials")

    # Print summary of what was auto-fetched vs. provided
    print(f"\n📊 Market Data Summary for {args.company_ticker}:")
    print(f"  Share Price: {share_price} {'(auto-fetched)' if args.share_price is None and 'share_price' in auto_fetched_metrics else '(provided)'}")
    print(f"  Target Price: {target_price} {'(auto-fetched)' if args.target_price is None and 'target_price' in auto_fetched_metrics else '(provided)'}")
    print(f"  Rating: {rating} {'(auto-fetched)' if args.rating is None and 'rating' in auto_fetched_metrics else '(provided)'}")
    print(f"  Market Cap: {market_cap} {'(auto-fetched)' if args.market_cap is None and 'market_cap' in auto_fetched_metrics else '(provided)'}")
    print(f"  Sector: {sector} {'(auto-fetched)' if args.sector is None and 'sector' in auto_fetched_metrics else '(provided)'}")

    # --- Load data ---
    analysis_df = load_analysis_csv(args.analysis_csv)
    if analysis_df is None:
        print("Error: Could not load analysis CSV file")
        return

    peer_ebitda_df = load_analysis_csv(args.peer_ebitda_csv) if args.peer_ebitda_csv else pd.DataFrame()
    peer_ev_ebitda_df = load_analysis_csv(args.peer_ev_ebitda_csv) if args.peer_ev_ebitda_csv else pd.DataFrame()

    # Process text content with AI enhancement
    processed_texts = process_text_content(args, analysis_df, peer_ebitda_df, peer_ev_ebitda_df, openai_api_key)
    
    # Assign processed texts
    tagline_text = processed_texts["tagline"]
    company_overview_text = processed_texts["company_overview"] 
    investment_overview_text = processed_texts["investment_overview"]
    valuation_overview_text = processed_texts["valuation_overview"]
    risks_text = processed_texts["risks"]
    competitor_analysis_text = processed_texts["competitor_analysis"]
    major_takeaways_text = processed_texts["major_takeaways"]
    news_summary_text = processed_texts["news_summary"]  # NEW

    # --- Prepare report data ---
    report_data = {
        "company_ticker": args.company_ticker,
        "company_name_full": args.company_name,
        "company_name_ticker": f"{args.company_name} ({args.company_ticker})",
        "report_date": args.report_date,
        "sector": sector,
        "share_price": share_price,
        "target_price": target_price,
        "rating": rating,
        "market_cap": market_cap,
        "volume": volume,
        "fwd_pe": fwd_pe,
        "pb_ratio": pb_ratio,
        "roe": roe,
        "free_float": free_float,
        "dividend_yield": dividend_yield,
        "net_debt_to_equity": net_debt_to_equity,
        "tagline": tagline_text,
        "company_overview": company_overview_text,
        "investment_overview": investment_overview_text,
        "valuation_overview": valuation_overview_text,
        "risks": risks_text,
        "competitor_analysis": competitor_analysis_text,
        "major_takeaways": major_takeaways_text,
        "news_summary": news_summary_text,  # NEW
        "research_source": args.research_source,
        "data_source_text": args.data_source_text,
        "disclaimer_text": args.disclaimer_text,
        "logo_image_path": args.logo_image_path,
        "analyst_names": args.analyst_names,
        "analyst_emails": args.analyst_emails,
        "closing_price_date": args.closing_price_date
    }

    # --- Generate or load charts ---
    print("Handling charts...")
    if args.revenue_chart_path and os.path.exists(args.revenue_chart_path):
        report_data['revenue_chart_path'] = args.revenue_chart_path
    else:
        chart_path = os.path.join(output_dir, f"{args.company_ticker}_revenue_ebitda_chart.png")
        chart_result = generate_revenue_ebitda_chart(analysis_df, chart_path, args.company_ticker)
        report_data['revenue_chart_path'] = chart_result or ""

    # Generate EPS × PE chart
    eps_pe_chart_path = os.path.join(output_dir, f"{args.company_ticker}_eps_pe_chart.png")
    eps_pe_chart_result = generate_eps_pe_chart(analysis_df, eps_pe_chart_path, args.company_ticker)
    report_data['eps_pe_chart_path'] = eps_pe_chart_result or ""

    if args.ev_ebitda_chart_path and os.path.exists(args.ev_ebitda_chart_path):
        report_data['ev_ebitda_chart_path'] = args.ev_ebitda_chart_path
    elif peer_ev_ebitda_df is not None and not peer_ev_ebitda_df.empty:
        if 'year' in peer_ev_ebitda_df.columns:
            peer_ev_ebitda_df.set_index('year', inplace=True)
        chart_path = os.path.join(output_dir, f"{args.company_ticker}_peer_ev_ebitda_chart.png")
        chart_result = generate_ev_ebitda_peer_chart(peer_ev_ebitda_df, chart_path, args.company_ticker)
        report_data['ev_ebitda_chart_path'] = chart_result or ""
    else:
        report_data['ev_ebitda_chart_path'] = ""

    # --- Enhanced Charts Generation ---
    if args.enable_enhanced_charts:
        print("Generating enhanced charts...")
        try:
            chart_config = ChartConfig()
            enhanced_chart_gen = EnhancedChartGenerator(chart_config)
            enhanced_charts = {}
            
            # Prepare financial data dict for generate_all_charts
            # Load income statement data if available
            income_csv_path = os.path.join(os.path.dirname(args.analysis_csv), "income_statement_raw_data.csv")
            income_df = pd.DataFrame()
            if os.path.exists(income_csv_path):
                income_df = pd.read_csv(income_csv_path)
                print(f"✅ Loaded income statement data from {income_csv_path}")
            
            # Load price data if available
            price_csv_path = os.path.join(os.path.dirname(args.analysis_csv), "historical_price_full.csv")
            price_df = pd.DataFrame()
            if os.path.exists(price_csv_path):
                price_df = pd.read_csv(price_csv_path)
                print(f"✅ Loaded price data from {price_csv_path}")
            
            financial_data_for_charts = {
                'analysis': analysis_df,
                'income_statement': income_df,
                'peer_data': {},
                'valuation_data': {}
            }
            
            # Generate EPS × PE chart (works with analysis_df)
            eps_pe_result = enhanced_chart_gen.generate_eps_pe_chart(
                analysis_df, args.company_ticker, output_dir
            )
            if eps_pe_result:
                enhanced_charts['eps_pe'] = eps_pe_result
                print(f"✅ Generated EPS × PE chart")
            
            # Generate charts that work with income_df if available
            if not income_df.empty:
                # Revenue YoY chart
                revenue_yoy_result = enhanced_chart_gen.generate_revenue_yoy_chart(
                    income_df, args.company_ticker, output_dir
                )
                if revenue_yoy_result:
                    enhanced_charts['revenue_yoy'] = revenue_yoy_result
                    print(f"✅ Generated Revenue YoY chart")
                
                # EBITDA Margin chart
                ebitda_margin_result = enhanced_chart_gen.generate_ebitda_margin_chart(
                    income_df, args.company_ticker, output_dir
                )
                if ebitda_margin_result:
                    enhanced_charts['ebitda_margin'] = ebitda_margin_result
                    print(f"✅ Generated EBITDA Margin chart")
            
            # ========== 高级图表生成 ==========
            print("Generating advanced charts...")
            
            # 1. 股价走势图（含移动平均线和成交量）
            if not price_df.empty:
                stock_price_path = os.path.join(output_dir, f"{args.company_ticker}_stock_price_chart.png")
                stock_price_result = generate_stock_price_chart(
                    price_df, stock_price_path, args.company_ticker, "1Y"
                )
                if stock_price_result:
                    enhanced_charts['stock_price'] = stock_price_result
                    print(f"✅ Generated Stock Price chart")
                
                # 2. 技术指标图（RSI, MACD）
                tech_indicators_path = os.path.join(output_dir, f"{args.company_ticker}_technical_indicators.png")
                tech_result = generate_technical_indicators_chart(
                    price_df, tech_indicators_path, args.company_ticker
                )
                if tech_result:
                    enhanced_charts['technical_indicators'] = tech_result
                    print(f"✅ Generated Technical Indicators chart")
            
            # 3. 财务比率雷达图
            financial_ratios = {}
            if analysis_df is not None and not analysis_df.empty:
                # 从分析数据中提取财务比率
                ratio_metrics = ['EBITDA Margin', 'Contribution Margin', 'SG&A Margin', 'Revenue Growth']
                year_cols = [col for col in analysis_df.columns if col.endswith('A')]
                if year_cols:
                    latest_year = sorted(year_cols)[-1]
                    for metric in ratio_metrics:
                        row = analysis_df[analysis_df['metrics'] == metric]
                        if not row.empty:
                            val = row[latest_year].iloc[0]
                            if isinstance(val, str):
                                val = val.replace('%', '')
                            try:
                                financial_ratios[metric] = float(val)
                            except:
                                pass
                
                # 添加其他比率
                if roe and roe != 'N/A':
                    try:
                        financial_ratios['ROE'] = float(str(roe).replace('%', ''))
                    except:
                        pass
                if fwd_pe and fwd_pe != 'N/A':
                    try:
                        financial_ratios['P/E Ratio'] = float(str(fwd_pe).replace('x', ''))
                    except:
                        pass
            
            if financial_ratios:
                radar_path = os.path.join(output_dir, f"{args.company_ticker}_financial_radar.png")
                radar_result = generate_financial_radar_chart(
                    financial_ratios, radar_path, args.company_ticker
                )
                if radar_result:
                    enhanced_charts['financial_radar'] = radar_result
                    print(f"✅ Generated Financial Radar chart")
            
            # 4. 敏感性热力图（如果有敏感性分析数据）
            if report_data.get('sensitivity_analysis'):
                sensitivity_data = report_data['sensitivity_analysis']
                if 'matrix' in sensitivity_data:
                    sensitivity_df = pd.DataFrame(sensitivity_data['matrix'])
                    heatmap_path = os.path.join(output_dir, f"{args.company_ticker}_sensitivity_heatmap.png")
                    heatmap_result = generate_sensitivity_heatmap(
                        sensitivity_df, heatmap_path, args.company_ticker
                    )
                    if heatmap_result:
                        enhanced_charts['sensitivity_heatmap'] = heatmap_result
                        print(f"✅ Generated Sensitivity Heatmap")
            
            # 5. 估值瀑布图（如果有估值分析数据）
            if report_data.get('valuation_analysis'):
                valuation_data = report_data['valuation_analysis']
                # 构建瀑布图数据
                waterfall_data = {}
                if 'ev_ebitda' in valuation_data:
                    waterfall_data['EV/EBITDA'] = valuation_data['ev_ebitda'].get('target_price', 0)
                if 'dcf' in valuation_data:
                    waterfall_data['DCF'] = valuation_data['dcf'].get('target_price', 0)
                if 'peer_comparison' in valuation_data:
                    waterfall_data['Peer Comp'] = valuation_data['peer_comparison'].get('target_price', 0)
                
                if waterfall_data:
                    waterfall_path = os.path.join(output_dir, f"{args.company_ticker}_valuation_waterfall.png")
                    waterfall_result = generate_valuation_waterfall_chart(
                        waterfall_data, waterfall_path, args.company_ticker
                    )
                    if waterfall_result:
                        enhanced_charts['valuation_waterfall'] = waterfall_result
                        print(f"✅ Generated Valuation Waterfall chart")
            
            # 6. 现金流分析图（如果有现金流数据）
            cashflow_csv_path = os.path.join(os.path.dirname(args.analysis_csv), "cash_flow_statement_raw_data.csv")
            if os.path.exists(cashflow_csv_path):
                try:
                    cashflow_df = pd.read_csv(cashflow_csv_path)
                    if not cashflow_df.empty:
                        # 提取现金流数据
                        cf_data = {
                            'periods': cashflow_df['calendarYear'].tolist() if 'calendarYear' in cashflow_df.columns else [],
                            'Operating': cashflow_df['operatingCashFlow'].tolist() if 'operatingCashFlow' in cashflow_df.columns else [],
                            'Investing': cashflow_df['netCashUsedForInvestingActivites'].tolist() if 'netCashUsedForInvestingActivites' in cashflow_df.columns else [],
                            'Financing': cashflow_df['netCashUsedProvidedByFinancingActivities'].tolist() if 'netCashUsedProvidedByFinancingActivities' in cashflow_df.columns else []
                        }
                        
                        if cf_data['Operating']:
                            cashflow_path = os.path.join(output_dir, f"{args.company_ticker}_cash_flow_chart.png")
                            cf_result = generate_cash_flow_chart(
                                cf_data, cashflow_path, args.company_ticker
                            )
                            if cf_result:
                                enhanced_charts['cash_flow'] = cf_result
                                print(f"✅ Generated Cash Flow chart")
                except Exception as e:
                    print(f"⚠️ Error generating cash flow chart: {e}")
            
            report_data['enhanced_charts'] = enhanced_charts
            print(f"✅ Generated {len(enhanced_charts)} enhanced charts total")
        except Exception as e:
            print(f"⚠️ Error generating enhanced charts: {e}")
            import traceback
            traceback.print_exc()
            report_data['enhanced_charts'] = {}

    # --- Valuation Analysis ---
    if args.enable_valuation_analysis:
        print("Performing valuation analysis...")
        try:
            # Prepare financial data for valuation engine
            financial_data_for_valuation = {
                'analysis': analysis_df,
                'current_price': float(share_price.replace('$', '').replace(',', '')) if isinstance(share_price, str) else share_price,
                'shares_outstanding': auto_fetched_metrics.get('shares_outstanding', 1e9)
            }
            
            # Prepare peer data if available
            peer_data_for_valuation = {}
            if peer_ev_ebitda_df is not None and not peer_ev_ebitda_df.empty:
                peer_data_for_valuation['ev_ebitda'] = peer_ev_ebitda_df
            
            valuation_engine = ValuationEngine(financial_data_for_valuation, peer_data_for_valuation)
            
            # Calculate different valuation methods
            valuation_results = {}
            
            # EV/EBITDA valuation
            ev_ebitda_result = valuation_engine.calculate_ev_ebitda_valuation()
            if ev_ebitda_result:
                valuation_results['ev_ebitda'] = {
                    'method': ev_ebitda_result.method,
                    'target_price': ev_ebitda_result.target_price,
                    'upside': ev_ebitda_result.upside_potential,
                    'confidence': ev_ebitda_result.confidence
                }
            
            report_data['valuation_analysis'] = valuation_results
            print(f"✅ Valuation analysis completed")
        except Exception as e:
            print(f"⚠️ Error performing valuation analysis: {e}")
            import traceback
            traceback.print_exc()
            report_data['valuation_analysis'] = {}

    # --- Load Enhanced Analysis Files ---
    import json
    
    # Load sensitivity analysis
    if args.sensitivity_analysis_file and os.path.exists(args.sensitivity_analysis_file):
        print(f"Loading sensitivity analysis from {args.sensitivity_analysis_file}...")
        try:
            with open(args.sensitivity_analysis_file, 'r', encoding='utf-8') as f:
                report_data['sensitivity_analysis'] = json.load(f)
            print("✅ Sensitivity analysis loaded")
        except Exception as e:
            print(f"⚠️ Error loading sensitivity analysis: {e}")
            report_data['sensitivity_analysis'] = {}
    
    # Load catalyst analysis
    if args.catalyst_analysis_file and os.path.exists(args.catalyst_analysis_file):
        print(f"Loading catalyst analysis from {args.catalyst_analysis_file}...")
        try:
            with open(args.catalyst_analysis_file, 'r', encoding='utf-8') as f:
                report_data['catalyst_analysis'] = json.load(f)
            print("✅ Catalyst analysis loaded")
        except Exception as e:
            print(f"⚠️ Error loading catalyst analysis: {e}")
            report_data['catalyst_analysis'] = {}
    
    # Load enhanced news
    if args.enhanced_news_file and os.path.exists(args.enhanced_news_file):
        print(f"Loading enhanced news from {args.enhanced_news_file}...")
        try:
            with open(args.enhanced_news_file, 'r', encoding='utf-8') as f:
                report_data['enhanced_news'] = json.load(f)
            print("✅ Enhanced news loaded")
        except Exception as e:
            print(f"⚠️ Error loading enhanced news: {e}")
            report_data['enhanced_news'] = {}

    # --- Format tables for HTML (EXCLUDE ESTIMATES FOR PAGE 3 TABLES) ---
    print("Formatting tables for HTML...")

    # For Page 3 tables, filter to only include actual years (no estimates)
    analysis_actual_only = filter_actual_years_only(analysis_df)

    summary_metrics = ["Revenue", "Revenue Growth", "EBITDA", "EBITDA Margin", "Contribution Profit", "Contribution Margin", "SG&A", "SG&A Margin"]
    financial_summary_df = analysis_actual_only[analysis_actual_only["metrics"].isin(summary_metrics)].set_index("metrics")
    report_data["financial_summary_table_html"] = format_dataframe_to_html_table(financial_summary_df, table_id="financial-summary")

    valuation_metrics = ["EBITDA Margin", "Contribution Margin", "SG&A Margin", "Revenue Growth"]
    valuation_metrics_df = analysis_actual_only[analysis_actual_only["metrics"].isin(valuation_metrics)].set_index("metrics")
    report_data["valuation_metrics_table_html"] = format_dataframe_to_html_table(valuation_metrics_df, table_id="valuation-metrics")

    # Load and format Credit & Cashflow metrics from the provided CSV
    print("Loading Credit & Cashflow metrics from CSV...")
    credit_cashflow_df = load_credit_cashflow_metrics_from_csv(args.ratios_csv)
    if not credit_cashflow_df.empty:
        credit_cashflow_actual = filter_actual_years_only(credit_cashflow_df)
        credit_cashflow_formatted = credit_cashflow_actual.set_index("metrics")
        report_data["credit_cashflow_table_html"] = format_dataframe_to_html_table(credit_cashflow_formatted, table_id="credit-cashflow")
        print("✅ Successfully loaded and formatted Credit & Cashflow metrics from CSV")
    else:
        report_data["credit_cashflow_table_html"] = "<p>Credit & Cashflow metrics not available.</p>"
        print("❌ Failed to load Credit & Cashflow metrics from CSV")


    # Handle peer data for tables - fix the filtering issue
    if peer_ebitda_df is not None and not peer_ebitda_df.empty:
        print(f"Processing peer EBITDA data with shape: {peer_ebitda_df.shape}")
        print(f"Peer EBITDA columns: {peer_ebitda_df.columns.tolist()}")

        if 'year' in peer_ebitda_df.columns:
            peer_ebitda_df.set_index('year', inplace=True)

        # Don't filter out estimates - show all available data
        print(f"Peer EBITDA index: {peer_ebitda_df.index.tolist()}")

        if not peer_ebitda_df.empty:
            report_data["peer_ebitda_table_html"] = format_dataframe_to_html_table(peer_ebitda_df.T, table_id="peer-ebitda-summary")
            print("✅ Successfully formatted peer EBITDA table")
        else:
            report_data["peer_ebitda_table_html"] = "<p>Peer EBITDA data not available.</p>"
            print("❌ Peer EBITDA DataFrame is empty")
    else:
        report_data["peer_ebitda_table_html"] = "<p>Peer EBITDA data not available.</p>"
        print("❌ No peer EBITDA data provided")

    if peer_ev_ebitda_df is not None and not peer_ev_ebitda_df.empty:
        print(f"Processing peer EV/EBITDA data with shape: {peer_ev_ebitda_df.shape}")
        print(f"Peer EV/EBITDA columns: {peer_ev_ebitda_df.columns.tolist()}")

        if 'year' in peer_ev_ebitda_df.columns:
            peer_ev_ebitda_df.set_index('year', inplace=True)

        # Don't filter out estimates - show all available data
        print(f"Peer EV/EBITDA index: {peer_ev_ebitda_df.index.tolist()}")

        if not peer_ev_ebitda_df.empty:
            report_data["peer_ev_ebitda_table_html"] = format_dataframe_to_html_table(peer_ev_ebitda_df.T, table_id="peer-ev-ebitda-summary")
            print("✅ Successfully formatted peer EV/EBITDA table")
        else:
            report_data["peer_ev_ebitda_table_html"] = "<p>Peer EV/EBITDA data not available.</p>"
            print("❌ Peer EV/EBITDA DataFrame is empty")
    else:
        report_data["peer_ev_ebitda_table_html"] = "<p>Peer EV/EBITDA data not available.</p>"
        print("❌ No peer EV/EBITDA data provided")

    # --- Generate Professional HTML Report (matching PDF structure) ---
    print("Generating professional HTML report (matching PDF structure)...")
    
    # Add additional data needed for professional template
    report_data['revenue_analysis_text'] = f"{report_data.get('company_name_full', 'The company')} has demonstrated consistent revenue performance over the analysis period. Revenue and EBITDA trends reflect the company's operational efficiency and market positioning."
    report_data['eps_analysis_text'] = f"{report_data.get('company_name_full', 'The company')}'s earnings trajectory reflects the company's profitability trends, while valuation multiples indicate market expectations for future growth."
    
    # Extract key figures from analysis_df
    if analysis_df is not None and not analysis_df.empty:
        years = [col for col in analysis_df.columns if col.endswith('A')]
        latest_year = years[-1] if years else None
        
        revenue_figures = {}
        eps_figures = {}
        
        if latest_year:
            for metric in ['Revenue', 'EBITDA', 'Revenue Growth']:
                row = analysis_df[analysis_df['metrics'] == metric]
                if not row.empty:
                    val = row[latest_year].values[0]
                    revenue_figures[f"{metric} ({latest_year})"] = str(val)
            
            for metric in ['EPS', 'PE Ratio']:
                row = analysis_df[analysis_df['metrics'] == metric]
                if not row.empty:
                    val = row[latest_year].values[0]
                    eps_figures[f"{metric} ({latest_year})"] = str(val)
        
        report_data['revenue_key_figures'] = revenue_figures
        report_data['eps_key_figures'] = eps_figures
    
    # Generate professional HTML report
    professional_html_path = os.path.join(output_dir, f"Professional_Equity_Report_{args.company_ticker}.html")
    professional_html_content = render_professional_html_report(report_data)
    with open(professional_html_path, "w", encoding="utf-8") as f:
        f.write(professional_html_content)
    print(f"✅ Generated Professional HTML Report: {professional_html_path}")

    # --- Generate Combined HTML Report (all sections in one file) ---
    print("Generating combined HTML report (all sections in one file)...")
    combined_html_path = os.path.join(output_dir, f"Combined_Equity_Report_{args.company_ticker}.html")
    combined_html_content = render_combined_html_report(report_data)
    with open(combined_html_path, "w", encoding="utf-8") as f:
        f.write(combined_html_content)
    print(f"✅ Generated Combined HTML Report: {combined_html_path}")

    # --- Also render legacy HTML pages for backward compatibility ---
    print("Rendering legacy HTML pages...")
    templates = [HTML_TEMPLATE_PAGE_1, HTML_TEMPLATE_PAGE_2_FINANCIAL_SUMMARY, HTML_TEMPLATE_PAGE_3_PEER_COMPARISON]
    
    # Add Page 4 (Sensitivity & Catalyst) if enabled
    has_sensitivity_catalyst = (
        report_data.get('sensitivity_analysis') or 
        report_data.get('catalyst_analysis')
    )
    if has_sensitivity_catalyst:
        templates.append(HTML_TEMPLATE_PAGE_4_SENSITIVITY_CATALYST)
        print("✅ Sensitivity/Catalyst content detected, adding Page 4")
    
    # Add Page 5 (News & Charts) if enabled
    has_news_charts = (
        report_data.get('enhanced_news') or 
        report_data.get('enhanced_charts')
    )
    if has_news_charts:
        templates.append(HTML_TEMPLATE_PAGE_5_NEWS_CHARTS)
        print("✅ News/Charts content detected, adding Page 5")
    
    for page_num, template in enumerate(templates, 1):
        page_path = os.path.join(output_dir, f"{args.html_report_prefix}_Page{page_num}_{args.company_ticker}.html")
        html_content = render_html_report(template, report_data)
        with open(page_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        print(f"Generated Page {page_num}: {page_path}")

    print(f"\n✅ Equity report generation complete!")
    print(f"📁 Reports saved to: {output_dir}")
    if auto_fetched_metrics:
        print(f"🤖 Market data automatically fetched from FMP API")


if __name__ == "__main__":
    main()