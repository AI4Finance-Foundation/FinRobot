#!/usr/bin/env python
# coding: utf-8
"""
专业股票研究报告 HTML 模板 - Modern Fintech Style
"""
import re as _re


def _auto_bold_key_data(text: str) -> str:
    """自动加粗关键金融数据和结论性语句。"""
    if not text or '<strong>' in text:
        return text  # 已有加粗标记则跳过

    # 1. 加粗 $金额+单位: "$97.7 billion", "$14.8B", "$1.5 million"
    text = _re.sub(
        r'(\$[\d,.]+\s*(?:billion|million|trillion|bn|mn|trn|B|M|K|T))',
        r'<strong>\1</strong>', text, flags=_re.IGNORECASE)

    # 2. 加粗百分比: "15.2%", "-0.9%", "+3.5%"
    text = _re.sub(
        r'(?<!\d)([\-+]?\d+\.?\d*%)',
        r'<strong>\1</strong>', text)

    # 3. 加粗倍数: "50x", "25.4x"
    text = _re.sub(
        r'\b(\d+\.?\d*x)\b',
        r'<strong>\1</strong>', text)

    # 4. 清理嵌套 strong 标签
    for _ in range(3):
        text = _re.sub(r'<strong>([^<]*)<strong>', r'<strong>\1', text)
        text = _re.sub(r'</strong>([^<]*)</strong>', r'\1</strong>', text)

    return text


def _is_conclusion_sentence(text: str) -> bool:
    """判断是否是结论性段落。"""
    conclusion_starters = [
        'overall,', 'in summary,', 'in conclusion,', 'this suggests',
        'to summarize,', 'taken together,', 'on balance,',
        'the key takeaway', 'notably,', 'importantly,',
    ]
    lower = text.lower().strip()
    return any(lower.startswith(s) for s in conclusion_starters)


def _markdown_to_html(text: str) -> str:
    """将 markdown 文本转换为 HTML，支持标题、粗体、列表等。自动加粗关键数据。"""
    if not text:
        return ""
    lines = text.split('\n')
    html_lines = []
    in_list = False
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if in_list:
                html_lines.append('</ul>')
                in_list = False
            html_lines.append('')
            continue
        # headings
        if stripped.startswith('### '):
            if in_list:
                html_lines.append('</ul>')
                in_list = False
            content = _re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', stripped[4:])
            html_lines.append(f'<h4 style="font-size:0.9rem; font-weight:600; color:#334155; margin:0.75rem 0 0.4rem 0;">{content}</h4>')
            continue
        if stripped.startswith('## '):
            if in_list:
                html_lines.append('</ul>')
                in_list = False
            content = _re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', stripped[3:])
            html_lines.append(f'<h3 style="font-size:1rem; font-weight:600; color:#0f172a; margin:1rem 0 0.5rem 0; border-left:3px solid #6366f1; padding-left:0.6rem;">{content}</h3>')
            continue
        # list items
        if stripped.startswith('- '):
            if not in_list:
                html_lines.append('<ul style="list-style:none; padding-left:0; margin:0.35rem 0;">')
                in_list = True
            item = _re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', stripped[2:])
            item = _auto_bold_key_data(item)
            html_lines.append(f'<li style="padding:0.3rem 0 0.3rem 1.2rem; position:relative; font-size:0.875rem; color:#334155; line-height:1.6;"><span style="position:absolute; left:0; color:#6366f1;">&#8227;</span> {item}</li>')
            continue
        # sub-list items (indented)
        if _re.match(r'^\s{2,}-\s', line):
            item_text = _re.sub(r'^\s+-\s*', '', line)
            item_text = _re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', item_text)
            item_text = _auto_bold_key_data(item_text)
            if not in_list:
                html_lines.append('<ul style="list-style:none; padding-left:0; margin:0.25rem 0;">')
                in_list = True
            html_lines.append(f'<li style="padding:0.2rem 0 0.2rem 2.2rem; font-size:0.825rem; color:#64748b; line-height:1.5;">&#8211; {item_text}</li>')
            continue
        # close list if open
        if in_list:
            html_lines.append('</ul>')
            in_list = False
        # plain paragraph with bold
        content = _re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', stripped)
        content = _auto_bold_key_data(content)
        # 结论性段落特殊样式 — 浅 indigo 背景 + 左边条
        if _is_conclusion_sentence(stripped):
            html_lines.append(
                f'<p style="margin:0.6rem 0; padding:0.6rem 0.8rem; font-size:0.875rem; color:#1e293b; '
                f'line-height:1.7; background:#eef2ff; border-left:3px solid #6366f1; border-radius:0.25rem; '
                f'font-weight:500;">{content}</p>')
        else:
            html_lines.append(f'<p style="margin-bottom:0.4rem; font-size:0.875rem; color:#334155; line-height:1.7;">{content}</p>')
    if in_list:
        html_lines.append('</ul>')
    return '\n'.join(html_lines)


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
        body {{ font-family: 'Inter', sans-serif; font-weight: 400; color: #0f172a; background: #ffffff; }}
        @media print {{
            .page-break {{ page-break-before: always; }}
            .no-print {{ display: none; }}
        }}

        /* Section titles - modern left bar accent */
        .section-title {{
            font-size: 1.25rem;
            font-weight: 700;
            color: #0f172a;
            border-left: 4px solid #6366f1;
            padding-left: 0.75rem;
            margin-bottom: 1.25rem;
        }}
        .heading-2 {{
            font-size: 1.05rem;
            font-weight: 600;
            color: #1e293b;
            margin-top: 1.5rem;
            margin-bottom: 0.75rem;
        }}
        .heading-3 {{
            font-size: 0.9rem;
            font-weight: 600;
            color: #334155;
            margin-top: 1rem;
            margin-bottom: 0.5rem;
        }}
        .body-text {{
            font-size: 0.875rem;
            color: #334155;
            line-height: 1.7;
        }}
        .bullet-point {{
            font-size: 0.875rem;
            color: #334155;
            padding-left: 1.2rem;
            margin-bottom: 0.3rem;
            line-height: 1.6;
        }}
        .caption {{
            font-size: 0.75rem;
            color: #94a3b8;
        }}

        /* Investment thesis callout */
        .highlight-box {{
            background: linear-gradient(135deg, #eef2ff 0%, #f5f3ff 100%);
            border-left: 4px solid #6366f1;
            border-radius: 0.75rem;
            padding: 1.25rem 1.5rem;
            margin: 1rem 0;
            position: relative;
        }}
        .highlight-box::before {{
            content: '\\201C';
            font-size: 3rem;
            color: #a5b4fc;
            position: absolute;
            top: -0.25rem;
            left: 0.75rem;
            font-family: Georgia, serif;
        }}
        .highlight-box .body-text {{
            padding-left: 1.5rem;
        }}

        /* Metric cards */
        .metric-card {{
            background: #ffffff;
            border: 1px solid #e2e8f0;
            border-radius: 0.75rem;
            padding: 1rem;
            box-shadow: 0 1px 3px rgba(0,0,0,0.06);
            position: relative;
            overflow: hidden;
        }}
        .metric-card::before {{
            content: '';
            position: absolute;
            top: 0; left: 0; right: 0;
            height: 3px;
            background: linear-gradient(90deg, #6366f1, #8b5cf6);
        }}

        /* Colors */
        .positive {{ color: #10b981; }}
        .negative {{ color: #ef4444; }}
        .neutral {{ color: #f59e0b; }}

        /* Rating badges */
        .rating-badge {{
            display: inline-block;
            padding: 0.25rem 0.75rem;
            border-radius: 9999px;
            font-size: 0.875rem;
            font-weight: 700;
            letter-spacing: 0.02em;
        }}
        .rating-buy {{ background: #d1fae5; color: #065f46; }}
        .rating-sell {{ background: #fee2e2; color: #991b1b; }}
        .rating-hold {{ background: #fef3c7; color: #92400e; }}

        /* Tables */
        .data-table {{
            width: 100%;
            border-collapse: separate;
            border-spacing: 0;
            font-size: 0.8rem;
            border-radius: 0.5rem;
            overflow: hidden;
            border: 1px solid #e2e8f0;
        }}
        .data-table th {{
            background: #f1f5f9;
            color: #475569;
            padding: 0.6rem 0.75rem;
            text-align: left;
            font-weight: 600;
            font-size: 0.75rem;
        }}
        .data-table td {{
            padding: 0.55rem 0.75rem;
            border-top: 1px solid #f1f5f9;
        }}
        .data-table tr:hover {{
            background: #f8fafc;
        }}

        /* Chart cards */
        .chart-container {{
            background: white;
            border: 1px solid #e2e8f0;
            border-radius: 0.75rem;
            padding: 1rem;
            text-align: center;
            box-shadow: 0 1px 3px rgba(0,0,0,0.06);
        }}
        .chart-container img {{
            max-width: 100%;
            height: auto;
            border-radius: 0.5rem;
        }}

        /* Two column layout */
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

        /* Content card */
        .content-card {{
            background: #f8fafc;
            border-radius: 0.75rem;
            padding: 1.25rem;
            border: 1px solid #e2e8f0;
        }}
    </style>
</head>
<body>
    <!-- Hero Header -->
    <div style="background: linear-gradient(135deg, #0f172a 0%, #1e293b 50%, #0f172a 100%); padding: 2.5rem 2rem 2rem;">
        <div class="max-w-4xl mx-auto">
            <div class="flex items-center gap-3 mb-4">
                <span style="background: rgba(99,102,241,0.2); color: #a5b4fc; padding: 0.2rem 0.75rem; border-radius: 9999px; font-size: 0.75rem; font-weight: 500; letter-spacing: 0.05em;">AI EQUITY RESEARCH</span>
                <span style="color: #64748b; font-size: 0.8rem;">{report_date}</span>
            </div>
            <h1 style="color: #ffffff; font-size: 2rem; font-weight: 700; margin-bottom: 0.5rem; letter-spacing: -0.02em;">{company_name_full}</h1>
            <div class="flex items-center gap-3 mb-6">
                <span style="background: #1e293b; border: 1px solid #334155; color: #94a3b8; padding: 0.2rem 0.6rem; border-radius: 0.375rem; font-size: 0.8rem; font-weight: 500;">{company_ticker}</span>
                <span style="color: #64748b; font-size: 0.85rem;">{sector}</span>
            </div>
            <div class="flex items-end gap-8">
                <div>
                    <p style="color: #64748b; font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 0.2rem;">Rating</p>
                    <span class="rating-badge {rating_color_class}">{rating}</span>
                </div>
                <div>
                    <p style="color: #64748b; font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 0.2rem;">Price</p>
                    <p style="color: #ffffff; font-size: 1.5rem; font-weight: 700;">{share_price}</p>
                </div>
                <div>
                    <p style="color: #64748b; font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 0.2rem;">Target</p>
                    <p style="color: #a5b4fc; font-size: 1.5rem; font-weight: 700;">{target_price}</p>
                </div>
            </div>
        </div>
    </div>

    <div class="max-w-4xl mx-auto px-6 pb-12" style="margin-top: -1rem;">
        <!-- Key Metrics Cards -->
        <section class="mb-10">
            <div class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
                <div class="metric-card">
                    <p style="color: #94a3b8; font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 0.25rem;">Market Cap</p>
                    <p style="color: #0f172a; font-size: 1rem; font-weight: 600;">{market_cap}</p>
                </div>
                <div class="metric-card">
                    <p style="color: #94a3b8; font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 0.25rem;">P/E (Fwd)</p>
                    <p style="color: #0f172a; font-size: 1rem; font-weight: 600;">{fwd_pe}</p>
                </div>
                <div class="metric-card">
                    <p style="color: #94a3b8; font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 0.25rem;">P/B Ratio</p>
                    <p style="color: #0f172a; font-size: 1rem; font-weight: 600;">{pb_ratio}</p>
                </div>
                <div class="metric-card">
                    <p style="color: #94a3b8; font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 0.25rem;">ROE</p>
                    <p style="color: #0f172a; font-size: 1rem; font-weight: 600;">{roe}</p>
                </div>
                <div class="metric-card">
                    <p style="color: #94a3b8; font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 0.25rem;">Div. Yield</p>
                    <p style="color: #0f172a; font-size: 1rem; font-weight: 600;">{dividend_yield}</p>
                </div>
                <div class="metric-card">
                    <p style="color: #94a3b8; font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 0.25rem;">52W Range</p>
                    <p style="color: #0f172a; font-size: 1rem; font-weight: 600;">{week_52_range}</p>
                </div>
            </div>
        </section>

        <!-- Investment Thesis -->
        <section class="mb-10" id="investment-thesis">
            <h2 class="section-title">Investment Thesis</h2>
            <div class="highlight-box">
                <p class="body-text">{tagline}</p>
            </div>
        </section>

        <!-- Company Overview -->
        <section class="mb-10" id="company-overview">
            <h2 class="section-title">Company Overview</h2>
            <div class="body-text">{company_overview}</div>

            <h3 class="heading-2">Investment Overview</h3>
            <div class="body-text">{investment_overview}</div>
        </section>

        <!-- Financial Analysis -->
        <section class="mb-10 page-break" id="financial-analysis">
            <h2 class="section-title">Financial Analysis</h2>

            <h3 class="heading-2">Revenue & EBITDA Performance</h3>
            <div class="two-column">
                <div class="content-card">
                    <p class="body-text">{revenue_analysis_text}</p>
                    <div class="mt-4">
                        <p class="heading-3">Key Figures</p>
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
                <div class="content-card">
                    <p class="body-text">{eps_analysis_text}</p>
                    <div class="mt-4">
                        <p class="heading-3">Key Figures</p>
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
        <section class="mb-10" id="valuation">
            <h2 class="section-title">Valuation Analysis</h2>
            <div class="body-text">{valuation_overview}</div>

            <!-- Target Price Derivation -->
            {valuation_breakdown_html}

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
        <section class="mb-10" id="news">
            <h2 class="section-title">Recent News & Events</h2>
            <div class="content-card">
                <h3 class="heading-3" style="margin-top:0;">News Summary</h3>
                <div class="body-text">{news_summary}</div>
                {enhanced_news_html}
            </div>
        </section>

        <!-- Sensitivity Analysis -->
        <section class="mb-10" id="sensitivity">
            <h2 class="section-title">Sensitivity Analysis</h2>
            <div class="content-card">
                {sensitivity_analysis_html}
            </div>
        </section>

        <!-- Catalyst Analysis -->
        <section class="mb-10" id="catalysts">
            <h2 class="section-title">Key Catalysts</h2>
            <div class="content-card">
                {catalyst_analysis_html}
            </div>
        </section>

        <!-- Advanced Charts -->
        <section class="mb-10 page-break" id="advanced-charts">
            <h2 class="section-title">Technical & Advanced Analysis</h2>
            {advanced_charts_section_html}
        </section>

        <!-- Competition & Risk -->
        <section class="mb-10" id="competition-risk">
            <h2 class="section-title">Competitive Landscape</h2>

            <!-- Peer Comparison Tables -->
            <div class="content-card mb-6">
                <h3 class="heading-2" style="margin-top:0;">Peer EBITDA Comparison</h3>
                {peer_ebitda_table_html}
            </div>
            <div class="content-card mb-6">
                <h3 class="heading-2" style="margin-top:0;">Peer EV/EBITDA Comparison</h3>
                {peer_ev_ebitda_table_html_comp}
            </div>

            <h3 class="heading-2">Analysis</h3>
            <div class="body-text">{competitor_analysis}</div>

            <h3 class="heading-2">Risk Factors</h3>
            <div class="content-card" style="border-left: 4px solid #ef4444;">
                {risks_html}
            </div>

            <h3 class="heading-2">Key Takeaways</h3>
            <div class="content-card" style="border-left: 4px solid #10b981;">
                {major_takeaways_html}
            </div>
        </section>

        <!-- Financial Data Appendix -->
        <section class="mb-10 page-break" id="financial-data">
            <h2 class="section-title">Financial Data</h2>

            <h3 class="heading-2">Income Statement Summary</h3>
            {financial_summary_table_html}

            <h3 class="heading-2">Credit & Cash Flow Metrics</h3>
            {credit_cashflow_table_html}
        </section>

        <!-- Disclaimer -->
        <section class="mt-12" id="disclaimer" style="background: #f8fafc; margin-left: -1.5rem; margin-right: -1.5rem; padding: 1.5rem; border-radius: 0.75rem;">
            <div class="flex items-center gap-2 mb-2">
                <span style="background: linear-gradient(90deg, #6366f1, #8b5cf6); -webkit-background-clip: text; -webkit-text-fill-color: transparent; font-weight: 600; font-size: 0.75rem;">Powered by FinRobot AI</span>
                <span style="color: #cbd5e1;">|</span>
                <span style="color: #94a3b8; font-size: 0.7rem;">{research_source}</span>
            </div>
            <p style="color: #94a3b8; font-size: 0.65rem; line-height: 1.5;">{disclaimer_text}</p>
            <p style="color: #cbd5e1; font-size: 0.65rem; margin-top: 0.5rem;">Data: {data_source_text} &middot; Generated: {report_generated_time}</p>
        </section>
    </div>
</body>
</html>
"""


def format_risks_to_html(risks_text: str) -> str:
    """将风险文本格式化为 HTML 列表"""
    if not risks_text:
        return "<p class='body-text' style='color:#94a3b8; font-style:italic;'>Risk factors not available.</p>"

    result = _markdown_to_html(risks_text)
    return result if result.strip() else "<p class='body-text' style='color:#94a3b8; font-style:italic;'>Risk factors not available.</p>"


def format_takeaways_to_html(takeaways_text: str) -> str:
    """将要点文本格式化为 HTML 列表"""
    if not takeaways_text:
        return "<p class='body-text' style='color:#94a3b8; font-style:italic;'>Key takeaways not available.</p>"

    result = _markdown_to_html(takeaways_text)
    return result if result.strip() else "<p class='body-text' style='color:#94a3b8; font-style:italic;'>Key takeaways not available.</p>"


def _format_figure_value(value) -> str:
    """将大数字格式化为可读单位 (B/M/K)"""
    if isinstance(value, str):
        # 尝试解析字符串数字
        try:
            num = float(value.replace(',', ''))
        except (ValueError, AttributeError):
            return value
    elif isinstance(value, (int, float)):
        num = float(value)
    else:
        return str(value)

    abs_num = abs(num)
    if abs_num >= 1e12:
        return f"${num/1e12:,.2f}T"
    elif abs_num >= 1e9:
        return f"${num/1e9:,.2f}B"
    elif abs_num >= 1e6:
        return f"${num/1e6:,.1f}M"
    elif abs_num >= 1e3:
        return f"${num/1e3:,.1f}K"
    elif abs_num == 0:
        return "$0"
    else:
        return f"{num:,.2f}"


def format_key_figures_html(figures: dict) -> str:
    """格式化关键指标为 HTML"""
    if not figures:
        return ""

    html_items = []
    for metric, value in figures.items():
        # 百分比和倍数保持原样，大数字转换单位
        display_val = str(value)
        if isinstance(value, str) and ('%' in value or 'x' in value or 'N/A' in value):
            display_val = value
        else:
            display_val = _format_figure_value(value)
        html_items.append(f'<div style="display:flex; justify-content:space-between; padding:0.35rem 0; border-bottom:1px solid #f1f5f9; font-size:0.85rem;"><span style="color:#64748b;">{metric}</span><span style="color:#0f172a; font-weight:600;">{display_val}</span></div>')

    return '\n'.join(html_items)


def format_sensitivity_analysis_html_professional(sensitivity_data: dict) -> str:
    """格式化敏感性分析为专业 HTML"""
    if not sensitivity_data:
        return "<p class='body-text' style='color:#94a3b8; font-style:italic;'>Sensitivity analysis not available.</p>"

    html = ""

    # Summary
    if sensitivity_data.get('summary'):
        html += f'<div class="mb-4">{_markdown_to_html(sensitivity_data["summary"])}</div>'

    # Confidence Intervals
    if sensitivity_data.get('confidence_intervals'):
        html += '<h3 class="heading-3">Forecast Confidence Intervals (95%)</h3>'
        html += '<div style="display:grid; gap:0.5rem;">'
        for metric, ci in sensitivity_data['confidence_intervals'].items():
            if ci and isinstance(ci, dict):
                low_val = ci.get('low') or ci.get('lower', 'N/A')
                high_val = ci.get('high') or ci.get('upper', 'N/A')
                if isinstance(low_val, (int, float)):
                    low_val = f"${low_val/1e9:.1f}B" if low_val > 1e9 else f"${low_val/1e6:.1f}M"
                if isinstance(high_val, (int, float)):
                    high_val = f"${high_val/1e9:.1f}B" if high_val > 1e9 else f"${high_val/1e6:.1f}M"
                html += f'<div style="display:flex; justify-content:space-between; padding:0.4rem 0.6rem; background:#f8fafc; border-radius:0.375rem; font-size:0.85rem;"><span style="color:#64748b;">{metric}</span><span style="color:#0f172a; font-weight:500;">{low_val} — {high_val}</span></div>'
        html += '</div>'

    return html if html else "<p class='body-text' style='color:#94a3b8; font-style:italic;'>Sensitivity analysis not available.</p>"


def format_catalyst_analysis_html_professional(catalyst_data: dict) -> str:
    """格式化催化剂分析为专业 HTML"""
    if not catalyst_data:
        return "<p class='body-text' style='color:#94a3b8; font-style:italic;'>Catalyst analysis not available.</p>"

    html = ""

    # Summary
    if catalyst_data.get('summary'):
        html += f'<div class="mb-4">{_markdown_to_html(catalyst_data["summary"])}</div>'

    # Top Catalysts
    top_catalysts = catalyst_data.get('top_catalysts', [])
    if top_catalysts:
        html += '<h3 class="heading-3">Upcoming Catalysts</h3>'
        html += '<div style="display:grid; gap:0.5rem;">'
        for cat in top_catalysts:
            event_type = cat.get('event_type') or cat.get('type', 'Event')
            description = cat.get('description') or cat.get('catalyst', '')
            sentiment = cat.get('sentiment', 'neutral')
            impact = cat.get('impact_level', cat.get('impact', 'medium'))

            if sentiment == 'positive':
                bg = '#d1fae5'; border = '#10b981'; text_color = '#065f46'; icon = '&#9650;'
            elif sentiment == 'negative':
                bg = '#fee2e2'; border = '#ef4444'; text_color = '#991b1b'; icon = '&#9660;'
            else:
                bg = '#f1f5f9'; border = '#94a3b8'; text_color = '#475569'; icon = '&#9679;'

            html += f'<div style="padding:0.6rem 0.75rem; background:{bg}; border-left:3px solid {border}; border-radius:0.375rem; font-size:0.85rem;">'
            html += f'<div style="display:flex; align-items:center; gap:0.5rem;"><span style="color:{text_color}; font-size:0.7rem;">{icon}</span><span style="background:{border}20; color:{text_color}; padding:0.1rem 0.4rem; border-radius:0.25rem; font-size:0.7rem; font-weight:600; text-transform:uppercase;">{event_type}</span><span style="font-size:0.65rem; color:{text_color};">Impact: {impact}</span></div>'
            html += f'<p style="color:#334155; margin-top:0.25rem; font-size:0.85rem;">{description}</p>'
            html += '</div>'
        html += '</div>'

    # Categorized Catalysts
    categorized = catalyst_data.get('categorized', {})
    if categorized:
        if categorized.get('positive'):
            html += '<h3 class="heading-3">Positive Catalysts</h3>'
            html += '<div style="display:grid; gap:0.35rem;">'
            for item in categorized['positive']:
                desc = item.get('description', '')
                if desc:
                    html += f'<div style="padding:0.4rem 0.6rem; background:#d1fae5; border-radius:0.375rem; font-size:0.85rem; color:#065f46;">&#10003; {desc}</div>'
            html += '</div>'

        if categorized.get('negative'):
            html += '<h3 class="heading-3">Risk Factors</h3>'
            html += '<div style="display:grid; gap:0.35rem;">'
            for item in categorized['negative']:
                desc = item.get('description', '')
                if desc:
                    html += f'<div style="padding:0.4rem 0.6rem; background:#fee2e2; border-radius:0.375rem; font-size:0.85rem; color:#991b1b;">&#9888; {desc}</div>'
            html += '</div>'

    return html if html else "<p class='body-text' style='color:#94a3b8; font-style:italic;'>Catalyst analysis not available.</p>"


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
            if overall == 'positive':
                bg = '#d1fae5'; color = '#065f46'
            elif overall == 'negative':
                bg = '#fee2e2'; color = '#991b1b'
            else:
                bg = '#f1f5f9'; color = '#475569'
            html += f'<div class="mt-3" style="display:inline-flex; align-items:center; gap:0.5rem;"><span style="font-size:0.85rem; font-weight:500; color:#64748b;">Sentiment:</span><span style="background:{bg}; color:{color}; padding:0.2rem 0.6rem; border-radius:9999px; font-size:0.8rem; font-weight:600;">{overall.upper()}</span></div>'

    # Categories
    if news_data.get('categories'):
        html += '<h3 class="heading-3">News by Category</h3>'
        html += '<div style="display:flex; flex-wrap:wrap; gap:0.5rem;">'
        for cat, count in news_data['categories'].items():
            html += f'<span style="background:#f1f5f9; color:#475569; padding:0.3rem 0.6rem; border-radius:9999px; font-size:0.8rem;">{cat} <strong>{count}</strong></span>'
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

            html += f'<div class="mt-3" style="display:inline-flex; align-items:center; gap:0.5rem;"><span style="font-size:0.85rem; font-weight:500; color:#64748b;">Articles analyzed:</span><span style="background:#eef2ff; color:#4f46e5; padding:0.2rem 0.5rem; border-radius:9999px; font-size:0.85rem; font-weight:600;">{len(articles)}</span></div>'
            html += '<h3 class="heading-3">By Category</h3>'
            html += '<div style="display:flex; flex-wrap:wrap; gap:0.5rem;">'
            for cat, count in sorted(category_counts.items(), key=lambda x: -x[1]):
                html += f'<span style="background:#f1f5f9; color:#475569; padding:0.3rem 0.6rem; border-radius:9999px; font-size:0.8rem;">{cat} <strong>{count}</strong></span>'
            html += '</div>'

    return html


def format_valuation_breakdown_html(valuation_data: dict) -> str:
    """格式化目标价推导过程为 HTML 表格 + 综合卡片。"""
    if not valuation_data or not valuation_data.get('methods'):
        return ""

    methods = valuation_data['methods']
    synthesis = valuation_data.get('synthesis', {})

    html = '<h3 class="heading-2">Target Price Derivation</h3>'

    # 方法对比表
    html += '<div style="overflow-x:auto; margin-bottom:1rem;"><table class="data-table">'
    html += '<thead><tr><th>Method</th><th>Target Price</th><th>Low</th><th>High</th><th>Weight</th><th>Key Assumptions</th></tr></thead><tbody>'

    for m in methods:
        target = f"${m['target_price']:.2f}"
        low = f"${m['low_estimate']:.2f}"
        high = f"${m['high_estimate']:.2f}"
        weight = f"{m['confidence'] * 100:.0f}%"
        # 格式化假设
        parts = []
        for k, v in list(m.get('assumptions', {}).items())[:3]:
            if isinstance(v, float):
                parts.append(f"{k}: {v * 100:.1f}%" if v < 1 else f"{k}: {v:.1f}")
            else:
                parts.append(f"{k}: {v}")
        assumptions_str = "; ".join(parts) if parts else "-"

        html += (f'<tr><td style="font-weight:600;">{m["method"]}</td>'
                 f'<td style="font-weight:600; color:#6366f1;">{target}</td>'
                 f'<td>{low}</td><td>{high}</td><td>{weight}</td>'
                 f'<td style="font-size:0.75rem; color:#64748b;">{assumptions_str}</td></tr>')

    html += '</tbody></table></div>'

    # 综合结果卡片
    if synthesis and synthesis.get('target_price'):
        synth_target = synthesis['target_price']
        synth_range = synthesis.get('range', (0, 0))
        upside = synthesis.get('upside', 0)
        upside_color = '#10b981' if upside >= 0 else '#ef4444'
        upside_label = 'Upside' if upside >= 0 else 'Downside'

        html += f'''
        <div style="background:linear-gradient(135deg, #eef2ff 0%, #f5f3ff 100%); border-radius:0.75rem;
            padding:1rem 1.25rem; display:flex; justify-content:space-between; align-items:center;
            flex-wrap:wrap; gap:1rem; margin-bottom:1.5rem;">
            <div>
                <p style="color:#64748b; font-size:0.7rem; text-transform:uppercase; letter-spacing:0.05em; margin-bottom:0.15rem;">Weighted Target Price</p>
                <p style="color:#0f172a; font-size:1.5rem; font-weight:700;">${synth_target:.2f}</p>
            </div>
            <div>
                <p style="color:#64748b; font-size:0.7rem; text-transform:uppercase; letter-spacing:0.05em; margin-bottom:0.15rem;">Valuation Range</p>
                <p style="color:#0f172a; font-size:1rem; font-weight:600;">${synth_range[0]:.2f} - ${synth_range[1]:.2f}</p>
            </div>
            <div>
                <p style="color:#64748b; font-size:0.7rem; text-transform:uppercase; letter-spacing:0.05em; margin-bottom:0.15rem;">Implied {upside_label}</p>
                <p style="color:{upside_color}; font-size:1rem; font-weight:700;">{abs(upside):.1f}%</p>
            </div>
        </div>'''

    return html


def format_advanced_charts_html_professional(data: dict) -> str:
    """格式化高级图表章节为专业 HTML - 2x2 card grid，无图时生成文字版技术分析。"""
    stock_price_chart = data.get('stock_price_chart_path', '')
    technical_chart = data.get('technical_indicators_path', '')
    radar_chart = data.get('financial_radar_path', '')
    cashflow_chart = data.get('cash_flow_chart_path', '')

    charts = []
    if stock_price_chart:
        charts.append(('Stock Price Performance', stock_price_chart, 'Price with 20/50/200-day moving averages'))
    if technical_chart:
        charts.append(('Technical Indicators', technical_chart, 'RSI & MACD momentum signals'))
    if radar_chart:
        charts.append(('Financial Ratios', radar_chart, 'Multi-dimensional financial health'))
    if cashflow_chart:
        charts.append(('Cash Flow Analysis', cashflow_chart, 'Operating, investing & financing'))

    if charts:
        html = '<div style="display:grid; grid-template-columns: 1fr 1fr; gap:1rem;">'
        for title, path, subtitle in charts:
            html += f'''
            <div class="chart-container" style="text-align:left;">
                <p style="font-weight:600; color:#0f172a; font-size:0.9rem; margin-bottom:0.15rem;">{title}</p>
                <p style="color:#94a3b8; font-size:0.75rem; margin-bottom:0.75rem;">{subtitle}</p>
                <img src="{path}" alt="{title}" style="border-radius:0.5rem;">
            </div>
            '''
        html += '</div>'
        return html

    # Fallback: 文字版技术分析 — 使用真实指标数据
    ticker = data.get('company_ticker', 'Stock')
    share_price = data.get('share_price', 'N/A')
    w52 = data.get('52w_range', data.get('week_52_range', 'N/A'))
    ti = data.get('technical_indicators', {})

    def _signal_badge(signal):
        if not signal or signal == 'N/A':
            return '<span style="background:#f1f5f9; color:#64748b; padding:0.15rem 0.5rem; border-radius:9999px; font-size:0.75rem; font-weight:600;">N/A</span>'
        colors = {
            'Bullish': ('#ecfdf5', '#059669'), 'Neutral-Bullish': ('#ecfdf5', '#059669'),
            'Bearish': ('#fef2f2', '#dc2626'), 'Neutral-Bearish': ('#fef2f2', '#dc2626'),
            'Overbought': ('#fef2f2', '#dc2626'), 'Oversold': ('#ecfdf5', '#059669'),
            'High Activity': ('#eff6ff', '#2563eb'), 'Low Activity': ('#fefce8', '#ca8a04'),
        }
        bg, fg = colors.get(signal, ('#f1f5f9', '#64748b'))
        return f'<span style="background:{bg}; color:{fg}; padding:0.15rem 0.5rem; border-radius:9999px; font-size:0.75rem; font-weight:600;">{signal}</span>'

    def _overall_badge(signal):
        if signal == 'Bullish':
            return '<span style="background:#059669; color:white; padding:0.3rem 0.8rem; border-radius:9999px; font-size:0.85rem; font-weight:700;">Bullish</span>'
        elif signal == 'Bearish':
            return '<span style="background:#dc2626; color:white; padding:0.3rem 0.8rem; border-radius:9999px; font-size:0.85rem; font-weight:700;">Bearish</span>'
        else:
            return '<span style="background:#64748b; color:white; padding:0.3rem 0.8rem; border-radius:9999px; font-size:0.85rem; font-weight:700;">Neutral</span>'

    card_style = 'background:#f8fafc; border-radius:0.5rem; padding:0.75rem; border:1px solid #e2e8f0;'
    label_style = 'font-weight:600; color:#0f172a; font-size:0.85rem; margin-bottom:0.25rem;'
    val_style = 'font-size:0.8rem; color:#334155; line-height:1.6;'

    html = '<div class="content-card">'
    html += f'<h3 class="heading-3" style="margin-top:0;">Technical Overview — {ticker}</h3>'
    html += f'<p class="body-text">Current Price: <strong>{share_price}</strong>'
    if w52 and w52 != 'N/A':
        html += f' &nbsp;|&nbsp; 52-Week Range: <strong>{w52}</strong>'
    html += '</p>'

    # Overall signal
    overall = ti.get('overall_signal', 'N/A')
    if overall and overall != 'N/A':
        html += f'<div style="margin:0.75rem 0; display:flex; align-items:center; gap:0.5rem;">'
        html += f'<span style="color:#64748b; font-size:0.8rem; font-weight:500;">Overall Technical Signal:</span>'
        html += _overall_badge(overall)
        html += '</div>'

    html += '<div style="display:grid; grid-template-columns:1fr 1fr; gap:0.75rem; margin-top:0.5rem;">'

    # 1. Moving Averages
    sma50 = ti.get('sma50')
    sma200 = ti.get('sma200')
    ma_sig = ti.get('ma_signal', 'N/A')
    ma_detail = ''
    if sma50:
        ma_detail += f'SMA 50: <strong>${sma50:.2f}</strong>'
    if sma200:
        ma_detail += f' &nbsp;|&nbsp; SMA 200: <strong>${sma200:.2f}</strong>'
    if not ma_detail:
        ma_detail = 'Price data not available for SMA calculation.'
    html += f'<div style="{card_style}"><p style="{label_style}">Moving Averages {_signal_badge(ma_sig)}</p><p style="{val_style}">{ma_detail}</p></div>'

    # 2. RSI
    rsi = ti.get('rsi14')
    rsi_sig = ti.get('rsi_signal', 'N/A')
    rsi_detail = f'RSI (14): <strong>{rsi:.1f}</strong>' if rsi else 'RSI data not available.'
    if rsi:
        if rsi > 70:
            rsi_detail += ' — Overbought territory, potential pullback.'
        elif rsi < 30:
            rsi_detail += ' — Oversold territory, potential bounce.'
        elif rsi > 55:
            rsi_detail += ' — Bullish momentum range.'
        elif rsi < 45:
            rsi_detail += ' — Bearish momentum range.'
        else:
            rsi_detail += ' — Neutral zone.'
    html += f'<div style="{card_style}"><p style="{label_style}">RSI {_signal_badge(rsi_sig)}</p><p style="{val_style}">{rsi_detail}</p></div>'

    # 3. MACD
    macd_val = ti.get('macd')
    macd_sig_val = ti.get('macd_signal')
    macd_hist = ti.get('macd_histogram')
    macd_sig = ti.get('macd_signal_label', 'N/A')
    if macd_val is not None:
        macd_detail = f'MACD: <strong>{macd_val:.2f}</strong> | Signal: <strong>{macd_sig_val:.2f}</strong> | Histogram: <strong>{macd_hist:.2f}</strong>'
    else:
        macd_detail = 'MACD data not available.'
    html += f'<div style="{card_style}"><p style="{label_style}">MACD {_signal_badge(macd_sig)}</p><p style="{val_style}">{macd_detail}</p></div>'

    # 4. Volume
    avg_vol = ti.get('avg_volume_20d')
    latest_vol = ti.get('latest_volume')
    vol_sig = ti.get('volume_signal', 'N/A')
    if avg_vol and latest_vol:
        vol_ratio = latest_vol / avg_vol if avg_vol > 0 else 0
        vol_detail = f'Latest: <strong>{latest_vol/1e6:.1f}M</strong> | 20d Avg: <strong>{avg_vol/1e6:.1f}M</strong> | Ratio: <strong>{vol_ratio:.2f}x</strong>'
    else:
        vol_detail = 'Volume data not available.'
    html += f'<div style="{card_style}"><p style="{label_style}">Volume {_signal_badge(vol_sig)}</p><p style="{val_style}">{vol_detail}</p></div>'

    html += '</div></div>'
    return html


def _derive_rating(share_price, target_price, api_rating: str) -> str:
    """根据 target_price vs share_price 推导评级，忽略可能矛盾的外部 API 评级。

    逻辑：
    - upside >= 15%  → Buy
    - upside 5~15%   → Outperform
    - upside -5~5%   → Hold
    - upside -15~-5%  → Underperform
    - upside <= -15% → Sell
    如果价格数据无效，fallback 到 API 评级。
    """
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


def get_rating_color_class(rating: str) -> str:
    """根据评级返回颜色类"""
    if rating in ['Buy', 'Outperform', 'Overweight', 'Strong Buy']:
        return 'rating-buy'
    elif rating in ['Sell', 'Underperform', 'Underweight', 'Strong Sell']:
        return 'rating-sell'
    else:
        return 'rating-hold'


def render_professional_html_report(data: dict) -> str:
    """渲染专业 HTML 报告"""
    from datetime import datetime

    # Prepare data with defaults
    report_data = {
        'company_name_full': data.get('company_name_full', 'Company'),
        'company_ticker': data.get('company_ticker', 'TICK'),
        'sector': data.get('sector', 'Technology'),
        'rating': _derive_rating(data.get('share_price', 'N/A'), data.get('target_price', 'N/A'), data.get('rating', 'N/A')),
        'rating_color_class': get_rating_color_class(_derive_rating(data.get('share_price', 'N/A'), data.get('target_price', 'N/A'), data.get('rating', 'N/A'))),
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
        'company_overview': _markdown_to_html(data.get('company_overview', 'Company overview not available.')),
        'investment_overview': _markdown_to_html(data.get('investment_overview', 'Investment overview not available.')),
        'revenue_analysis_text': data.get('revenue_analysis_text', 'Revenue analysis demonstrates the company\'s financial performance over the analysis period.'),
        'revenue_key_figures_html': format_key_figures_html(data.get('revenue_key_figures', {})),
        'revenue_chart_path': data.get('revenue_chart_path', ''),
        'eps_analysis_text': data.get('eps_analysis_text', 'Earnings analysis shows the company\'s profitability trends.'),
        'eps_key_figures_html': format_key_figures_html(data.get('eps_key_figures', {})),
        'eps_pe_chart_path': data.get('eps_pe_chart_path', ''),
        'valuation_overview': _markdown_to_html(data.get('valuation_overview', 'Valuation analysis not available.')),
        'valuation_breakdown_html': format_valuation_breakdown_html(data.get('valuation_analysis', {})),
        'peer_ev_ebitda_table_html': data.get('peer_ev_ebitda_table_html', '<p class="body-text" style="color:#94a3b8; font-style:italic;">Peer comparison data not available.</p>'),
        'ev_ebitda_chart_path': data.get('ev_ebitda_chart_path', ''),
        'news_summary': _markdown_to_html(data.get('news_summary', 'Recent news coverage not available.')),
        'enhanced_news_html': format_enhanced_news_html_professional(data.get('enhanced_news', {})),
        'sensitivity_analysis_html': format_sensitivity_analysis_html_professional(data.get('sensitivity_analysis', {})),
        'catalyst_analysis_html': format_catalyst_analysis_html_professional(data.get('catalyst_analysis', {})),
        'advanced_charts_section_html': format_advanced_charts_html_professional(data),
        'peer_ebitda_table_html': data.get('peer_ebitda_table_html', '<p class="body-text" style="color:#94a3b8; font-style:italic;">Peer EBITDA data not available.</p>'),
        'peer_ev_ebitda_table_html_comp': data.get('peer_ev_ebitda_table_html', '<p class="body-text" style="color:#94a3b8; font-style:italic;">Peer EV/EBITDA data not available.</p>'),
        'competitor_analysis': _markdown_to_html(data.get('competitor_analysis', 'Competitive analysis not available.')),
        'risks_html': format_risks_to_html(data.get('risks', '')),
        'major_takeaways_html': format_takeaways_to_html(data.get('major_takeaways', '')),
        'financial_summary_table_html': data.get('financial_summary_table_html', '<p class="body-text" style="color:#94a3b8; font-style:italic;">Financial summary not available.</p>'),
        'credit_cashflow_table_html': data.get('credit_cashflow_table_html', '<p class="body-text" style="color:#94a3b8; font-style:italic;">Credit & cashflow metrics not available.</p>'),
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
