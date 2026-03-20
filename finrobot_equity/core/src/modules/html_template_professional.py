#!/usr/bin/env python
# coding: utf-8
"""
专业股票研究报告 HTML 模板 - 与 PDF 结构完全一致
"""

HTML_PROFESSIONAL_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{company_name_full} ({company_ticker}) - Equity Research Report</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <style>
        body {{ font-family: 'Inter', sans-serif; }}
        @media print {{
            .page-break {{ page-break-before: always; }}
            .no-print {{ display: none; }}
        }}
        .section-title {{ 
            font-size: 1.5rem; 
            font-weight: 700; 
            color: #1a365d; 
            border-bottom: 2px solid #c9a227;
            padding-bottom: 0.5rem;
            margin-bottom: 1rem;
        }}
        .heading-2 {{
            font-size: 1.1rem;
            font-weight: 600;
            color: #1a365d;
            margin-top: 1.5rem;
            margin-bottom: 0.75rem;
        }}
        .heading-3 {{
            font-size: 0.95rem;
            font-weight: 600;
            color: #2d3748;
            margin-top: 1rem;
            margin-bottom: 0.5rem;
        }}
        .body-text {{
            font-size: 0.875rem;
            color: #2d3748;
            line-height: 1.6;
            text-align: justify;
        }}
        .bullet-point {{
            font-size: 0.875rem;
            color: #2d3748;
            padding-left: 1rem;
            margin-bottom: 0.25rem;
        }}
        .caption {{
            font-size: 0.75rem;
            color: #718096;
        }}
        .highlight-box {{
            background: #f7fafc;
            border-left: 3px solid #c9a227;
            padding: 1rem;
            margin: 1rem 0;
        }}
        .metric-card {{
            background: #f8fafc;
            border: 1px solid #e2e8f0;
            border-radius: 0.5rem;
            padding: 0.75rem;
        }}
        .positive {{ color: #38a169; }}
        .negative {{ color: #e53e3e; }}
        .neutral {{ color: #718096; }}
        .data-table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 0.8rem;
        }}
        .data-table th {{
            background: #1a365d;
            color: white;
            padding: 0.5rem;
            text-align: left;
            font-weight: 500;
        }}
        .data-table td {{
            padding: 0.5rem;
            border-bottom: 1px solid #e2e8f0;
        }}
        .data-table tr:nth-child(even) {{
            background: #f8fafc;
        }}
        .chart-container {{
            background: white;
            border: 1px solid #e2e8f0;
            border-radius: 0.5rem;
            padding: 0.5rem;
            text-align: center;
        }}
        .chart-container img {{
            max-width: 100%;
            height: auto;
        }}
        .two-column {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 1.5rem;
            align-items: start;
        }}
        @media (max-width: 768px) {{
            .two-column {{
                grid-template-columns: 1fr;
            }}
        }}
    </style>
</head>
<body class="bg-gray-50 text-gray-800">
    <!-- Cover Section -->
    <div class="bg-[#1a365d] text-white py-12 px-8 mb-8">
        <div class="max-w-4xl mx-auto text-center">
            <p class="text-[#c9a227] text-sm font-medium tracking-wider mb-2">EQUITY RESEARCH</p>
            <h1 class="text-4xl font-bold mb-2">{company_name_full}</h1>
            <p class="text-[#c9a227] text-lg mb-6">{company_ticker} | {sector}</p>
            
            <div class="flex justify-center gap-8 mb-6">
                <div>
                    <p class="text-gray-300 text-sm">Rating</p>
                    <p class="text-2xl font-bold {rating_color_class}">{rating}</p>
                </div>
                <div>
                    <p class="text-gray-300 text-sm">Current Price</p>
                    <p class="text-2xl font-bold">${share_price}</p>
                </div>
                <div>
                    <p class="text-gray-300 text-sm">Target Price</p>
                    <p class="text-2xl font-bold">${target_price}</p>
                </div>
            </div>
            
            <p class="text-gray-300 text-sm">{report_date}</p>
        </div>
    </div>

    <div class="max-w-4xl mx-auto px-8 pb-12">
        <!-- Key Metrics Snapshot -->
        <section class="mb-8">
            <h2 class="heading-2">Key Metrics Snapshot</h2>
            <div class="grid grid-cols-2 md:grid-cols-3 gap-4">
                <div class="metric-card">
                    <p class="text-xs text-gray-500">Market Cap</p>
                    <p class="text-lg font-semibold">{market_cap}</p>
                </div>
                <div class="metric-card">
                    <p class="text-xs text-gray-500">P/E (Fwd)</p>
                    <p class="text-lg font-semibold">{fwd_pe}</p>
                </div>
                <div class="metric-card">
                    <p class="text-xs text-gray-500">P/B Ratio</p>
                    <p class="text-lg font-semibold">{pb_ratio}</p>
                </div>
                <div class="metric-card">
                    <p class="text-xs text-gray-500">ROE</p>
                    <p class="text-lg font-semibold">{roe}</p>
                </div>
                <div class="metric-card">
                    <p class="text-xs text-gray-500">Dividend Yield</p>
                    <p class="text-lg font-semibold">{dividend_yield}</p>
                </div>
                <div class="metric-card">
                    <p class="text-xs text-gray-500">52W Range</p>
                    <p class="text-lg font-semibold">{week_52_range}</p>
                </div>
            </div>
        </section>

        <!-- Investment Thesis -->
        <section class="mb-8" id="investment-thesis">
            <h2 class="heading-2">Investment Thesis</h2>
            <div class="highlight-box">
                <p class="body-text">{tagline}</p>
            </div>
        </section>

        <!-- Company Overview -->
        <section class="mb-8" id="company-overview">
            <h2 class="section-title">Company Overview</h2>
            <div class="body-text whitespace-pre-line">{company_overview}</div>
            
            <h3 class="heading-2">Investment Overview</h3>
            <div class="body-text whitespace-pre-line">{investment_overview}</div>
        </section>

        <!-- Financial Analysis -->
        <section class="mb-8 page-break" id="financial-analysis">
            <h2 class="section-title">Financial Analysis</h2>
            
            <h3 class="heading-2">Revenue & EBITDA Performance</h3>
            <div class="two-column">
                <div>
                    <p class="body-text">{revenue_analysis_text}</p>
                    <div class="mt-4">
                        <p class="heading-3">Key Figures:</p>
                        {revenue_key_figures_html}
                    </div>
                </div>
                <div class="chart-container">
                    <img src="{revenue_chart_path}" alt="Revenue & EBITDA Chart">
                    <p class="caption mt-2">Source: Company Filings</p>
                </div>
            </div>
            
            <h3 class="heading-2">Earnings & Valuation Metrics</h3>
            <div class="two-column">
                <div>
                    <p class="body-text">{eps_analysis_text}</p>
                    <div class="mt-4">
                        <p class="heading-3">Key Figures:</p>
                        {eps_key_figures_html}
                    </div>
                </div>
                <div class="chart-container">
                    <img src="{eps_pe_chart_path}" alt="EPS & PE Chart">
                    <p class="caption mt-2">Source: Company Filings</p>
                </div>
            </div>
        </section>

        <!-- Valuation Analysis -->
        <section class="mb-8" id="valuation">
            <h2 class="section-title">Valuation Analysis</h2>
            <div class="body-text whitespace-pre-line">{valuation_overview}</div>
            
            <h3 class="heading-2">Peer Comparison</h3>
            <div class="two-column">
                <div>
                    {peer_ev_ebitda_table_html}
                </div>
                <div class="chart-container">
                    <img src="{ev_ebitda_chart_path}" alt="EV/EBITDA Peer Comparison">
                    <p class="caption mt-2">EV/EBITDA Peer Comparison</p>
                </div>
            </div>
        </section>

        <!-- News Section -->
        <section class="mb-8" id="news">
            <h2 class="section-title">Recent News & Events</h2>
            <h3 class="heading-2">News Summary</h3>
            <div class="body-text whitespace-pre-line">{news_summary}</div>
            {enhanced_news_html}
        </section>

        <!-- Sensitivity Analysis -->
        <section class="mb-8" id="sensitivity">
            <h2 class="section-title">Sensitivity Analysis</h2>
            {sensitivity_analysis_html}
        </section>

        <!-- Catalyst Analysis -->
        <section class="mb-8" id="catalysts">
            <h2 class="section-title">Key Catalysts</h2>
            {catalyst_analysis_html}
        </section>

        <!-- Advanced Charts -->
        <section class="mb-8 page-break" id="advanced-charts">
            <h2 class="section-title">Technical & Advanced Analysis</h2>
            {advanced_charts_section_html}
        </section>

        <!-- Competition & Risk -->
        <section class="mb-8" id="competition-risk">
            <h2 class="section-title">Competitive Landscape</h2>
            <div class="body-text whitespace-pre-line">{competitor_analysis}</div>
            
            <h3 class="heading-2">Risk Factors</h3>
            <div class="space-y-1">
                {risks_html}
            </div>
            
            <h3 class="heading-2">Key Takeaways</h3>
            <div class="space-y-1">
                {major_takeaways_html}
            </div>
        </section>

        <!-- Financial Data Appendix -->
        <section class="mb-8 page-break" id="financial-data">
            <h2 class="section-title">Financial Data</h2>
            
            <h3 class="heading-2">Income Statement Summary</h3>
            {financial_summary_table_html}
            
            <h3 class="heading-2">Credit & Cash Flow Metrics</h3>
            {credit_cashflow_table_html}
        </section>

        <!-- Disclaimer -->
        <section class="mt-12 pt-8 border-t border-gray-300" id="disclaimer">
            <h3 class="heading-3">DISCLAIMER</h3>
            <p class="text-xs text-gray-500 leading-relaxed">{disclaimer_text}</p>
            <div class="mt-4 text-xs text-gray-400">
                <p>Data Source: {data_source_text}</p>
                <p>Report Generated: {report_generated_time} | {research_source}</p>
            </div>
        </section>
    </div>
</body>
</html>
"""


def format_risks_to_html(risks_text: str) -> str:
    """将风险文本格式化为 HTML 列表"""
    if not risks_text:
        return "<p class='body-text text-gray-500 italic'>Risk factors not available.</p>"
    
    html_items = []
    for line in risks_text.strip().split('\n'):
        line = line.strip().lstrip('•').lstrip('-').strip()
        if line:
            html_items.append(f'<p class="bullet-point">▪ {line}</p>')
    
    return '\n'.join(html_items) if html_items else "<p class='body-text text-gray-500 italic'>Risk factors not available.</p>"


def format_takeaways_to_html(takeaways_text: str) -> str:
    """将要点文本格式化为 HTML 列表"""
    if not takeaways_text:
        return "<p class='body-text text-gray-500 italic'>Key takeaways not available.</p>"
    
    html_items = []
    for line in takeaways_text.strip().split('\n'):
        line = line.strip().lstrip('•').lstrip('-').lstrip('✓').strip()
        if line:
            html_items.append(f'<p class="bullet-point">✓ {line}</p>')
    
    return '\n'.join(html_items) if html_items else "<p class='body-text text-gray-500 italic'>Key takeaways not available.</p>"


def format_key_figures_html(figures: dict) -> str:
    """格式化关键指标为 HTML"""
    if not figures:
        return ""
    
    html_items = []
    for metric, value in figures.items():
        html_items.append(f'<p class="bullet-point">• {metric}: {value}</p>')
    
    return '\n'.join(html_items)


def format_sensitivity_analysis_html_professional(sensitivity_data: dict) -> str:
    """格式化敏感性分析为专业 HTML"""
    if not sensitivity_data:
        return "<p class='body-text text-gray-500 italic'>Sensitivity analysis not available.</p>"
    
    html = ""
    
    # Summary
    if sensitivity_data.get('summary'):
        summary = sensitivity_data['summary'].replace('\n', '<br>')
        html += f'<div class="body-text mb-4">{summary}</div>'
    
    # Confidence Intervals
    if sensitivity_data.get('confidence_intervals'):
        html += '<h3 class="heading-3">Forecast Confidence Intervals (95%):</h3>'
        html += '<div class="space-y-1">'
        for metric, ci in sensitivity_data['confidence_intervals'].items():
            if ci and isinstance(ci, dict):
                low_val = ci.get('low') or ci.get('lower', 'N/A')
                high_val = ci.get('high') or ci.get('upper', 'N/A')
                # Format large numbers
                if isinstance(low_val, (int, float)):
                    low_val = f"${low_val/1e9:.1f}B" if low_val > 1e9 else f"${low_val/1e6:.1f}M"
                if isinstance(high_val, (int, float)):
                    high_val = f"${high_val/1e9:.1f}B" if high_val > 1e9 else f"${high_val/1e6:.1f}M"
                html += f'<p class="bullet-point">• {metric}: {low_val} - {high_val}</p>'
        html += '</div>'
    
    return html if html else "<p class='body-text text-gray-500 italic'>Sensitivity analysis not available.</p>"


def format_catalyst_analysis_html_professional(catalyst_data: dict) -> str:
    """格式化催化剂分析为专业 HTML"""
    if not catalyst_data:
        return "<p class='body-text text-gray-500 italic'>Catalyst analysis not available.</p>"
    
    html = ""
    
    # Summary
    if catalyst_data.get('summary'):
        summary = catalyst_data['summary'].replace('\n', '<br>')
        html += f'<div class="body-text mb-4">{summary}</div>'
    
    # Top Catalysts
    top_catalysts = catalyst_data.get('top_catalysts', [])
    if top_catalysts:
        html += '<h3 class="heading-3">Upcoming Catalysts:</h3>'
        html += '<div class="space-y-2">'
        for cat in top_catalysts:
            event_type = cat.get('event_type') or cat.get('type', 'Event')
            description = cat.get('description') or cat.get('catalyst', '')
            sentiment = cat.get('sentiment', 'neutral')
            impact = cat.get('impact_level', cat.get('impact', 'medium'))
            
            # Color based on sentiment
            if sentiment == 'positive':
                prefix = "▲"
                color_class = "positive"
            elif sentiment == 'negative':
                prefix = "▼"
                color_class = "negative"
            else:
                prefix = "●"
                color_class = "neutral"
            
            html += f'<p class="bullet-point {color_class}">{prefix} [{event_type.upper()}] {description} (Impact: {impact})</p>'
        html += '</div>'
    
    # Categorized Catalysts
    categorized = catalyst_data.get('categorized', {})
    if categorized:
        if categorized.get('positive'):
            html += '<h3 class="heading-3">Positive Catalysts:</h3>'
            html += '<div class="space-y-1">'
            for item in categorized['positive']:
                desc = item.get('description', '')
                if desc:
                    html += f'<p class="bullet-point positive">✓ {desc}</p>'
            html += '</div>'
        
        if categorized.get('negative'):
            html += '<h3 class="heading-3">Risk Factors:</h3>'
            html += '<div class="space-y-1">'
            for item in categorized['negative']:
                desc = item.get('description', '')
                if desc:
                    html += f'<p class="bullet-point negative">⚠ {desc}</p>'
            html += '</div>'
    
    return html if html else "<p class='body-text text-gray-500 italic'>Catalyst analysis not available.</p>"


def format_enhanced_news_html_professional(news_data: dict) -> str:
    """格式化增强新闻为专业 HTML"""
    if not news_data:
        return ""
    
    html = ""
    
    # Sentiment Summary
    if news_data.get('sentiment_summary'):
        sentiment = news_data['sentiment_summary']
        if isinstance(sentiment, dict):
            overall = sentiment.get('overall', 'neutral')
            color_class = "positive" if overall == 'positive' else ("negative" if overall == 'negative' else "neutral")
            html += f'<div class="mt-4"><span class="heading-3">Overall Sentiment: </span><span class="{color_class} font-bold">{overall.upper()}</span></div>'
    
    # Categories
    if news_data.get('categories'):
        html += '<h3 class="heading-3">News by Category:</h3>'
        html += '<div class="space-y-1">'
        for cat, count in news_data['categories'].items():
            html += f'<p class="bullet-point">• {cat}: {count} articles</p>'
        html += '</div>'
    
    # Articles count
    if news_data.get('articles') and not news_data.get('categories'):
        articles = news_data['articles']
        if isinstance(articles, list) and len(articles) > 0:
            category_counts = {}
            for article in articles:
                if isinstance(article, dict):
                    cat = article.get('category', 'general')
                    category_counts[cat] = category_counts.get(cat, 0) + 1
            
            html += f'<div class="mt-4"><span class="heading-3">Total Articles: </span><span class="font-semibold">{len(articles)}</span></div>'
            html += '<h3 class="heading-3">News by Category:</h3>'
            html += '<div class="space-y-1">'
            for cat, count in sorted(category_counts.items(), key=lambda x: -x[1]):
                html += f'<p class="bullet-point">• {cat}: {count} articles</p>'
            html += '</div>'
    
    return html


def format_advanced_charts_html_professional(data: dict) -> str:
    """格式化高级图表章节为专业 HTML"""
    stock_price_chart = data.get('stock_price_chart_path', '')
    technical_chart = data.get('technical_indicators_path', '')
    radar_chart = data.get('financial_radar_path', '')
    cashflow_chart = data.get('cash_flow_chart_path', '')
    
    has_charts = any([stock_price_chart, technical_chart, radar_chart, cashflow_chart])
    
    if not has_charts:
        return "<p class='body-text text-gray-500 italic'>Advanced charts not available.</p>"
    
    html = ""
    
    # Stock Price Chart
    if stock_price_chart:
        html += '''
        <div class="mb-8">
            <h3 class="heading-2">Stock Price Performance</h3>
            <div class="two-column">
                <div>
                    <p class="body-text">Stock price performance is analyzed using multiple moving averages to identify trend direction and potential support/resistance levels. The chart displays the 20-day, 50-day, and 200-day moving averages alongside daily closing prices.</p>
                    <div class="mt-4">
                        <p class="heading-3">Key Technical Levels:</p>
                        <p class="bullet-point">• MA20: Short-term trend indicator</p>
                        <p class="bullet-point">• MA50: Medium-term support/resistance</p>
                        <p class="bullet-point">• MA200: Long-term trend direction</p>
                    </div>
                </div>
                <div class="chart-container">
                    <img src="''' + stock_price_chart + '''" alt="Stock Price Chart">
                    <p class="caption mt-2">Stock Price with Moving Averages</p>
                </div>
            </div>
        </div>
        '''
    
    # Technical Indicators
    if technical_chart:
        html += '''
        <div class="mb-8">
            <h3 class="heading-2">Technical Indicators</h3>
            <div class="two-column">
                <div>
                    <p class="body-text">Technical analysis incorporates momentum indicators including the Relative Strength Index (RSI) and Moving Average Convergence Divergence (MACD). RSI measures the speed and magnitude of price movements.</p>
                    <div class="mt-4">
                        <p class="heading-3">Indicator Interpretation:</p>
                        <p class="bullet-point">• RSI > 70: Overbought condition</p>
                        <p class="bullet-point">• RSI < 30: Oversold condition</p>
                        <p class="bullet-point">• MACD crossover: Momentum signal</p>
                    </div>
                </div>
                <div class="chart-container">
                    <img src="''' + technical_chart + '''" alt="Technical Indicators">
                    <p class="caption mt-2">RSI & MACD Technical Indicators</p>
                </div>
            </div>
        </div>
        '''
    
    # Financial Radar
    if radar_chart:
        html += '''
        <div class="mb-8">
            <h3 class="heading-2">Financial Ratio Analysis</h3>
            <div class="two-column">
                <div>
                    <p class="body-text">The financial ratio radar chart provides a multi-dimensional view of financial health across key metrics including profitability, efficiency, and leverage ratios.</p>
                    <div class="mt-4">
                        <p class="heading-3">Key Ratios Explained:</p>
                        <p class="bullet-point">• ROE: Return on shareholder equity</p>
                        <p class="bullet-point">• ROA: Asset utilization efficiency</p>
                        <p class="bullet-point">• Margins: Profitability indicators</p>
                    </div>
                </div>
                <div class="chart-container">
                    <img src="''' + radar_chart + '''" alt="Financial Radar">
                    <p class="caption mt-2">Financial Ratio Radar Chart</p>
                </div>
            </div>
        </div>
        '''
    
    # Cash Flow
    if cashflow_chart:
        html += '''
        <div class="mb-8">
            <h3 class="heading-2">Cash Flow Analysis</h3>
            <div class="two-column">
                <div>
                    <p class="body-text">Cash flow analysis examines the three primary components of cash movement: operating, investing, and financing activities. Strong operating cash flow indicates healthy core business performance.</p>
                    <div class="mt-4">
                        <p class="heading-3">Cash Flow Components:</p>
                        <p class="bullet-point">• Operating CF: Core business cash generation</p>
                        <p class="bullet-point">• Investing CF: Capital expenditure & investments</p>
                        <p class="bullet-point">• Financing CF: Debt & equity transactions</p>
                    </div>
                </div>
                <div class="chart-container">
                    <img src="''' + cashflow_chart + '''" alt="Cash Flow Chart">
                    <p class="caption mt-2">Cash Flow Statement Analysis</p>
                </div>
            </div>
        </div>
        '''
    
    return html


def get_rating_color_class(rating: str) -> str:
    """根据评级返回颜色类"""
    if rating in ['Buy', 'Outperform', 'Overweight', 'Strong Buy']:
        return 'text-green-400'
    elif rating in ['Sell', 'Underperform', 'Underweight', 'Strong Sell']:
        return 'text-red-400'
    else:
        return 'text-[#c9a227]'


def render_professional_html_report(data: dict) -> str:
    """渲染专业 HTML 报告"""
    from datetime import datetime
    
    # Prepare data with defaults
    report_data = {
        'company_name_full': data.get('company_name_full', 'Company'),
        'company_ticker': data.get('company_ticker', 'TICK'),
        'sector': data.get('sector', 'Technology'),
        'rating': data.get('rating', 'N/A'),
        'rating_color_class': get_rating_color_class(data.get('rating', 'N/A')),
        'share_price': data.get('share_price', 'N/A'),
        'target_price': data.get('target_price', 'N/A'),
        'report_date': data.get('report_date', datetime.now().strftime('%B %Y')),
        'market_cap': data.get('market_cap', 'N/A'),
        'fwd_pe': data.get('fwd_pe', 'N/A'),
        'pb_ratio': data.get('pb_ratio', 'N/A'),
        'roe': data.get('roe', 'N/A'),
        'dividend_yield': data.get('dividend_yield', 'N/A'),
        'week_52_range': data.get('52w_range', data.get('week_52_range', 'N/A')),
        'tagline': data.get('tagline', 'Investment thesis not available.'),
        'company_overview': data.get('company_overview', 'Company overview not available.'),
        'investment_overview': data.get('investment_overview', 'Investment overview not available.'),
        'revenue_analysis_text': data.get('revenue_analysis_text', 'Revenue analysis demonstrates the company\'s financial performance over the analysis period.'),
        'revenue_key_figures_html': format_key_figures_html(data.get('revenue_key_figures', {})),
        'revenue_chart_path': data.get('revenue_chart_path', ''),
        'eps_analysis_text': data.get('eps_analysis_text', 'Earnings analysis shows the company\'s profitability trends.'),
        'eps_key_figures_html': format_key_figures_html(data.get('eps_key_figures', {})),
        'eps_pe_chart_path': data.get('eps_pe_chart_path', ''),
        'valuation_overview': data.get('valuation_overview', 'Valuation analysis not available.'),
        'peer_ev_ebitda_table_html': data.get('peer_ev_ebitda_table_html', '<p class="body-text text-gray-500 italic">Peer comparison data not available.</p>'),
        'ev_ebitda_chart_path': data.get('ev_ebitda_chart_path', ''),
        'news_summary': data.get('news_summary', 'Recent news coverage not available.'),
        'enhanced_news_html': format_enhanced_news_html_professional(data.get('enhanced_news', {})),
        'sensitivity_analysis_html': format_sensitivity_analysis_html_professional(data.get('sensitivity_analysis', {})),
        'catalyst_analysis_html': format_catalyst_analysis_html_professional(data.get('catalyst_analysis', {})),
        'advanced_charts_section_html': format_advanced_charts_html_professional(data),
        'competitor_analysis': data.get('competitor_analysis', 'Competitive analysis not available.'),
        'risks_html': format_risks_to_html(data.get('risks', '')),
        'major_takeaways_html': format_takeaways_to_html(data.get('major_takeaways', '')),
        'financial_summary_table_html': data.get('financial_summary_table_html', '<p class="body-text text-gray-500 italic">Financial summary not available.</p>'),
        'credit_cashflow_table_html': data.get('credit_cashflow_table_html', '<p class="body-text text-gray-500 italic">Credit & cashflow metrics not available.</p>'),
        'disclaimer_text': data.get('disclaimer_text', 'This report is for informational purposes only and does not constitute investment advice.'),
        'data_source_text': data.get('data_source_text', 'Company Filings, FMP API'),
        'research_source': data.get('research_source', 'AI4Finance FinRobot'),
        'report_generated_time': datetime.now().strftime('%Y-%m-%d %H:%M'),
    }
    
    try:
        return HTML_PROFESSIONAL_TEMPLATE.format(**report_data)
    except KeyError as e:
        print(f"Error rendering professional HTML: Missing key {e}")
        return f"<html><body><h1>Error rendering report</h1><p>Missing data: {e}</p></body></html>"
    except Exception as e:
        print(f"Error rendering professional HTML: {e}")
        return f"<html><body><h1>Error rendering report</h1><p>Error: {e}</p></body></html>"
