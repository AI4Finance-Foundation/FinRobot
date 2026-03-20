#!/usr/bin/env python
# coding: utf-8
"""
测试报告生成脚本 - 使用模拟数据生成PDF报告
"""

import os
import sys
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# 添加模块路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from modules.professional_pdf_report import generate_professional_report
from modules.chart_generator import (
    generate_revenue_ebitda_chart,
    generate_eps_pe_chart,
    generate_ev_ebitda_peer_chart,
    generate_margin_trend_chart,
    generate_stock_price_chart,
    generate_financial_radar_chart,
    generate_technical_indicators_chart,
    generate_cash_flow_chart
)


def create_mock_analysis_df():
    """创建模拟财务分析数据"""
    data = {
        'metrics': ['Revenue', 'Revenue Growth', 'EBITDA', 'EBITDA Margin', 
                   'EPS', 'PE Ratio', 'Contribution Margin', 'SG&A Margin'],
        '2021A': [386.1e9, '33.3%', 120.2e9, '31.1%', 5.61, 28.5, '42.5%', '11.4%'],
        '2022A': [394.3e9, '2.1%', 130.5e9, '33.1%', 6.11, 24.2, '43.2%', '10.1%'],
        '2023A': [383.3e9, '-2.8%', 125.8e9, '32.8%', 6.13, 30.1, '44.1%', '10.8%'],
        '2024A': [391.0e9, '2.0%', 135.2e9, '34.6%', 6.42, 29.5, '44.8%', '10.2%'],
    }
    return pd.DataFrame(data)


def create_mock_price_df():
    """创建模拟股价数据"""
    dates = pd.date_range(start='2024-01-01', periods=250, freq='D')
    np.random.seed(42)
    
    # 生成随机股价走势
    returns = np.random.randn(250) * 0.02
    prices = 180 * np.cumprod(1 + returns)
    volumes = np.random.randint(50000000, 150000000, 250)
    
    return pd.DataFrame({
        'date': dates,
        'close': prices,
        'volume': volumes
    })


def create_mock_peer_ev_ebitda_df():
    """创建模拟同行EV/EBITDA数据"""
    data = {
        'AAPL': [18.5, 17.2, 19.1, 18.8],
        'MSFT': [22.3, 21.5, 23.1, 22.8],
        'GOOGL': [15.2, 14.8, 16.1, 15.5],
        'AMZN': [25.1, 24.2, 26.3, 25.8],
    }
    df = pd.DataFrame(data, index=['2021', '2022', '2023', '2024'])
    df.index.name = 'year'
    return df


def create_financial_summary_df():
    """创建财务摘要表格"""
    data = {
        '2021A': ['$365.8B', '33.3%', '$120.2B', '32.9%', '$94.7B', '25.9%', '$5.61'],
        '2022A': ['$394.3B', '7.8%', '$130.5B', '33.1%', '$99.8B', '25.3%', '$6.11'],
        '2023A': ['$383.3B', '-2.8%', '$125.8B', '32.8%', '$97.0B', '25.3%', '$6.13'],
        '2024A': ['$391.0B', '2.0%', '$135.2B', '34.6%', '$101.2B', '25.9%', '$6.42'],
    }
    df = pd.DataFrame(data, index=['Revenue', 'Revenue Growth', 'EBITDA', 'EBITDA Margin', 
                                    'Net Income', 'Net Margin', 'EPS'])
    return df


def create_credit_metrics_df():
    """创建信用指标表格"""
    data = {
        '2021A': ['1.99', '0.35', '42.5x', '25.9%', '1.07', '0.85'],
        '2022A': ['2.39', '0.34', '38.2x', '25.3%', '0.88', '0.92'],
        '2023A': ['1.81', '0.32', '29.1x', '25.3%', '0.99', '0.88'],
        '2024A': ['1.72', '0.31', '35.5x', '25.9%', '1.04', '0.95'],
    }
    df = pd.DataFrame(data, index=['Debt/Equity', 'Debt/Assets', 'Interest Coverage', 
                                    'Net Margin', 'Current Ratio', 'CF to Debt'])
    return df


def main():
    print("=" * 60)
    print("📄 TEST REPORT GENERATION")
    print("=" * 60)
    
    ticker = "AAPL"
    company_name = "Apple Inc."
    
    # 创建输出目录
    output_dir = os.path.join(os.path.dirname(__file__), "test_output")
    os.makedirs(output_dir, exist_ok=True)
    
    # 创建模拟数据
    print("\n📊 Creating mock data...")
    analysis_df = create_mock_analysis_df()
    price_df = create_mock_price_df()
    peer_ev_ebitda_df = create_mock_peer_ev_ebitda_df()
    
    # 生成图表
    print("\n📈 Generating charts...")
    charts = {}
    
    # 基础图表
    revenue_path = os.path.join(output_dir, f"{ticker}_revenue_ebitda.png")
    charts['revenue_chart_path'] = generate_revenue_ebitda_chart(analysis_df, revenue_path, ticker) or ""
    print(f"  ✅ Revenue/EBITDA chart: {'Generated' if charts['revenue_chart_path'] else 'Skipped'}")
    
    eps_path = os.path.join(output_dir, f"{ticker}_eps_pe.png")
    charts['eps_pe_chart_path'] = generate_eps_pe_chart(analysis_df, eps_path, ticker) or ""
    print(f"  ✅ EPS/PE chart: {'Generated' if charts['eps_pe_chart_path'] else 'Skipped'}")
    
    ev_path = os.path.join(output_dir, f"{ticker}_ev_ebitda.png")
    charts['ev_ebitda_chart_path'] = generate_ev_ebitda_peer_chart(peer_ev_ebitda_df, ev_path, ticker) or ""
    print(f"  ✅ EV/EBITDA peer chart: {'Generated' if charts['ev_ebitda_chart_path'] else 'Skipped'}")
    
    margin_path = os.path.join(output_dir, f"{ticker}_margin.png")
    charts['margin_chart_path'] = generate_margin_trend_chart(analysis_df, margin_path, ticker) or ""
    print(f"  ✅ Margin trend chart: {'Generated' if charts['margin_chart_path'] else 'Skipped'}")
    
    # 高级图表
    print("\n📈 Generating advanced charts...")
    
    stock_path = os.path.join(output_dir, f"{ticker}_stock_price.png")
    charts['stock_price_chart_path'] = generate_stock_price_chart(price_df, stock_path, ticker, "1Y") or ""
    print(f"  ✅ Stock price chart: {'Generated' if charts['stock_price_chart_path'] else 'Skipped'}")
    
    tech_path = os.path.join(output_dir, f"{ticker}_technical.png")
    charts['technical_indicators_path'] = generate_technical_indicators_chart(price_df, tech_path, ticker) or ""
    print(f"  ✅ Technical indicators chart: {'Generated' if charts['technical_indicators_path'] else 'Skipped'}")
    
    # 财务比率雷达图
    financial_ratios = {
        'ROE': 147.5,
        'ROA': 28.3,
        'Gross Margin': 44.1,
        'Net Margin': 25.3,
        'Current Ratio': 0.99,
        'Debt/Equity': 1.81
    }
    radar_path = os.path.join(output_dir, f"{ticker}_radar.png")
    charts['financial_radar_path'] = generate_financial_radar_chart(financial_ratios, radar_path, ticker) or ""
    print(f"  ✅ Financial radar chart: {'Generated' if charts['financial_radar_path'] else 'Skipped'}")
    
    # 现金流图表
    cf_data = {
        'periods': ['2021', '2022', '2023', '2024'],
        'Operating': [104.0e9, 122.2e9, 110.5e9, 118.3e9],
        'Investing': [-14.5e9, -22.4e9, -3.7e9, -8.2e9],
        'Financing': [-93.4e9, -110.7e9, -108.5e9, -115.1e9]
    }
    cf_path = os.path.join(output_dir, f"{ticker}_cashflow.png")
    charts['cash_flow_chart_path'] = generate_cash_flow_chart(cf_data, cf_path, ticker) or ""
    print(f"  ✅ Cash flow chart: {'Generated' if charts['cash_flow_chart_path'] else 'Skipped'}")
    
    # 组装报告数据
    print("\n📝 Assembling report data...")
    report_data = {
        # 基本信息
        'company_ticker': ticker,
        'company_name_full': company_name,
        'report_date': datetime.now().strftime("%B %Y"),
        'sector': 'Technology',
        
        # 市场数据
        'share_price': '$189.95',
        'target_price': '$220.00',
        'rating': 'Buy',
        'market_cap': '$2.95T',
        'fwd_pe': '29.5x',
        'pb_ratio': '45.2x',
        'roe': '147.5%',
        'dividend_yield': '0.52%',
        '52w_range': '$164.08 - $199.62',
        
        # 文本内容
        'tagline': 'Apple remains a compelling investment with strong ecosystem lock-in, services growth momentum, and potential AI-driven upgrade cycle. The company\'s robust cash generation and shareholder returns program provide downside protection.',
        
        'company_overview': '''Apple Inc. designs, manufactures, and markets smartphones, personal computers, tablets, wearables, and accessories worldwide. The company offers iPhone, Mac, iPad, and Wearables, Home and Accessories products. It also provides AppleCare support and cloud services, operates various platforms including the App Store, and offers digital content and services.

The company has a dominant position in the premium smartphone market with approximately 50% market share in the US and strong presence globally. Apple's ecosystem of hardware, software, and services creates significant customer loyalty and switching costs.''',
        
        'investment_overview': '''We maintain our BUY rating on Apple with a $220 price target, representing 16% upside from current levels. Our thesis is based on:

1. Services Growth: Apple's services segment continues to grow at double-digit rates, now representing over 22% of total revenue with significantly higher margins than hardware.

2. AI Integration: The upcoming Apple Intelligence features could drive a significant iPhone upgrade cycle, particularly among the large installed base of older devices.

3. Capital Returns: Apple's aggressive share buyback program and growing dividend provide strong shareholder returns, with over $100B returned annually.

4. Ecosystem Strength: The integrated hardware-software ecosystem creates high switching costs and enables premium pricing power.''',
        
        'valuation_overview': '''Our $220 price target is based on a blended valuation approach:

- DCF Analysis: Using a 9% WACC and 3% terminal growth rate, our DCF model yields a fair value of $225.
- P/E Multiple: Applying a 32x multiple to our FY25 EPS estimate of $7.00 yields $224.
- EV/EBITDA: At 20x forward EV/EBITDA, we derive a value of $215.

Apple trades at a premium to the broader market, which we believe is justified given its superior profitability, cash generation, and growth visibility.''',
        
        'competitor_analysis': '''Apple faces competition across all product categories:

- Smartphones: Samsung, Google, and Chinese OEMs (Xiaomi, Oppo, Vivo) compete in the Android ecosystem
- PCs: Microsoft Surface, Dell, HP, and Lenovo in the Windows ecosystem
- Tablets: Samsung and Amazon in the Android/Fire OS space
- Wearables: Samsung, Fitbit (Google), and Garmin

Despite intense competition, Apple maintains premium positioning and strong brand loyalty. The company's vertical integration and ecosystem advantages create sustainable competitive moats.''',
        
        'risks': '''Key investment risks include:
Regulatory scrutiny on App Store practices and potential forced changes to commission structure
China exposure representing ~19% of revenue amid geopolitical tensions
Smartphone market maturity limiting unit growth potential
Increasing competition in services from Google, Amazon, and Microsoft
Supply chain concentration in Asia, particularly Taiwan and China
Currency headwinds from strong US dollar''',
        
        'major_takeaways': '''Strong services growth trajectory with expanding margins
AI features could catalyze significant iPhone upgrade cycle
Robust capital returns program with $100B+ annual shareholder returns
Premium valuation justified by superior profitability and cash generation
Near-term risks from China exposure and regulatory headwinds''',
        
        'news_summary': '''Recent news highlights include Apple's announcement of Apple Intelligence AI features at WWDC, strong iPhone 15 Pro demand, and continued services growth. The company also announced a record $110B share buyback authorization.''',
        
        # 图表路径
        **charts,
        
        # 表格数据
        'analysis_df': analysis_df,
        'peer_comparison_df': peer_ev_ebitda_df,
        'financial_summary_df': create_financial_summary_df(),
        'credit_cashflow_df': create_credit_metrics_df(),
        
        # 增强分析数据
        'sensitivity_analysis': {
            'summary': 'Sensitivity analysis shows Apple\'s valuation is most sensitive to changes in revenue growth assumptions and discount rate.'
        },
        'catalyst_analysis': {
            'summary': 'Key upcoming catalysts include iPhone 16 launch, Apple Intelligence rollout, and potential Vision Pro expansion.',
            'top_catalysts': [
                {'event_type': 'Product Launch', 'description': 'iPhone 16 launch expected September 2024', 'sentiment': 'positive', 'impact': 'high'},
                {'event_type': 'AI Features', 'description': 'Apple Intelligence rollout starting Fall 2024', 'sentiment': 'positive', 'impact': 'high'},
                {'event_type': 'Earnings', 'description': 'Q4 FY24 earnings report', 'sentiment': 'neutral', 'impact': 'medium'},
            ]
        },
        'enhanced_news': {
            'sentiment_summary': {'overall': 'positive'},
            'categories': {'Product': 5, 'Financial': 3, 'AI': 4}
        },
        'company_news': [
            {'title': 'Apple announces Apple Intelligence AI features', 'publishedDate': '2024-06-10'},
            {'title': 'iPhone 15 Pro demand exceeds expectations', 'publishedDate': '2024-05-15'},
            {'title': 'Apple reports record services revenue', 'publishedDate': '2024-05-02'},
        ],
        
        # 元数据
        'data_source_text': 'Company Filings, Mock Data for Testing',
        'research_source': 'AI4Finance FinRobot Test',
        'analyst_names': ['Test Analyst'],
        'disclaimer_text': 'This is a test report generated with mock data for demonstration purposes only. Not for investment decisions.',
    }
    
    # 生成PDF
    print("\n📄 Generating PDF report...")
    pdf_path = os.path.join(output_dir, f"Test_Report_{ticker}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf")
    
    try:
        result_path = generate_professional_report(pdf_path, report_data)
        
        print("\n" + "=" * 60)
        print("✅ TEST REPORT GENERATED SUCCESSFULLY!")
        print("=" * 60)
        print(f"📁 Output: {result_path}")
        print(f"📊 Charts generated: {sum(1 for v in charts.values() if v)}")
        print("=" * 60)
        
        return result_path
        
    except Exception as e:
        print(f"\n❌ Error generating PDF: {e}")
        import traceback
        traceback.print_exc()
        return None


if __name__ == "__main__":
    result = main()
    if result:
        print(f"\n🎉 Report saved to: {result}")
    else:
        print("\n❌ Report generation failed")
