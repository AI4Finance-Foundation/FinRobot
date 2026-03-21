#!/usr/bin/env python
# coding: utf-8
"""
专业股票研究报告PDF生成器 - 主入口脚本
根据用户样式规范生成3页A4 PDF报告

使用方法:
    python generate_pdf_report.py --company-ticker AAPL --company-name "Apple Inc."
    
或者使用预生成的分析数据:
    python generate_pdf_report.py --company-ticker AAPL --company-name "Apple Inc." --analysis-dir ./output/AAPL/analysis
"""

import argparse
import os
import sys
import json
from datetime import datetime
from typing import Dict, Any, Optional

import pandas as pd

# 添加模块路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from modules.common_utils import load_config, get_api_key
from modules.report_data_loader import load_analysis_csv, load_text_from_file
from modules.chart_generator import (
    generate_revenue_ebitda_chart, 
    generate_ev_ebitda_peer_chart, 
    generate_eps_pe_chart,
    generate_margin_trend_chart,
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
from modules.market_data_api import get_comprehensive_company_metrics, get_technical_indicators
from modules.pdf_generator import generate_equity_report_pdf
from modules.professional_pdf_report import generate_professional_report


def load_analysis_data(analysis_dir: str, ticker: str) -> Dict[str, Any]:
    """
    从分析目录加载所有数据文件
    
    Args:
        analysis_dir: 分析数据目录路径
        ticker: 股票代码
    
    Returns:
        包含所有数据的字典
    """
    data = {}
    
    # 加载主分析CSV
    analysis_csv_path = os.path.join(analysis_dir, "financial_metrics_and_forecasts.csv")
    if os.path.exists(analysis_csv_path):
        data['analysis_df'] = load_analysis_csv(analysis_csv_path)
        print(f"✅ Loaded financial metrics from {analysis_csv_path}")
    else:
        print(f"⚠️ Financial metrics CSV not found: {analysis_csv_path}")
        data['analysis_df'] = pd.DataFrame()
    
    # 加载财务比率CSV
    ratios_csv_path = os.path.join(analysis_dir, "ratios_raw_data.csv")
    if os.path.exists(ratios_csv_path):
        data['ratios_df'] = pd.read_csv(ratios_csv_path)
        print(f"✅ Loaded ratios data from {ratios_csv_path}")
    else:
        data['ratios_df'] = pd.DataFrame()
    
    # 加载价格数据（用于高级图表）
    price_csv_path = os.path.join(analysis_dir, "historical_price_full.csv")
    if os.path.exists(price_csv_path):
        data['price_df'] = pd.read_csv(price_csv_path)
        print(f"✅ Loaded price data from {price_csv_path}")
    else:
        data['price_df'] = pd.DataFrame()
    
    # 加载现金流数据（用于高级图表）
    cashflow_csv_path = os.path.join(analysis_dir, "cash_flow_statement_raw_data.csv")
    if os.path.exists(cashflow_csv_path):
        data['cashflow_df'] = pd.read_csv(cashflow_csv_path)
        print(f"✅ Loaded cash flow data from {cashflow_csv_path}")
    else:
        data['cashflow_df'] = pd.DataFrame()
    
    # 加载同行对比数据
    peer_ebitda_path = os.path.join(analysis_dir, "peer_ebitda_comparison.csv")
    if os.path.exists(peer_ebitda_path):
        data['peer_ebitda_df'] = pd.read_csv(peer_ebitda_path)
        print(f"✅ Loaded peer EBITDA data")
    else:
        data['peer_ebitda_df'] = pd.DataFrame()
    
    peer_ev_ebitda_path = os.path.join(analysis_dir, "peer_ev_ebitda_comparison.csv")
    if os.path.exists(peer_ev_ebitda_path):
        data['peer_ev_ebitda_df'] = pd.read_csv(peer_ev_ebitda_path)
        if 'year' in data['peer_ev_ebitda_df'].columns:
            data['peer_ev_ebitda_df'].set_index('year', inplace=True)
        print(f"✅ Loaded peer EV/EBITDA data")
    else:
        data['peer_ev_ebitda_df'] = pd.DataFrame()
    
    # 加载文本内容
    text_files = {
        'tagline': 'tagline.txt',
        'company_overview': 'company_overview.txt',
        'investment_overview': 'investment_overview.txt',
        'valuation_overview': 'valuation_overview.txt',
        'risks': 'risks.txt',
        'competitor_analysis': 'competitor_analysis.txt',
        'major_takeaways': 'major_takeaways.txt',
        'news_summary': 'news_summary.txt',
    }
    
    for key, filename in text_files.items():
        file_path = os.path.join(analysis_dir, filename)
        if os.path.exists(file_path):
            data[key] = load_text_from_file(file_path)
            print(f"✅ Loaded {key}")
        else:
            data[key] = ""
            print(f"⚠️ {filename} not found")
    
    # 加载分析摘要JSON
    summary_path = os.path.join(analysis_dir, "analysis_summary.json")
    if os.path.exists(summary_path):
        with open(summary_path, 'r', encoding='utf-8') as f:
            data['analysis_summary'] = json.load(f)
        print(f"✅ Loaded analysis summary")
    else:
        data['analysis_summary'] = {}
    
    # 加载增强分析数据
    # 敏感性分析
    sensitivity_path = os.path.join(analysis_dir, "sensitivity_analysis.json")
    if os.path.exists(sensitivity_path):
        with open(sensitivity_path, 'r', encoding='utf-8') as f:
            data['sensitivity_analysis'] = json.load(f)
        print(f"✅ Loaded sensitivity analysis")
    else:
        data['sensitivity_analysis'] = {}
    
    # 催化剂分析
    catalyst_path = os.path.join(analysis_dir, "catalyst_analysis.json")
    if os.path.exists(catalyst_path):
        with open(catalyst_path, 'r', encoding='utf-8') as f:
            data['catalyst_analysis'] = json.load(f)
        print(f"✅ Loaded catalyst analysis")
    else:
        data['catalyst_analysis'] = {}
    
    # 增强新闻数据
    enhanced_news_path = os.path.join(analysis_dir, "enhanced_news.json")
    if os.path.exists(enhanced_news_path):
        with open(enhanced_news_path, 'r', encoding='utf-8') as f:
            data['enhanced_news'] = json.load(f)
        print(f"✅ Loaded enhanced news")
    else:
        data['enhanced_news'] = {}
    
    # 公司新闻
    company_news_path = os.path.join(analysis_dir, "company_news.json")
    if os.path.exists(company_news_path):
        with open(company_news_path, 'r', encoding='utf-8') as f:
            data['company_news'] = json.load(f)
        print(f"✅ Loaded company news")
    else:
        data['company_news'] = []
    
    return data


def prepare_financial_summary_df(analysis_df: pd.DataFrame) -> pd.DataFrame:
    """
    准备财务摘要表格数据
    """
    if analysis_df is None or analysis_df.empty:
        return pd.DataFrame()
    
    # 选择要显示的指标
    summary_metrics = [
        "Revenue", "Revenue Growth", "EBITDA", "EBITDA Margin",
        "Contribution Profit", "Contribution Margin", "SG&A", "SG&A Margin",
        "EPS", "PE Ratio"
    ]
    
    # 过滤存在的指标
    available_metrics = [m for m in summary_metrics if m in analysis_df['metrics'].values]
    
    if not available_metrics:
        return pd.DataFrame()
    
    # 筛选数据
    df = analysis_df[analysis_df['metrics'].isin(available_metrics)].copy()
    df.set_index('metrics', inplace=True)
    
    # 只保留实际年份列 (以A结尾)
    year_cols = [col for col in df.columns if col.endswith('A')]
    if not year_cols:
        year_cols = [col for col in df.columns if col not in ['metrics', 'CAGR']]
    
    return df[year_cols]


def prepare_credit_metrics_df(ratios_df: pd.DataFrame) -> pd.DataFrame:
    """
    准备信用指标表格数据
    """
    if ratios_df is None or ratios_df.empty:
        return pd.DataFrame()
    
    # 定义要提取的指标映射
    metric_mapping = {
        'debtEquityRatio': 'Debt/Equity',
        'debtRatio': 'Debt/Assets',
        'interestCoverage': 'Interest Coverage',
        'netProfitMargin': 'Net Margin',
        'currentRatio': 'Current Ratio',
        'cashFlowToDebtRatio': 'CF to Debt Ratio'
    }
    
    if 'calendarYear' not in ratios_df.columns:
        return pd.DataFrame()
    
    # 按年份排序
    ratios_df = ratios_df.sort_values(by='calendarYear').reset_index(drop=True)
    
    # 构建新的DataFrame
    result_data = {'Metrics': list(metric_mapping.values())}
    
    for year in ratios_df['calendarYear'].unique():
        year_str = f"{int(year)}A"
        year_data = ratios_df[ratios_df['calendarYear'] == year].iloc[0]
        
        values = []
        for csv_col, display_name in metric_mapping.items():
            if csv_col in year_data and pd.notna(year_data[csv_col]):
                val = year_data[csv_col]
                if csv_col == 'interestCoverage':
                    values.append(f"{val:.1f}x")
                elif csv_col == 'netProfitMargin':
                    values.append(f"{val*100:.1f}%")
                elif csv_col in ['currentRatio', 'cashFlowToDebtRatio']:
                    values.append(f"{val:.2f}")
                else:
                    values.append(f"{val:.2f}")
            else:
                values.append("N/A")
        
        result_data[year_str] = values
    
    result_df = pd.DataFrame(result_data)
    result_df.set_index('Metrics', inplace=True)
    
    return result_df


def generate_all_charts(analysis_df: pd.DataFrame, peer_ev_ebitda_df: pd.DataFrame,
                       output_dir: str, ticker: str, 
                       price_df: pd.DataFrame = None,
                       ratios_df: pd.DataFrame = None,
                       cashflow_df: pd.DataFrame = None) -> Dict[str, str]:
    """
    生成所有图表（包括高级图表）
    
    Returns:
        包含图表路径的字典
    """
    charts = {}
    
    # 确保输出目录存在
    os.makedirs(output_dir, exist_ok=True)
    
    # ========== 基础图表 ==========
    # 1. Revenue & EBITDA 图表
    revenue_chart_path = os.path.join(output_dir, f"{ticker}_revenue_ebitda_chart.png")
    charts['revenue_chart_path'] = generate_revenue_ebitda_chart(
        analysis_df, revenue_chart_path, ticker
    ) or ""
    
    # 2. EPS × PE 图表
    eps_pe_chart_path = os.path.join(output_dir, f"{ticker}_eps_pe_chart.png")
    charts['eps_pe_chart_path'] = generate_eps_pe_chart(
        analysis_df, eps_pe_chart_path, ticker
    ) or ""
    
    # 3. EV/EBITDA 同行对比图表
    if peer_ev_ebitda_df is not None and not peer_ev_ebitda_df.empty:
        ev_chart_path = os.path.join(output_dir, f"{ticker}_peer_ev_ebitda_chart.png")
        charts['ev_ebitda_chart_path'] = generate_ev_ebitda_peer_chart(
            peer_ev_ebitda_df, ev_chart_path, ticker
        ) or ""
    else:
        charts['ev_ebitda_chart_path'] = ""
    
    # 4. 利润率趋势图
    margin_chart_path = os.path.join(output_dir, f"{ticker}_margin_trend_chart.png")
    charts['margin_chart_path'] = generate_margin_trend_chart(
        analysis_df, margin_chart_path, ticker
    ) or ""
    
    # ========== 高级图表 ==========
    print("Generating advanced charts...")
    
    # 5. 股价走势图（含移动平均线和成交量）
    if price_df is not None and not price_df.empty:
        stock_price_path = os.path.join(output_dir, f"{ticker}_stock_price_chart.png")
        charts['stock_price_chart_path'] = generate_stock_price_chart(
            price_df, stock_price_path, ticker, "1Y"
        ) or ""
        if charts['stock_price_chart_path']:
            print(f"✅ Generated Stock Price chart")
        
        # 6. 技术指标图（RSI, MACD）
        tech_indicators_path = os.path.join(output_dir, f"{ticker}_technical_indicators.png")
        charts['technical_indicators_path'] = generate_technical_indicators_chart(
            price_df, tech_indicators_path, ticker
        ) or ""
        if charts['technical_indicators_path']:
            print(f"✅ Generated Technical Indicators chart")
    
    # 7. 财务比率雷达图
    if ratios_df is not None and not ratios_df.empty:
        # 从比率数据中提取最新年份的财务比率
        financial_ratios = {}
        latest_ratios = ratios_df.sort_values('calendarYear', ascending=False).iloc[0] if 'calendarYear' in ratios_df.columns else ratios_df.iloc[0]
        
        ratio_mapping = {
            'returnOnEquity': 'ROE',
            'returnOnAssets': 'ROA',
            'grossProfitMargin': 'Gross Margin',
            'netProfitMargin': 'Net Margin',
            'currentRatio': 'Current Ratio',
            'debtEquityRatio': 'Debt/Equity'
        }
        
        for csv_col, display_name in ratio_mapping.items():
            if csv_col in latest_ratios and pd.notna(latest_ratios[csv_col]):
                val = latest_ratios[csv_col]
                # 转换为百分比形式（如果是小数）
                if csv_col in ['returnOnEquity', 'returnOnAssets', 'grossProfitMargin', 'netProfitMargin']:
                    val = val * 100 if val < 1 else val
                financial_ratios[display_name] = val
        
        if financial_ratios:
            radar_path = os.path.join(output_dir, f"{ticker}_financial_radar.png")
            charts['financial_radar_path'] = generate_financial_radar_chart(
                financial_ratios, radar_path, ticker
            ) or ""
            if charts['financial_radar_path']:
                print(f"✅ Generated Financial Radar chart")
    
    # 8. 现金流分析图
    if cashflow_df is not None and not cashflow_df.empty:
        try:
            cf_data = {
                'periods': cashflow_df['calendarYear'].tolist() if 'calendarYear' in cashflow_df.columns else [],
                'Operating': cashflow_df['operatingCashFlow'].tolist() if 'operatingCashFlow' in cashflow_df.columns else [],
                'Investing': cashflow_df['netCashUsedForInvestingActivites'].tolist() if 'netCashUsedForInvestingActivites' in cashflow_df.columns else [],
                'Financing': cashflow_df['netCashUsedProvidedByFinancingActivities'].tolist() if 'netCashUsedProvidedByFinancingActivities' in cashflow_df.columns else []
            }
            
            if cf_data['Operating']:
                cashflow_path = os.path.join(output_dir, f"{ticker}_cash_flow_chart.png")
                charts['cash_flow_chart_path'] = generate_cash_flow_chart(
                    cf_data, cashflow_path, ticker
                ) or ""
                if charts['cash_flow_chart_path']:
                    print(f"✅ Generated Cash Flow chart")
        except Exception as e:
            print(f"⚠️ Error generating cash flow chart: {e}")
    
    return charts


def fetch_market_data(ticker: str, config_file: Optional[str] = None) -> Dict[str, Any]:
    """
    从API获取市场数据
    """
    market_data = {}
    
    try:
        config = load_config(config_file)
        fmp_api_key = get_api_key(config, "API_KEYS", "fmp_api_key")
        
        if fmp_api_key:
            print(f"📊 Fetching market data for {ticker}...")
            market_data = get_comprehensive_company_metrics(ticker, fmp_api_key)
            print(f"✅ Successfully fetched market data")
    except Exception as e:
        print(f"⚠️ Could not fetch market data: {e}")
    
    return market_data


def main():
    parser = argparse.ArgumentParser(
        description="Generate professional equity research PDF report"
    )
    
    # 必需参数
    parser.add_argument("--company-ticker", type=str, required=True,
                       help="Stock ticker symbol (e.g., AAPL)")
    parser.add_argument("--company-name", type=str, required=True,
                       help="Full company name (e.g., 'Apple Inc.')")
    
    # 数据源参数
    parser.add_argument("--analysis-dir", type=str, default=None,
                       help="Directory containing analysis data files")
    
    # 可选参数
    parser.add_argument("--output-dir", type=str, default=None,
                       help="Output directory for PDF report")
    parser.add_argument("--report-date", type=str, 
                       default=datetime.now().strftime("%B %Y"),
                       help="Report date (e.g., 'November 2025')")
    parser.add_argument("--config-file", type=str, default=None,
                       help="Path to config.ini file")
    
    # 市场数据覆盖
    parser.add_argument("--share-price", type=float, default=None)
    parser.add_argument("--target-price", type=float, default=None)
    parser.add_argument("--rating", type=str, default=None)
    parser.add_argument("--market-cap", type=float, default=None)
    parser.add_argument("--sector", type=str, default=None)
    
    # 其他选项
    parser.add_argument("--skip-market-fetch", action="store_true",
                       help="Skip fetching market data from API")
    parser.add_argument("--analyst-names", type=str, nargs="*", 
                       default=["AI4Finance FinRobot"])
    parser.add_argument("--research-source", type=str, 
                       default="AI4Finance Foundation FinRobot Equity Research")
    
    args = parser.parse_args()
    
    # 设置路径
    ticker = args.company_ticker.upper()
    if args.analysis_dir:
        analysis_dir = args.analysis_dir
    else:
        analysis_dir = os.path.join(".", "output", ticker, "analysis")
    
    if args.output_dir:
        output_dir = args.output_dir
    else:
        output_dir = os.path.join(".", "output", ticker, "report")
    
    os.makedirs(output_dir, exist_ok=True)
    
    print(f"\n{'='*60}")
    print(f"📄 PROFESSIONAL EQUITY RESEARCH PDF GENERATOR")
    print(f"{'='*60}")
    print(f"Company: {args.company_name} ({ticker})")
    print(f"Analysis Dir: {analysis_dir}")
    print(f"Output Dir: {output_dir}")
    print(f"{'='*60}\n")
    
    # 1. 加载分析数据
    print("📥 Loading analysis data...")
    loaded_data = load_analysis_data(analysis_dir, ticker)
    
    # 2. 获取市场数据
    market_data = {}
    tech_indicators = {}
    if not args.skip_market_fetch:
        market_data = fetch_market_data(ticker, args.config_file)
        # Fetch technical indicators
        try:
            config = load_config(args.config_file)
            fmp_key = get_api_key(config, "API_KEYS", "fmp_api_key")
            if fmp_key:
                tech_indicators = get_technical_indicators(ticker, fmp_key)
        except Exception as e:
            print(f"⚠️ Could not compute technical indicators: {e}")

    # 3. 生成图表（包括高级图表）
    print("\n📊 Generating charts...")
    charts = generate_all_charts(
        loaded_data.get('analysis_df', pd.DataFrame()),
        loaded_data.get('peer_ev_ebitda_df', pd.DataFrame()),
        output_dir,
        ticker,
        price_df=loaded_data.get('price_df', pd.DataFrame()),
        ratios_df=loaded_data.get('ratios_df', pd.DataFrame()),
        cashflow_df=loaded_data.get('cashflow_df', pd.DataFrame())
    )
    
    # 4. 准备财务表格数据
    print("\n📋 Preparing financial tables...")
    financial_summary_df = prepare_financial_summary_df(
        loaded_data.get('analysis_df', pd.DataFrame())
    )
    credit_metrics_df = prepare_credit_metrics_df(
        loaded_data.get('ratios_df', pd.DataFrame())
    )
    
    # 4.5 Fix stale dates in cached text (e.g. "June 2024" → current report date)
    import re as _re
    _stale_date_pattern = _re.compile(
        r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+20\d{2}')
    _report_date_label = args.report_date  # e.g. "March 2026"

    def _fix_stale_dates(text: str) -> str:
        if not text:
            return text
        lines = text.split('\n')
        for i in range(min(3, len(lines))):
            if _stale_date_pattern.search(lines[i]):
                lines[i] = _stale_date_pattern.sub(_report_date_label, lines[i])
        return '\n'.join(lines)

    for key in ['company_overview', 'investment_overview', 'valuation_overview']:
        if key in loaded_data and loaded_data[key]:
            loaded_data[key] = _fix_stale_dates(loaded_data[key])

    # 4.6 Re-classify catalyst sentiments from cached JSON
    ANALYST_POS = _re.compile(
        r'(initiates?\s+coverage|acquires?\s+new\s+holdings|increases?\s+stake|'
        r'overweight|buy\s+rating|outperform|upgrade)', _re.IGNORECASE)
    catalyst_data = loaded_data.get('catalyst_analysis', {})
    if catalyst_data and 'top_catalysts' in catalyst_data:
        for cat in catalyst_data['top_catalysts']:
            desc = cat.get('description', '') or cat.get('catalyst', '')
            if cat.get('sentiment') == 'negative' and ANALYST_POS.search(desc):
                cat['sentiment'] = 'positive'
    # Also fix categorized negative → positive
    if catalyst_data and 'categorized' in catalyst_data:
        neg_list = catalyst_data['categorized'].get('negative', [])
        pos_list = catalyst_data['categorized'].get('positive', [])
        to_move = []
        for item in neg_list:
            desc = item.get('description', '') or item.get('catalyst', '')
            if ANALYST_POS.search(desc):
                to_move.append(item)
        for item in to_move:
            neg_list.remove(item)
            item['sentiment'] = 'positive'
            pos_list.append(item)
    # Fix summary text: remove mis-classified lines (analyst positive actions listed under Risk)
    if catalyst_data and catalyst_data.get('summary'):
        fixed_lines = []
        skip_next_impact = False
        for line in catalyst_data['summary'].split('\n'):
            if skip_next_impact:
                # Skip the "Impact: HIGH, Probability: XX%" line that follows a removed catalyst
                if 'Impact:' in line and 'Probability:' in line:
                    skip_next_impact = False
                    continue
                skip_next_impact = False
            if ANALYST_POS.search(line):
                skip_next_impact = True
                continue
            fixed_lines.append(line)
        catalyst_data['summary'] = '\n'.join(fixed_lines)

    # 4.7 Derive rating from target vs share price
    def _derive_rating_pdf(share_price, target_price, api_rating):
        try:
            price = float(str(share_price).replace('$', '').replace(',', ''))
            target = float(str(target_price).replace('$', '').replace(',', ''))
            if price <= 0:
                return api_rating or 'N/A'
            upside = (target - price) / price
            if upside >= 0.15:
                return 'Buy'
            elif upside >= 0.05:
                return 'Outperform'
            elif upside >= -0.05:
                return 'Hold'
            elif upside >= -0.15:
                return 'Underperform'
            else:
                return 'Sell'
        except (ValueError, TypeError, ZeroDivisionError):
            return api_rating or 'N/A'

    # 5. 组装报告数据
    print("\n📝 Assembling report data...")

    # 从 ratios_df 提取最新数据
    ratios_df = loaded_data.get('ratios_df', pd.DataFrame())
    local_metrics = {}
    if not ratios_df.empty:
        # 获取最新年份的数据
        latest_ratios = ratios_df.sort_values('calendarYear', ascending=False).iloc[0]
        local_metrics = {
            'pb_ratio': f"{latest_ratios.get('priceToBookRatio', 0):.2f}x" if pd.notna(latest_ratios.get('priceToBookRatio')) else 'N/A',
            'roe': f"{latest_ratios.get('returnOnEquity', 0)*100:.1f}%" if pd.notna(latest_ratios.get('returnOnEquity')) else 'N/A',
            'dividend_yield': f"{latest_ratios.get('dividendYield', 0)*100:.2f}%" if pd.notna(latest_ratios.get('dividendYield')) else 'N/A',
            'pe_ratio': f"{latest_ratios.get('priceEarningsRatio', 0):.1f}x" if pd.notna(latest_ratios.get('priceEarningsRatio')) else 'N/A',
            'net_margin': f"{latest_ratios.get('netProfitMargin', 0)*100:.1f}%" if pd.notna(latest_ratios.get('netProfitMargin')) else 'N/A',
            'debt_equity': f"{latest_ratios.get('debtEquityRatio', 0):.2f}" if pd.notna(latest_ratios.get('debtEquityRatio')) else 'N/A',
        }
        print(f"✅ Extracted local metrics from ratios data")
    
    # 辅助函数：优先使用命令行参数，其次使用API数据，最后使用本地数据
    def get_value(arg_val, api_key, local_key, default, format_func=None):
        if arg_val is not None:
            return format_func(arg_val) if format_func else arg_val
        elif api_key in market_data and market_data[api_key] is not None:
            val = market_data[api_key]
            return format_func(val) if format_func else val
        elif local_key in local_metrics and local_metrics[local_key] != 'N/A':
            return local_metrics[local_key]
        return default
    
    report_data = {
        # 基本信息
        'company_ticker': ticker,
        'company_name_full': args.company_name,
        'report_date': args.report_date,
        'sector': get_value(args.sector, 'sector', None, 'Technology', None),
        
        # 市场数据
        'share_price': get_value(args.share_price, 'share_price', None, 'N/A',
                                lambda x: f"${x:.2f}"),
        'target_price': get_value(args.target_price, 'target_price', None, 'N/A',
                                 lambda x: f"${x:.2f}"),
        'rating': 'Hold',  # placeholder, will be derived below
        'market_cap': get_value(args.market_cap, 'market_cap', None, 'N/A',
                               lambda x: f"${x:,.2f}B"),
        '52w_range': market_data.get('52w_range', 'N/A'),
        'volume': market_data.get('volume', 'N/A'),
        'fwd_pe': get_value(None, 'fwd_pe', 'pe_ratio', 'N/A', None),
        'pb_ratio': get_value(None, 'pb_ratio', 'pb_ratio', 'N/A', None),
        'roe': get_value(None, 'roe', 'roe', 'N/A', None),
        'free_float': market_data.get('free_float', 'N/A'),
        'dividend_yield': get_value(None, 'dividend_yield', 'dividend_yield', 'N/A', None),
        'net_debt_to_equity': get_value(None, 'net_debt_to_equity', 'debt_equity', 'N/A', None),
        
        # 文本内容
        'tagline': loaded_data.get('tagline', ''),
        'company_overview': loaded_data.get('company_overview', 'Company overview not available.'),
        'investment_overview': loaded_data.get('investment_overview', 'Investment overview not available.'),
        'valuation_overview': loaded_data.get('valuation_overview', 'Valuation analysis not available.'),
        'risks': loaded_data.get('risks', 'Risk factors not available.'),
        'competitor_analysis': loaded_data.get('competitor_analysis', 'Competitor analysis not available.'),
        'major_takeaways': loaded_data.get('major_takeaways', 'Key takeaways not available.'),
        'news_summary': loaded_data.get('news_summary', ''),
        'technical_indicators': tech_indicators,

        # 图表路径（基础图表）
        'revenue_chart_path': charts.get('revenue_chart_path', ''),
        'eps_pe_chart_path': charts.get('eps_pe_chart_path', ''),
        'ev_ebitda_chart_path': charts.get('ev_ebitda_chart_path', ''),
        'margin_chart_path': charts.get('margin_chart_path', ''),
        
        # 高级图表路径
        'stock_price_chart_path': charts.get('stock_price_chart_path', ''),
        'technical_indicators_path': charts.get('technical_indicators_path', ''),
        'financial_radar_path': charts.get('financial_radar_path', ''),
        'cash_flow_chart_path': charts.get('cash_flow_chart_path', ''),
        
        # 表格数据
        'financial_summary_df': financial_summary_df,
        'credit_cashflow_df': credit_metrics_df,
        'peer_comparison_df': loaded_data.get('peer_ev_ebitda_df', pd.DataFrame()),
        
        # 增强分析数据
        'sensitivity_analysis': loaded_data.get('sensitivity_analysis', {}),
        'catalyst_analysis': loaded_data.get('catalyst_analysis', {}),
        'enhanced_news': loaded_data.get('enhanced_news', {}),
        'company_news': loaded_data.get('company_news', []),
        
        # 元数据
        'closing_price_date': datetime.now().strftime("%B %d, %Y"),
        'data_source_text': 'FMP, Company Filings, AI4Finance Estimates',
        'research_source': args.research_source,
        'analyst_names': args.analyst_names,
        'disclaimer_text': (
            "Disclaimer: The information contained in this document is intended only for use "
            "by the person to whom it has been delivered and should not be disseminated or "
            "distributed to third parties without our prior written consent. This report is "
            "for informational purposes only and does not constitute investment advice. "
            "Our firm accepts no liability whatsoever with respect to the use of this document "
            "or its contents. Past performance is not indicative of future results."
        ),
    }
    
    # 5.5 Derive rating from target vs share price
    api_rating = get_value(args.rating, 'rating', None, 'Hold', None)
    report_data['rating'] = _derive_rating_pdf(
        report_data['share_price'], report_data['target_price'], api_rating)
    print(f"📊 Derived rating: {report_data['rating']} (API: {api_rating})")

    # 6. 生成PDF（专业版）
    print("\n📄 Generating Professional PDF report...")
    pdf_filename = f"Professional_Equity_Report_{ticker}.pdf"
    pdf_path = os.path.join(output_dir, pdf_filename)

    # 补充 analysis_df 到报告数据
    report_data['analysis_df'] = loaded_data.get('analysis_df', pd.DataFrame())
    
    try:
        result_path = generate_professional_report(pdf_path, report_data)
        
        print(f"\n{'='*60}")
        print(f"✅ PROFESSIONAL PDF REPORT GENERATED!")
        print(f"{'='*60}")
        print(f"📁 Output: {result_path}")
        print(f"📊 Dynamic pages based on content")
        print(f"📈 Charts: {sum(1 for v in charts.values() if v)}")
        print(f"💼 Investment Bank Style Report")
        print(f"{'='*60}\n")
        
    except Exception as e:
        print(f"\n❌ Error generating PDF: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())
