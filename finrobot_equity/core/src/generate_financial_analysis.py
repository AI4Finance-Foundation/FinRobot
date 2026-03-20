#!/usr/bin/env python
# coding: utf-8

import argparse
import os
import pandas as pd
import json 

from modules.common_utils import load_config, get_api_key
from modules.financial_data_processor import calculate_growth_and_forecasts, extract_historical_metrics_from_api_data
from modules.market_data_api import (
    get_comprehensive_financial_data,
    combine_peer_financial_data,
    project_ebitda_for_peers,
    get_company_news
)
from modules.text_generator_agents import generate_text_section

# 新增模块导入
from modules.sensitivity_analyzer import SensitivityAnalyzer
from modules.catalyst_analyzer import CatalystAnalyzer
from modules.news_integrator import NewsIntegrator, get_enhanced_company_news

def main():
    parser = argparse.ArgumentParser(description="Generate financial analysis data using FMP API instead of PDF extraction.")
    
    # Company Identifiers
    parser.add_argument("--company-ticker", type=str, required=True, help="Stock ticker (e.g., AAPL).")
    parser.add_argument("--company-name", type=str, required=True, help="Full company name (e.g., Apple Inc.).")
    
    # API Configuration
    parser.add_argument("--config-file", type=str, default=None, help="Path to the configuration file (e.g., config.ini).")
    parser.add_argument("--years-limit", type=int, default=5, help="Number of years of historical data to fetch.")
    
    # Output Configuration
    parser.add_argument("--output-dir", type=str, help="Directory to save all outputs. Default: ./output/[TICKER]/analysis/")
    parser.add_argument("--output-csv-name", type=str, default="financial_metrics_and_forecasts.csv", help="Name for the output CSV file.")

    # Peer Analysis
    parser.add_argument("--peer-tickers", type=str, nargs="*", default=[], help="List of peer tickers for comparative analysis (e.g., GOOG MSFT).")

    # Text Generation
    parser.add_argument("--generate-text-sections", action="store_true", help="Enable generation of text sections using OpenAI.")
    parser.add_argument("--text-output-dir", type=str, default=None, help="Directory to save generated text files.")

    # NEWS PARAMETERS
    parser.add_argument("--news-days-back", type=int, default=5, help="Number of days to look back for company news (default: 5)")
    parser.add_argument("--news-limit", type=int, default=50, help="Maximum number of news articles to fetch (default: 50)")

    # 新增分析选项
    parser.add_argument("--enable-sensitivity-analysis", action="store_true", help="Enable sensitivity analysis for forecasts")
    parser.add_argument("--enable-catalyst-analysis", action="store_true", help="Enable catalyst identification and analysis")
    parser.add_argument("--enable-enhanced-news", action="store_true", help="Enable enhanced news integration with categorization")

    # Forecast Configuration
    parser.add_argument("--revenue-growth-2025", type=float, default=0.05, help="Revenue growth assumption for 2025E (default: 5%)")
    parser.add_argument("--revenue-growth-2026", type=float, default=0.06, help="Revenue growth assumption for 2026E (default: 6%)")
    parser.add_argument("--revenue-growth-2027", type=float, default=0.04, help="Revenue growth assumption for 2027E (default: 4%)")
    parser.add_argument("--margin-improvement", type=float, default=0.01, help="Annual margin improvement assumption (default: 1%)")
    parser.add_argument("--sga-margin-improvement", type=float, default=-0.005, help="SG&A margin change assumption (default: -0.5% efficiency gain)")

    # API Options
    parser.add_argument("--period", type=str, default="annual", choices=["annual", "quarterly"], help="Data period (annual or quarterly)")

    args = parser.parse_args()

    # Setup output directory
    if args.output_dir:
        output_dir = args.output_dir
    else:
        output_dir = os.path.join(".", "output", args.company_ticker, "analysis")
    os.makedirs(output_dir, exist_ok=True)
    print(f"Output will be saved to: {output_dir}")

    # Text output directory
    text_output_dir = args.text_output_dir if args.text_output_dir else output_dir
    if args.generate_text_sections:
        os.makedirs(text_output_dir, exist_ok=True)
        print(f"Text outputs will be saved to: {text_output_dir}")

    # Load configuration and API keys
    openai_base_url = None
    try:
        config = load_config(args.config_file)
        fmp_api_key = get_api_key(config, section="API_KEYS", key="fmp_api_key")
        if args.generate_text_sections:
            openai_api_key = get_api_key(config, section="API_KEYS", key="openai_api_key")
            # Try to get base_url for proxy services (like SiliconFlow)
            try:
                openai_base_url = get_api_key(config, section="API_KEYS", key="openai_base_url")
                print(f"Using OpenAI base URL: {openai_base_url}")
            except:
                pass  # base_url is optional
            # Try to get model name for proxy services
            try:
                openai_model = get_api_key(config, section="API_KEYS", key="openai_model")
                print(f"Using model: {openai_model}")
            except:
                openai_model = None  # model is optional
    except Exception as e:
        print(f"Error loading configuration: {e}")
        print("Please ensure config.ini exists with valid API keys:")
        print("[API_KEYS]")
        print("fmp_api_key = YOUR_FMP_API_KEY")
        print("openai_api_key = YOUR_OPENAI_API_KEY")
        print("openai_base_url = https://api.xxx.com/v1  # optional, for proxy services")
        return

    print(f"Starting FMP API-based financial analysis for {args.company_name} ({args.company_ticker})")

    # 1. Fetch Financial Data from FMP API
    print(f"Fetching financial data from FMP API...")
    financial_data = get_comprehensive_financial_data(
        ticker=args.company_ticker, 
        api_key=fmp_api_key, 
        period=args.period, 
        limit=args.years_limit
    )

    # Check if we got the required data
    if financial_data.get('income_statement') is None or financial_data['income_statement'].empty:
        print("Error: Could not fetch income statement data from FMP API. Exiting.")
        print("Please check:")
        print("1. FMP API key is valid and has remaining quota")
        print("2. Ticker symbol is correct") 
        print("3. Internet connection is working")
        return

    print("Successfully fetched financial data from FMP API")
    income_df = financial_data['income_statement']
    print(f"Retrieved {len(income_df)} years of income statement data")
    
    # Display available years for confirmation
    available_years = sorted(income_df['year'].tolist(), reverse=True)
    print(f"Available years: {available_years}")

    # 2. Process Historical Metrics
    print("Processing historical financial metrics...")
    historical_metrics_df = extract_historical_metrics_from_api_data(financial_data)

    if historical_metrics_df is None or historical_metrics_df.empty:
        print("Error: Failed to process historical metrics from API data. Exiting.")
        return
    
    print("\nHistorical Metrics Extracted from API:")
    print(historical_metrics_df.to_string())

    # 3. Forecasting
    print("Generating forecasts...")
    
    # Determine the latest actual year for base year
    actual_years = [col for col in historical_metrics_df.columns if col.endswith("A") and col != "metrics"]
    latest_year = max(actual_years) if actual_years else "2024A"
    
    print(f"Using {latest_year} as base year for forecasts")
    
    forecast_config = {
        "revenue_base_year": latest_year,
        "revenue_growth_assumptions": {
            "2025E": args.revenue_growth_2025, 
            "2026E": args.revenue_growth_2026, 
            "2027E": args.revenue_growth_2027
        }, 
        "ebitda_growth_factor": 1.05,
        "margin_improvement": {
            "Contribution Margin": args.margin_improvement, 
            "EBITDA Margin": args.margin_improvement
        },
        "sga_margin_change": args.sga_margin_improvement
    }
    
    print(f"Forecast assumptions:")
    print(f"  Revenue Growth 2025E: {args.revenue_growth_2025*100:.1f}%")
    print(f"  Revenue Growth 2026E: {args.revenue_growth_2026*100:.1f}%") 
    print(f"  Revenue Growth 2027E: {args.revenue_growth_2027*100:.1f}%")
    print(f"  Margin Improvement: {args.margin_improvement*100:.1f}% annually")
    print(f"  SG&A Efficiency: {args.sga_margin_improvement*100:.1f}% annually")
    
    final_data_df = calculate_growth_and_forecasts(historical_metrics_df, forecast_config)
    print("\nFinal Metrics with Forecasts:")
    print(final_data_df.to_string())

    # Save the main analysis file
    output_csv_path = os.path.join(output_dir, args.output_csv_name)
    final_data_df.to_csv(output_csv_path, index=False)
    print(f"Successfully saved financial analysis to: {output_csv_path}")

    # 4. Peer Comparison Analysis
    projected_peer_ebitda = None
    df_ev_ebitda_peers = None
    if args.peer_tickers and fmp_api_key:
        print(f"\nFetching data for peer comparison: {args.peer_tickers}")
        all_tickers = args.peer_tickers + [args.company_ticker]
        
        try:
            df_ebitda_peers, df_ev_ebitda_peers = combine_peer_financial_data(
                all_tickers, fmp_api_key, years_limit=args.years_limit
            )
            
            if df_ebitda_peers is not None and not df_ebitda_peers.empty:
                projected_peer_ebitda = project_ebitda_for_peers(df_ebitda_peers, num_projection_years=1)
                peer_ebitda_path = os.path.join(output_dir, "peer_ebitda_comparison.csv")
                projected_peer_ebitda.to_csv(peer_ebitda_path)
                print(f"Saved peer EBITDA comparison to: {peer_ebitda_path}")
            else:
                print("Warning: No peer EBITDA data could be retrieved")
            
            if df_ev_ebitda_peers is not None and not df_ev_ebitda_peers.empty:
                peer_ev_ebitda_path = os.path.join(output_dir, "peer_ev_ebitda_comparison.csv")
                df_ev_ebitda_peers.to_csv(peer_ev_ebitda_path)
                print(f"Saved peer EV/EBITDA comparison to: {peer_ev_ebitda_path}")
            else:
                print("Warning: No peer EV/EBITDA data could be retrieved")
                
        except Exception as e:
            print(f"Error fetching peer data: {e}")
            print("Continuing without peer comparison...")
    else:
        print("Skipping peer comparison (no peer tickers provided)")

    # 4.5 Fetch Company News
    company_news = None
    enhanced_news_data = None
    if fmp_api_key:
        print(f"\nFetching company news for {args.company_ticker}...")
        try:
            if args.enable_enhanced_news:
                # 使用增强版新闻获取
                enhanced_news_data = get_enhanced_company_news(
                    ticker=args.company_ticker,
                    api_key=fmp_api_key,
                    days_back=args.news_days_back,
                    limit=args.news_limit
                )
                company_news = enhanced_news_data.get('articles', [])
                
                # 保存增强版新闻数据
                enhanced_news_path = os.path.join(output_dir, "enhanced_news.json")
                with open(enhanced_news_path, 'w', encoding='utf-8') as f:
                    json.dump(enhanced_news_data, f, indent=2, ensure_ascii=False)
                print(f"Saved enhanced news data to: {enhanced_news_path}")
                
                # 保存新闻摘要
                news_summary_path = os.path.join(output_dir, "news_summary.md")
                with open(news_summary_path, 'w', encoding='utf-8') as f:
                    f.write(enhanced_news_data.get('summary', ''))
                print(f"Saved news summary to: {news_summary_path}")
            else:
                # 使用原始新闻获取
                company_news = get_company_news(
                    ticker=args.company_ticker,
                    api_key=fmp_api_key,
                    days_back=args.news_days_back,
                    limit=args.news_limit
                )
            
            if company_news:
                news_output_path = os.path.join(output_dir, "company_news.json")
                with open(news_output_path, 'w', encoding='utf-8') as f:
                    json.dump(company_news, f, indent=2, ensure_ascii=False)
                print(f"Saved company news to: {news_output_path}")
            else:
                print("Warning: No news data could be retrieved")
        except Exception as e:
            print(f"Error fetching company news: {e}")
            print("Continuing without news data...")
    else:
        print("Skipping news fetch (no FMP API key)")

    # 4.6 敏感性分析
    sensitivity_results = None
    if args.enable_sensitivity_analysis:
        print(f"\nPerforming sensitivity analysis...")
        try:
            sensitivity_analyzer = SensitivityAnalyzer(final_data_df)
            
            # 收入敏感性分析
            revenue_sensitivity = sensitivity_analyzer.analyze_revenue_sensitivity()
            
            # 利润率敏感性分析
            margin_sensitivity = sensitivity_analyzer.analyze_margin_sensitivity()
            
            # 综合敏感性表格
            combined_sensitivity = sensitivity_analyzer.generate_sensitivity_table()
            
            # 置信区间
            revenue_ci = sensitivity_analyzer.calculate_confidence_interval('Revenue')
            ebitda_ci = sensitivity_analyzer.calculate_confidence_interval('EBITDA')
            
            sensitivity_results = {
                'revenue_sensitivity': revenue_sensitivity.to_dict() if not revenue_sensitivity.empty else {},
                'margin_sensitivity': margin_sensitivity.to_dict() if not margin_sensitivity.empty else {},
                'combined_sensitivity': combined_sensitivity.to_dict() if not combined_sensitivity.empty else {},
                'confidence_intervals': sensitivity_analyzer.confidence_intervals,
                'summary': sensitivity_analyzer.generate_sensitivity_summary()
            }
            
            # 保存敏感性分析结果
            sensitivity_path = os.path.join(output_dir, "sensitivity_analysis.json")
            with open(sensitivity_path, 'w', encoding='utf-8') as f:
                json.dump(sensitivity_results, f, indent=2, default=str)
            print(f"Saved sensitivity analysis to: {sensitivity_path}")
            
            # 保存敏感性摘要
            sensitivity_summary_path = os.path.join(output_dir, "sensitivity_summary.md")
            with open(sensitivity_summary_path, 'w', encoding='utf-8') as f:
                f.write(sensitivity_results['summary'])
            print(f"Saved sensitivity summary to: {sensitivity_summary_path}")
            
        except Exception as e:
            print(f"Error performing sensitivity analysis: {e}")
            print("Continuing without sensitivity analysis...")

    # 4.7 催化剂分析
    catalyst_results = None
    if args.enable_catalyst_analysis and company_news:
        print(f"\nPerforming catalyst analysis...")
        try:
            catalyst_analyzer = CatalystAnalyzer(args.company_ticker, fmp_api_key)
            
            # 识别催化剂
            catalysts = catalyst_analyzer.identify_catalysts(company_news)
            
            # 分类催化剂
            categorized_catalysts = catalyst_analyzer.categorize_catalysts()
            
            # 获取顶级催化剂
            top_catalysts = catalyst_analyzer.get_top_catalysts(5)
            
            # 生成摘要
            catalyst_summary = catalyst_analyzer.generate_catalyst_summary()
            
            catalyst_results = {
                'catalysts': [
                    {
                        'event_type': c.event_type,
                        'description': c.description,
                        'expected_date': c.expected_date,
                        'impact_level': c.impact_level,
                        'probability': c.probability,
                        'sentiment': c.sentiment
                    }
                    for c in catalysts
                ],
                'categorized': {
                    k: [{'description': c.description, 'impact': c.impact_level} for c in v]
                    for k, v in categorized_catalysts.items()
                },
                'top_catalysts': top_catalysts,
                'summary': catalyst_summary
            }
            
            # 保存催化剂分析结果
            catalyst_path = os.path.join(output_dir, "catalyst_analysis.json")
            with open(catalyst_path, 'w', encoding='utf-8') as f:
                json.dump(catalyst_results, f, indent=2, default=str)
            print(f"Saved catalyst analysis to: {catalyst_path}")
            
            # 保存催化剂摘要
            catalyst_summary_path = os.path.join(output_dir, "catalyst_summary.md")
            with open(catalyst_summary_path, 'w', encoding='utf-8') as f:
                f.write(catalyst_summary)
            print(f"Saved catalyst summary to: {catalyst_summary_path}")
            
        except Exception as e:
            print(f"Error performing catalyst analysis: {e}")
            print("Continuing without catalyst analysis...")

    # 5. Text Generation (Unified Logic)
    if args.generate_text_sections:
        print("\nGenerating AI-powered text sections...")
        
        if 'openai_api_key' not in locals() or not openai_api_key:
            print("Error: OpenAI API key not loaded. Skipping text generation.")
        else:
            data_for_text_gen = {
                "financial_metrics": final_data_df,
                "peer_ebitda": projected_peer_ebitda,
                "peer_ev_ebitda": df_ev_ebitda_peers,
                "company_news": company_news,
                "enhanced_news": enhanced_news_data,
                "sensitivity_analysis": sensitivity_results,
                "catalyst_analysis": catalyst_results
            }
            
            # A single list for all text types to be generated (including news_summary)
            all_text_types = [
                "tagline", "company_overview", "investment_overview", 
                "valuation_overview", "risks", "competitor_analysis", 
                "major_takeaways", "news_summary"  # NEW
            ]
            
            # A single loop calling the unified generation function
            for text_type in all_text_types:
                # Skip news_summary if no news data available
                if text_type == "news_summary" and not company_news:
                    print(f"Skipping 'news_summary' - no news data available")
                    # Create placeholder file
                    fallback_text = f"No recent news available for {args.company_name} ({args.company_ticker})."
                    file_path = os.path.join(text_output_dir, f"{text_type}.txt")
                    with open(file_path, "w", encoding="utf-8") as f:
                        f.write(fallback_text)
                    print(f"Created placeholder for '{text_type}' at {file_path}")
                    continue
                
                print(f"Generating '{text_type}' for {args.company_name} ({args.company_ticker})...")
                try:
                    # Call the single, unified function for all types
                    generated_text = generate_text_section(
                        data_for_text_gen, 
                        text_type, 
                        openai_api_key, 
                        args.company_name, 
                        args.company_ticker,
                        base_url=openai_base_url,
                        model=openai_model
                    )
                    
                    # Fallback validation can remain here as a safety net
                    if text_type == "competitor_analysis" and (not generated_text or len(generated_text.split('.')) < 3):
                         print(f"⚠️ Warning: Competitor analysis seems too short, using fallback.")
                         generated_text = f"{args.company_name} demonstrates competitive positioning within its industry sector through consistent financial performance and strategic market positioning relative to key competitors."
                    
                    elif text_type == "major_takeaways" and "Revenue Growth:" not in generated_text:
                         print(f"⚠️ Warning: Major takeaways missing required sections, using fallback.")
                         generated_text = f"Revenue Growth: {args.company_name}'s revenue growth shows consistent performance trends.\n\nGross Profit Margin: {args.company_name}'s gross profit margins demonstrate operational effectiveness.\n\nSG&A Expense Margin: {args.company_name}'s SG&A expense management shows disciplined cost control.\n\nEBITDA Margin Stability: {args.company_name}'s EBITDA margin stability reflects strong underlying fundamentals."

                    elif text_type == "news_summary" and (not generated_text or len(generated_text.split()) < 50):
                        print(f"⚠️ Warning: News summary seems too short, using fallback.")
                        generated_text = f"Recent news coverage for {args.company_name} reflects ongoing market interest and developments in the company's operations and strategic initiatives."

                    file_path = os.path.join(text_output_dir, f"{text_type}.txt")
                    with open(file_path, "w", encoding="utf-8") as f:
                        f.write(generated_text)
                    print(f"✅ Successfully generated and saved '{text_type}' to {file_path}")
                    
                except Exception as e:
                    print(f"Error generating text for '{text_type}': {e}")
                    # Create a fallback file if generation fails
                    fallback_text = f"{args.company_name} ({args.company_ticker}) {text_type.replace('_', ' ')} analysis not available."
                    file_path = os.path.join(text_output_dir, f"{text_type}.txt")
                    with open(file_path, "w", encoding="utf-8") as f:
                        f.write(fallback_text)
                    print(f"Created fallback text for '{text_type}' at {file_path}")
    else:
        print("Skipping text generation (not enabled)")

    # 6. Save additional financial statement data for reference
    print("\nSaving additional financial statement data...")
    
    for statement_name, df in financial_data.items():
        if df is not None and not df.empty:
            statement_path = os.path.join(output_dir, f"{statement_name}_raw_data.csv")
            df.to_csv(statement_path, index=False)
            print(f"Saved {statement_name} to: {statement_path} ({len(df)} rows)")

    # 7. Create summary report
    all_text_types = ["tagline", "company_overview", "investment_overview", "valuation_overview", "risks", "competitor_analysis", "major_takeaways", "news_summary"]
    
    summary_data = {
        "company_ticker": args.company_ticker,
        "company_name": args.company_name,
        "analysis_date": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
        "data_source": "Financial Modeling Prep API",
        "data_period": args.period,
        "years_analyzed": len(actual_years),
        "available_years": available_years,
        "latest_year": latest_year,
        "forecast_years": list(forecast_config["revenue_growth_assumptions"].keys()),
        "peer_tickers": args.peer_tickers,
        "news_days_back": args.news_days_back,
        "news_articles_fetched": len(company_news) if company_news else 0,
        "enhanced_news_enabled": args.enable_enhanced_news,
        "sensitivity_analysis_enabled": args.enable_sensitivity_analysis,
        "catalyst_analysis_enabled": args.enable_catalyst_analysis,
        "forecast_config": forecast_config,
        "files_generated": {
            "main_analysis": args.output_csv_name,
            "peer_ebitda": "peer_ebitda_comparison.csv" if projected_peer_ebitda is not None else None,
            "peer_ev_ebitda": "peer_ev_ebitda_comparison.csv" if df_ev_ebitda_peers is not None else None,
            "company_news": "company_news.json" if company_news else None,
            "enhanced_news": "enhanced_news.json" if enhanced_news_data else None,
            "sensitivity_analysis": "sensitivity_analysis.json" if sensitivity_results else None,
            "catalyst_analysis": "catalyst_analysis.json" if catalyst_results else None,
            "text_sections": all_text_types if args.generate_text_sections else []
        }
    }
    
    summary_path = os.path.join(output_dir, "analysis_summary.json")
    with open(summary_path, "w") as f:
        json.dump(summary_data, f, indent=2, default=str)
    print(f"Saved analysis summary to: {summary_path}")

    # 8. Print final summary and next steps
    print(f"\n" + "="*60)
    print(f"✅ Financial analysis completed successfully!")
    print(f"📁 All outputs saved to: {output_dir}")
    print(f"📊 Main analysis file: {output_csv_path}")
    if args.generate_text_sections:
        print(f"📝 AI text sections generated and saved in: {text_output_dir}")
    
    print(f"\n🚀 Ready to create equity report using:")
    print(f"python create_equity_report.py \\")
    print(f"  --company-ticker {args.company_ticker} \\")
    print(f"  --company-name \"{args.company_name}\" \\")
    print(f"  --analysis-csv {output_csv_path} \\")
    print(f"  --ratios-csv {os.path.join(output_dir, 'ratios_raw_data.csv')} \\")
    
    if args.peer_tickers and projected_peer_ebitda is not None:
        print(f"  --peer-ebitda-csv {os.path.join(output_dir, 'peer_ebitda_comparison.csv')} \\")
    if args.peer_tickers and df_ev_ebitda_peers is not None:
        print(f"  --peer-ev-ebitda-csv {os.path.join(output_dir, 'peer_ev_ebitda_comparison.csv')} \\")
    
    if args.generate_text_sections:
        for i, text_type in enumerate(all_text_types):
            param_name = text_type.replace('_', '-')
            file_path = os.path.join(text_output_dir, f'{text_type}.txt')
            # Add backslash for line continuation, except for the last item
            continuation = " \\" if i < len(all_text_types) - 1 else ""
            print(f"  --{param_name}-file {file_path}{continuation}")
    
    print(f"\n🎯 All files ready for report generation!")


if __name__ == "__main__":
    main()