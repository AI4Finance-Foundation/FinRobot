#!/usr/bin/env python
# coding: utf-8

import os
import re as _re
import pandas as pd


def _auto_bold_key_data(text: str) -> str:
    """自动加粗关键金融数据。"""
    if not text or '<strong>' in text:
        return text
    # $金额+单位
    text = _re.sub(
        r'(\$[\d,.]+\s*(?:billion|million|trillion|bn|mn|trn|B|M|K|T))',
        r'<strong>\1</strong>', text, flags=_re.IGNORECASE)
    # 百分比
    text = _re.sub(r'(?<!\d)([\-+]?\d+\.?\d*%)', r'<strong>\1</strong>', text)
    # 倍数
    text = _re.sub(r'\b(\d+\.?\d*x)\b', r'<strong>\1</strong>', text)
    # 清理嵌套 strong
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
            html_lines.append(f'<h4 style="font-size:11px; font-weight:600; color:#002855; margin:8px 0 4px 0; text-transform:uppercase; letter-spacing:0.03em;">{content}</h4>')
            continue
        if stripped.startswith('## '):
            if in_list:
                html_lines.append('</ul>')
                in_list = False
            content = _re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', stripped[3:])
            html_lines.append(f'<h3 style="font-size:12px; font-weight:600; color:#002855; margin:10px 0 6px 0;">{content}</h3>')
            continue
        # list items
        if stripped.startswith('- '):
            if not in_list:
                html_lines.append('<ul style="list-style:none; padding-left:0; margin:3px 0;">')
                in_list = True
            item = _re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', stripped[2:])
            html_lines.append(f'<li style="padding-left:10px; margin-bottom:2px; font-size:11px; color:#1a1a1a;">&#9642; {item}</li>')
            continue
        # sub-list items
        if _re.match(r'^\s{2,}-\s', line):
            item_text = _re.sub(r'^\s+-\s*', '', line)
            item_text = _re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', item_text)
            if not in_list:
                html_lines.append('<ul style="list-style:none; padding-left:0; margin:3px 0;">')
                in_list = True
            html_lines.append(f'<li style="padding-left:20px; margin-bottom:1px; font-size:10px; color:#333;">– {item_text}</li>')
            continue
        if in_list:
            html_lines.append('</ul>')
            in_list = False
        content = _re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', stripped)
        content = _auto_bold_key_data(content)
        if _is_conclusion_sentence(stripped):
            html_lines.append(f'<p style="margin-bottom:3px; font-size:11px; color:#1a1a1a; background:#f0f9ff; border-left:3px solid #002855; padding:4px 8px; font-weight:500;">{content}</p>')
        else:
            html_lines.append(f'<p style="margin-bottom:3px; font-size:11px; color:#1a1a1a;">{content}</p>')
    if in_list:
        html_lines.append('</ul>')
    return '\n'.join(html_lines)

HTML_TEMPLATE_PAGE_1 = """
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta content="width=device-width, initial-scale=1.0" name="viewport"/>
  <title>
   US EQUITY RESEARCH - {company_name_ticker}
  </title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&amp;display=swap" rel="stylesheet"/>
  <style>
   body {{ font-family: 'Inter', sans-serif; font-weight: 400; color: #1a1a1a; }}
   h1, h2, h3.serif {{ font-family: 'Georgia', 'Times New Roman', serif; }}
   @page {{
     size: 8.5in 11in;
     margin: 0;
   }}
   .page-container {{
     width: 8.5in;
     height: 11in;
     padding: 0.5in;
     box-sizing: border-box;
     display: flex;
     flex-direction: column;
   }}
   .page-container header {{}}
   .page-container main {{ flex-grow: 1; }}
   .page-container footer {{
     flex-shrink: 0;
     margin-top: auto;
   }}
   .financial-table tr:not(:last-child) {{ border-bottom: 1px solid #d1d5db; }}
   .financial-table td {{ padding: 5px 0; font-size: 11px; }}
   .data-source {{ border-bottom: 1px dotted #666; cursor: help; }}
   .ai-generated {{ position: relative; border-left: 2px solid #8B6914; padding-left: 8px; margin: 8px 0; }}
   .ai-badge {{ display: inline-block; background: #8B6914; color: white; font-size: 8px; padding: 1px 4px; border-radius: 2px; margin-left: 4px; }}
   .executive-summary {{ background: #f5f7fa; padding: 12px; margin-bottom: 16px; border-top: 2px solid #002855; }}
   .executive-summary h3 {{ color: #002855; margin-bottom: 8px; }}
   .section-summary {{ background: #f5f7fa; padding: 8px; border-left: 3px solid #002855; margin-top: 8px; font-style: italic; }}
   .catalyst-positive {{ color: #006633; }}
   .catalyst-negative {{ color: #cc0000; }}
   .catalyst-neutral {{ color: #555555; }}
   .section-label {{
     font-size: 13px;
     font-weight: 600;
     color: #002855;
     text-transform: uppercase;
     letter-spacing: 0.04em;
     margin-bottom: 6px;
     padding-bottom: 4px;
     border-bottom: 1px solid #d1d5db;
   }}
  </style>
</head>
<body class="bg-white text-xs">
  <div class="page-container mx-auto">
   <header class="mb-6">
    <div class="flex justify-between items-center mb-2">
     <div></div>
     <p style="color: #555555; font-size: 11px;">
      {research_source}
     </p>
    </div>
    <div style="background: #002855;" class="text-white px-3 py-1 w-full">
     <h1 class="text-2xl font-normal" style="font-family: 'Georgia', 'Times New Roman', serif; letter-spacing: 0.03em;">
      US EQUITY RESEARCH
     </h1>
    </div>
    <div style="height: 2px; background: #8B6914; width: 100%;"></div>
    <p style="color: #555555; font-size: 11px;" class="text-right mt-1">
     {report_date}
    </p>
   </header>
   <main>
    <div class="flex justify-between mb-6">
     <div>
      <h2 class="text-[20px] mb-2" style="font-family: 'Georgia', 'Times New Roman', serif; color: #002855; font-weight: 600;">
       {company_name_full}
      </h2>
      <p style="color: #333333; font-size: 13px; line-height: 1.5;">
       {tagline}
      </p>
     </div>
     <div>
      <p style="color: #002855; font-size: 13px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em;">
       Analysts
      </p>
      {analyst_contacts_html}
     </div>
    </div>
    <div class="flex gap-6">
     <div class="w-2/3">
      <h3 class="section-label">
       Company Overview
      </h3>
      <p class="mb-4 text-xs leading-tight" style="color: #1a1a1a;">
       {company_overview}
      </p>
      <h3 class="section-label">
       Investment Update
      </h3>
      <p class="mb-4 text-xs leading-tight" style="color: #1a1a1a;">
       {investment_overview}
      </p>
      <h3 class="section-label">
       Recent News Summary
      </h3>
      <p class="mb-4 text-xs leading-tight" style="color: #1a1a1a;">
       {news_summary}
      </p>
      <h3 class="section-label">
       Valuation
      </h3>
      <p class="mb-4 text-xs leading-tight" style="color: #1a1a1a;">
       {valuation_overview}
      </p>
      <h3 class="section-label">
       Risks
      </h3>
      <p class="mb-4 text-xs leading-tight" style="color: #1a1a1a;">
       {risks}
      </p>
     </div>
     <div class="w-1/3">
      <h3 class="section-label">
       Key Financial Data
      </h3>
      <div style="background: #f5f7fa; border-top: 2px solid #002855;" class="p-3 mb-4">
       <table class="w-full text-xs financial-table">
        <tr>
          <td style="color: #555555;">Bloomberg Ticker</td>
          <td class="text-right" style="color: #1a1a1a; font-weight: 500;">{company_ticker} US</td>
        </tr>
        <tr>
          <td style="color: #555555;">Sector</td>
          <td class="text-right" style="color: #1a1a1a; font-weight: 500;">{sector}</td>
        </tr>
        <tr>
          <td style="color: #555555;">Share Price (USD)</td>
          <td class="text-right" style="color: #1a1a1a; font-weight: 500;">{share_price}</td>
        </tr>
        <tr>
          <td style="color: #555555;">Rating</td>
          <td class="text-right" style="color: #1a1a1a; font-weight: 600;">{rating}</td>
        </tr>
        <tr>
          <td style="color: #555555;">12-mth Target Price (USD)</td>
          <td class="text-right" style="color: #1a1a1a; font-weight: 500;">{target_price}</td>
        </tr>
        <tr>
          <td style="color: #555555;">Market Cap (USDb)</td>
          <td class="text-right" style="color: #1a1a1a; font-weight: 500;">{market_cap}</td>
        </tr>
        <tr>
          <td style="color: #555555;">Volume (m shares)</td>
          <td class="text-right" style="color: #1a1a1a; font-weight: 500;">{volume}</td>
        </tr>
        <tr>
          <td style="color: #555555;">Free float (%)</td>
          <td class="text-right" style="color: #1a1a1a; font-weight: 500;">{free_float}</td>
        </tr>
        <tr>
          <td style="color: #555555;">Dividend yield (%)</td>
          <td class="text-right" style="color: #1a1a1a; font-weight: 500;">{dividend_yield}</td>
        </tr>
        <tr>
          <td style="color: #555555;">Net Debt to Equity (%)</td>
          <td class="text-right" style="color: #1a1a1a; font-weight: 500;">{net_debt_to_equity}</td>
        </tr>
        <tr>
          <td style="color: #555555;">Fwd. P/E (x)</td>
          <td class="text-right" style="color: #1a1a1a; font-weight: 500;">{fwd_pe}</td>
        </tr>
        <tr>
          <td style="color: #555555;">P/Book (x)</td>
          <td class="text-right" style="color: #1a1a1a; font-weight: 500;">{pb_ratio}</td>
        </tr>
        <tr>
          <td style="color: #555555;">ROE (%)</td>
          <td class="text-right" style="color: #1a1a1a; font-weight: 500;">{roe}</td>
        </tr>
       </table>
      </div>
      <p style="font-size: 10px; color: #555555; font-style: italic;" class="mb-2">
       Closing Price as of {closing_price_date}
      </p>
      <p style="font-size: 10px; color: #888888;">
       Source: {data_source_text}
      </p>
     </div>
    </div>
   </main>
   <footer class="pt-4" style="border-top: 1px solid #002855;">
    <p style="font-size: 9px; color: #555555; line-height: 1.4;">{disclaimer_text}</p>
    <div class="text-right">
     <img alt="Research Group logo" class="inline-block" height="60" src="https://github.com/AI4Finance-Foundation/FinGPT/assets/31713746/e0371951-1ce1-488e-aa25-0992dafcc139" width="100" style="margin-top: -10px;"/>
    </div>
   </footer>
  </div>
 </body>
</html>
"""

HTML_TEMPLATE_PAGE_2_FINANCIAL_SUMMARY = """
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta content="width=device-width, initial-scale=1.0" name="viewport"/>
  <title>{company_name_ticker} - Competitor Analysis</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&display=swap" rel="stylesheet"/>
  <style>
   body {{ font-family: 'Inter', sans-serif; font-weight: 400; color: #1a1a1a; }}
   @page {{ size: 8.5in 11in; margin: 0; }}
   .page-container {{ width: 8.5in; height: 11in; padding: 0.5in; box-sizing: border-box; display: flex; flex-direction: column; }}
   .page-container header {{ margin-bottom: 1rem; }}
   .page-container main {{ flex-grow: 1; }}
   .page-container footer {{ flex-shrink: 0; margin-top: auto; }}
   table td, table th {{ padding: 2px 4px; }}
  </style>
</head>
<body class="bg-white text-xs">
  <div class="page-container mx-auto">
    <header>
      <div class="flex justify-between items-center mb-2" style="border-bottom: 2px solid #002855; padding-bottom: 6px;">
        <div><h2 class="text-lg" style="font-family: 'Georgia', 'Times New Roman', serif; font-weight: 600; color: #002855;">{company_name_full} ({company_ticker})</h2></div>
        <p style="color: #555555; font-size: 11px;">
          {research_source}
        </p>
      </div>
    </header>
    <main>
      <div class="w-full">
        <div class="mb-6">
          <h2 style="color: #002855; font-size: 13px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em; border-bottom: 1px solid #d1d5db; padding-bottom: 4px;" class="mb-3">Competitor Analysis</h2>
          <p class="text-xs leading-tight mb-4" style="color: #1a1a1a;">
            {competitor_analysis}
          </p>

          <div style="background: #f5f7fa; border-top: 2px solid #002855; padding: 12px 16px;" class="mb-6">
            <h3 style="font-weight: 600; font-size: 11px; color: #002855; text-transform: uppercase; letter-spacing: 0.03em;" class="mb-3">Major takeaways from {company_ticker} and peers:</h3>
            <div class="text-xs leading-tight whitespace-pre-line" style="color: #1a1a1a;">
              {major_takeaways}
            </div>
          </div>
        </div>

        <div class="mb-4">
          <h2 style="color: #002855; font-size: 13px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em; border-bottom: 1px solid #d1d5db; padding-bottom: 4px;" class="mb-3">Financial Metrics and Peer Comparison Charts</h2>
          <div class="grid grid-cols-3 gap-3">
              <div>
                  <h3 style="font-size: 10px; color: #555555; text-transform: uppercase; letter-spacing: 0.03em; font-weight: 600;" class="mb-2">Revenue & EBITDA Trend</h3>
                  <img src="{revenue_chart_path}" alt="Revenue and EBITDA Trend" class="w-full"/>
              </div>
              <div>
                  <h3 style="font-size: 10px; color: #555555; text-transform: uppercase; letter-spacing: 0.03em; font-weight: 600;" class="mb-2">EPS x PE Trend Analysis</h3>
                  <img src="{eps_pe_chart_path}" alt="EPS x PE Trend Analysis" class="w-full"/>
              </div>
              <div>
                  <h3 style="font-size: 10px; color: #555555; text-transform: uppercase; letter-spacing: 0.03em; font-weight: 600;" class="mb-2">EV/EBITDA Peer Comparison</h3>
                  <img src="{ev_ebitda_chart_path}" alt="EV/EBITDA Peer Comparison" class="w-full"/>
              </div>
          </div>
        </div>
      </div>
    </main>
    <footer class="pt-4" style="border-top: 1px solid #002855;">
      <p style="font-size: 9px; color: #555555; line-height: 1.4;">{disclaimer_text}</p>
      <div class="text-right">
        <img alt="Research Group logo" class="inline-block" height="60" src="https://github.com/AI4Finance-Foundation/FinGPT/assets/31713746/e0371951-1ce1-488e-aa25-0992dafcc139" width="100" style="margin-top: -10px;"/>
      </div>
    </footer>
  </div>
 </body>
</html>
"""

HTML_TEMPLATE_PAGE_3_PEER_COMPARISON = """
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta content="width=device-width, initial-scale=1.0" name="viewport"/>
  <title>{company_name_ticker} - Financial Summary & Peer Comparison</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&display=swap" rel="stylesheet"/>
  <style>
   body {{ font-family: 'Inter', sans-serif; font-weight: 400; color: #1a1a1a; }}
   @page {{ size: 8.5in 11in; margin: 0; }}
   .page-container {{ width: 8.5in; height: 11in; padding: 0.5in; box-sizing: border-box; display: flex; flex-direction: column; }}
   .page-container header {{ margin-bottom: 1rem; }}
   .page-container main {{ flex-grow: 1; }}
   .page-container footer {{ flex-shrink: 0; margin-top: auto; }}
   table {{ width: 100%; border-collapse: collapse; font-size: 11px; }}
   table th {{ background: #002855; color: white; padding: 5px 6px; text-align: right; font-weight: 500; font-size: 10px; text-transform: uppercase; letter-spacing: 0.03em; }}
   table th:first-child {{ text-align: left; }}
   table td {{ padding: 4px 6px; text-align: right; border-bottom: 1px solid #d1d5db; }}
   table td:first-child {{ text-align: left; font-weight: 500; }}
   table tr:nth-child(even) {{ background: #f5f7fa; }}
  </style>
</head>
<body class="bg-white text-xs">
  <div class="page-container mx-auto">
    <header>
      <div class="flex justify-between items-center mb-2" style="border-bottom: 2px solid #002855; padding-bottom: 6px;">
        <div><h2 class="text-lg" style="font-family: 'Georgia', 'Times New Roman', serif; font-weight: 600; color: #002855;">{company_name_full} ({company_ticker})</h2></div>
        <p style="color: #555555; font-size: 11px;">
          {research_source}
        </p>
      </div>
    </header>
    <main>
      <div class="w-full">
        <div class="mb-6">
          <h2 style="color: #002855; font-size: 13px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em; border-bottom: 1px solid #d1d5db; padding-bottom: 4px;" class="mb-3">Financial Summary (USD, unless otherwise stated)</h2>
          {financial_summary_table_html}
        </div>

        <div class="mb-4">
          <h2 style="color: #002855; font-size: 13px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em; border-bottom: 1px solid #d1d5db; padding-bottom: 4px;" class="mb-3">Credit & Cashflow Metrics</h2>
          {credit_cashflow_table_html}
        </div>

        <div class="mb-4">
          <h2 style="color: #002855; font-size: 13px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em; border-bottom: 1px solid #d1d5db; padding-bottom: 4px;" class="mb-3">Peer Valuation Metrics (EV/EBITDA, x)</h2>
          {peer_ev_ebitda_table_html}
        </div>

      </div>
    </main>
    <footer class="pt-4" style="border-top: 1px solid #002855;">
      <p style="font-size: 9px; color: #555555; line-height: 1.4;">{disclaimer_text}</p>
      <div class="text-right">
        <img alt="Research Group logo" class="inline-block" height="60" src="https://github.com/AI4Finance-Foundation/FinGPT/assets/31713746/e0371951-1ce1-488e-aa25-0992dafcc139" width="100" style="margin-top: -10px;"/>
      </div>
    </footer>
  </div>
 </body>
</html>
"""

def _format_value(val):
    """Helper function to format numbers for HTML display."""
    if isinstance(val, str):
        # Keep percentage strings and ratio strings as is
        if '%' in val or 'x' in val or val in ['N/A', '-']:
            return val
        # Try to parse as number
        try:
            num_val = float(val)
            if abs(num_val) >= 1_000_000_000:
                return f"${num_val/1_000_000_000:,.1f}B"
            elif abs(num_val) >= 1_000_000:
                return f"${num_val/1_000_000:,.1f}M"
            elif abs(num_val) >= 1_000:
                return f"{num_val:,.0f}"
            else:
                return val  # Keep as is for ratios/small numbers
        except ValueError:
            return val  # Keep as string if can't parse
    
    if isinstance(val, (int, float)):
        if pd.isna(val):
            return "-"
        if abs(val) >= 1_000_000_000:
            return f"${val/1_000_000_000:,.1f}B"
        if abs(val) >= 1_000_000:
            return f"${val/1_000_000:,.1f}M"
        if abs(val) >= 1_000:
            return f"{val:,.0f}"
        # For ratios or multipliers, format to appropriate decimal places
        if 0 < abs(val) < 10:
            return f"{val:.2f}"
        elif 10 <= abs(val) < 100:
            return f"{val:.1f}"
        else:
            return f"{val:.1f}x"
    
    return val if pd.notna(val) else "-"


def format_dataframe_to_html_table(df, table_id="financial-table", header_class="bg-gray-200 font-semibold", row_class_cycle=["bg-white", "bg-gray-50"]):
    """Converts a pandas DataFrame to an HTML table with investment bank styling."""
    if df is None or df.empty:
        return "<p>No data available.</p>"

    html = f"<table id='{table_id}' style='width:100%; border-collapse:collapse; font-size:11px;'>\n"
    html += "  <thead>\n    <tr style='background:#002855; color:white;'>\n"

    index_header = df.index.name if df.index.name else ""
    html += f"      <th style='text-align:left; padding:5px 6px; font-weight:500; font-size:10px; text-transform:uppercase; letter-spacing:0.03em;'>{index_header}</th>\n"

    for col_name in df.columns:
        html += f"      <th style='text-align:right; padding:5px 6px; font-weight:500; font-size:10px; text-transform:uppercase; letter-spacing:0.03em;'>{col_name}</th>\n"
    html += "    </tr>\n  </thead>\n"
    html += "  <tbody>\n"
    for i, (index_val, row) in enumerate(df.iterrows()):
        bg = "#f5f7fa" if i % 2 == 1 else "#ffffff"
        html += f"    <tr style='background:{bg}; border-bottom:1px solid #d1d5db;'>\n"
        html += f"      <td style='text-align:left; padding:4px 6px; font-weight:500;'>{index_val}</td>\n"
        for val in row:
            formatted_val = _format_value(val)
            html += f"      <td style='text-align:right; padding:4px 6px;'>{formatted_val}</td>\n"
        html += "    </tr>\n"
    html += "  </tbody>\n</table>"
    return html


# Page 4: Sensitivity & Catalyst Analysis
HTML_TEMPLATE_PAGE_4_SENSITIVITY_CATALYST = """
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta content="width=device-width, initial-scale=1.0" name="viewport"/>
  <title>{company_name_ticker} - Sensitivity & Catalyst Analysis</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&display=swap" rel="stylesheet"/>
  <style>
   body {{ font-family: 'Inter', sans-serif; font-weight: 400; color: #1a1a1a; }}
   @page {{ size: 8.5in 11in; margin: 0; }}
   .page-container {{ width: 8.5in; height: 11in; padding: 0.5in; box-sizing: border-box; display: flex; flex-direction: column; }}
   .catalyst-positive {{ color: #006633; background: #E8F5E9; padding: 2px 6px; display: inline-block; }}
   .catalyst-negative {{ color: #cc0000; background: #FFEBEE; padding: 2px 6px; display: inline-block; }}
   .catalyst-neutral {{ color: #555555; background: #F5F5F5; padding: 2px 6px; display: inline-block; }}
  </style>
</head>
<body class="bg-white text-xs">
  <div class="page-container mx-auto">
    <header>
      <div class="flex justify-between items-center mb-2" style="border-bottom: 2px solid #002855; padding-bottom: 6px;">
        <div><h2 class="text-lg" style="font-family: 'Georgia', 'Times New Roman', serif; font-weight: 600; color: #002855;">{company_name_full} ({company_ticker})</h2></div>
        <p style="color: #555555; font-size: 11px;">{research_source}</p>
      </div>
      <div style="background: #002855;" class="text-white px-3 py-1 w-full mb-4">
        <h1 class="text-xl font-normal" style="font-family: 'Georgia', 'Times New Roman', serif; letter-spacing: 0.03em;">SENSITIVITY & CATALYST ANALYSIS</h1>
      </div>
    </header>
    <main class="flex-grow">
      <div class="mb-6">
        <h2 style="color: #002855; font-size: 13px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em; border-bottom: 1px solid #d1d5db; padding-bottom: 4px;" class="mb-3">Sensitivity Analysis</h2>
        <div class="text-xs leading-tight">{sensitivity_analysis_html}</div>
      </div>
      <div class="mb-6">
        <h2 style="color: #002855; font-size: 13px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em; border-bottom: 1px solid #d1d5db; padding-bottom: 4px;" class="mb-3">Key Catalysts</h2>
        <div class="text-xs leading-tight">{catalyst_analysis_html}</div>
      </div>
    </main>
    <footer class="pt-4 mt-auto" style="border-top: 1px solid #002855;">
      <p style="font-size: 9px; color: #555555; line-height: 1.4;">{disclaimer_text}</p>
      <div class="text-right">
        <img alt="Research Group logo" class="inline-block" height="60" src="https://github.com/AI4Finance-Foundation/FinGPT/assets/31713746/e0371951-1ce1-488e-aa25-0992dafcc139" width="100"/>
      </div>
    </footer>
  </div>
</body>
</html>
"""

# Page 5: Enhanced News & Charts
HTML_TEMPLATE_PAGE_5_NEWS_CHARTS = """
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta content="width=device-width, initial-scale=1.0" name="viewport"/>
  <title>{company_name_ticker} - News & Enhanced Charts</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&display=swap" rel="stylesheet"/>
  <style>
   body {{ font-family: 'Inter', sans-serif; font-weight: 400; color: #1a1a1a; }}
   @page {{ size: 8.5in 11in; margin: 0; }}
   .page-container {{ width: 8.5in; height: 11in; padding: 0.5in; box-sizing: border-box; display: flex; flex-direction: column; }}
  </style>
</head>
<body class="bg-white text-xs">
  <div class="page-container mx-auto">
    <header>
      <div class="flex justify-between items-center mb-2" style="border-bottom: 2px solid #002855; padding-bottom: 6px;">
        <div><h2 class="text-lg" style="font-family: 'Georgia', 'Times New Roman', serif; font-weight: 600; color: #002855;">{company_name_full} ({company_ticker})</h2></div>
        <p style="color: #555555; font-size: 11px;">{research_source}</p>
      </div>
      <div style="background: #002855;" class="text-white px-3 py-1 w-full mb-4">
        <h1 class="text-xl font-normal" style="font-family: 'Georgia', 'Times New Roman', serif; letter-spacing: 0.03em;">NEWS & ENHANCED CHARTS</h1>
      </div>
    </header>
    <main class="flex-grow">
      <div class="mb-6">
        <h2 style="color: #002855; font-size: 13px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em; border-bottom: 1px solid #d1d5db; padding-bottom: 4px;" class="mb-3">News Impact Analysis</h2>
        <div class="text-xs leading-tight">{enhanced_news_html}</div>
      </div>
      <div class="mb-6">
        <h2 style="color: #002855; font-size: 13px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em; border-bottom: 1px solid #d1d5db; padding-bottom: 4px;" class="mb-3">Enhanced Charts</h2>
        <div class="grid grid-cols-2 gap-3">{enhanced_charts_html}</div>
      </div>
    </main>
    <footer class="pt-4 mt-auto" style="border-top: 1px solid #002855;">
      <p style="font-size: 9px; color: #555555; line-height: 1.4;">{disclaimer_text}</p>
      <div class="text-right">
        <img alt="Research Group logo" class="inline-block" height="60" src="https://github.com/AI4Finance-Foundation/FinGPT/assets/31713746/e0371951-1ce1-488e-aa25-0992dafcc139" width="100"/>
      </div>
    </footer>
  </div>
</body>
</html>
"""

# Keep backward compatibility alias
HTML_TEMPLATE_PAGE_4_ENHANCED_ANALYSIS = HTML_TEMPLATE_PAGE_4_SENSITIVITY_CATALYST


def _derive_rating(share_price, target_price, api_rating: str) -> str:
    """根据 target_price vs share_price 推导评级。"""
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


def format_valuation_breakdown_html(valuation_data: dict) -> str:
    """格式化目标价推导过程为 HTML 表格 + 综合卡片（投行风格）。"""
    if not valuation_data or not valuation_data.get('methods'):
        return ""

    methods = valuation_data['methods']
    synthesis = valuation_data.get('synthesis', {})

    html = '<h3 class="section-label mb-2">Target Price Derivation</h3>'

    html += '<table class="w-full text-xs" style="margin-bottom:12px;">'
    html += '<thead><tr><th style="text-align:left;">Method</th><th>Target Price</th><th>Low</th><th>High</th><th>Weight</th><th style="text-align:left;">Key Assumptions</th></tr></thead><tbody>'

    for m in methods:
        target = f"${m['target_price']:.2f}"
        low = f"${m['low_estimate']:.2f}"
        high = f"${m['high_estimate']:.2f}"
        weight = f"{m['confidence'] * 100:.0f}%"
        parts = []
        for k, v in list(m.get('assumptions', {}).items())[:3]:
            if isinstance(v, float):
                parts.append(f"{k}: {v * 100:.1f}%" if v < 1 else f"{k}: {v:.1f}")
            else:
                parts.append(f"{k}: {v}")
        assumptions_str = "; ".join(parts) if parts else "-"

        html += (f'<tr><td style="font-weight:600; text-align:left;">{m["method"]}</td>'
                 f'<td style="font-weight:600; color:#002855;">{target}</td>'
                 f'<td>{low}</td><td>{high}</td><td>{weight}</td>'
                 f'<td style="font-size:10px; color:#555555; text-align:left;">{assumptions_str}</td></tr>')

    html += '</tbody></table>'

    if synthesis and synthesis.get('target_price'):
        synth_target = synthesis['target_price']
        synth_range = synthesis.get('range', (0, 0))
        upside = synthesis.get('upside', 0)
        upside_color = '#006633' if upside >= 0 else '#cc0000'
        upside_label = 'Upside' if upside >= 0 else 'Downside'

        html += f'''
        <div style="background:#f5f7fa; border-top:2px solid #002855; padding:10px 16px; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px; margin-bottom:12px;">
            <div>
                <p style="color:#555555; font-size:9px; text-transform:uppercase; letter-spacing:0.04em; margin-bottom:2px;">Weighted Target Price</p>
                <p style="color:#002855; font-size:18px; font-weight:700;">${synth_target:.2f}</p>
            </div>
            <div>
                <p style="color:#555555; font-size:9px; text-transform:uppercase; letter-spacing:0.04em; margin-bottom:2px;">Valuation Range</p>
                <p style="color:#1a1a1a; font-size:13px; font-weight:600;">${synth_range[0]:.2f} - ${synth_range[1]:.2f}</p>
            </div>
            <div>
                <p style="color:#555555; font-size:9px; text-transform:uppercase; letter-spacing:0.04em; margin-bottom:2px;">Implied {upside_label}</p>
                <p style="color:{upside_color}; font-size:13px; font-weight:700;">{abs(upside):.1f}%</p>
            </div>
        </div>'''

    return html


def format_sensitivity_analysis_html(sensitivity_data):
    """Format sensitivity analysis data to HTML"""
    if not sensitivity_data:
        return "<p class='text-gray-500 italic'>Sensitivity analysis not available.</p>"
    
    html = ""
    if 'summary' in sensitivity_data:
        html += f"<div class='mb-4 p-3' style='background:#f5f7fa;'>{_markdown_to_html(sensitivity_data['summary'])}</div>"
    
    if 'confidence_intervals' in sensitivity_data:
        html += "<div class='mb-3'><strong>Confidence Intervals:</strong><ul class='list-disc ml-4 mt-1'>"
        for metric, ci in sensitivity_data['confidence_intervals'].items():
            if ci and isinstance(ci, dict):
                # Support both 'low'/'high' and 'lower'/'upper' formats
                low_val = ci.get('low') or ci.get('lower', 'N/A')
                high_val = ci.get('high') or ci.get('upper', 'N/A')
                # Format large numbers
                if isinstance(low_val, (int, float)):
                    low_val = f"${low_val/1e9:.1f}B" if low_val > 1e9 else f"${low_val/1e6:.1f}M"
                if isinstance(high_val, (int, float)):
                    high_val = f"${high_val/1e9:.1f}B" if high_val > 1e9 else f"${high_val/1e6:.1f}M"
                html += f"<li>{metric}: {low_val} - {high_val} (95% CI)</li>"
        html += "</ul></div>"
    
    return html if html else "<p class='text-gray-500 italic'>Sensitivity analysis not available.</p>"


def format_catalyst_analysis_html(catalyst_data):
    """Format catalyst analysis data to HTML"""
    if not catalyst_data:
        return "<p class='text-gray-500 italic'>Catalyst analysis not available.</p>"
    
    html = ""
    if 'summary' in catalyst_data:
        html += f"<div class='mb-4 p-3' style='background:#f5f7fa;'>{_markdown_to_html(catalyst_data['summary'])}</div>"
    
    if 'top_catalysts' in catalyst_data and catalyst_data['top_catalysts']:
        html += "<div class='mb-3'><strong>Top Catalysts:</strong><ul class='mt-2 space-y-2'>"
        for cat in catalyst_data['top_catalysts'][:5]:
            sentiment_class = 'catalyst-positive' if cat.get('sentiment', '') == 'positive' else ('catalyst-negative' if cat.get('sentiment', '') == 'negative' else 'catalyst-neutral')
            # Support both old format (event_type/description) and new format (type/catalyst)
            event_type = cat.get('event_type') or cat.get('type', 'Event')
            description = cat.get('description') or cat.get('catalyst', 'N/A')
            html += f"<li class='p-2 border-l-2 border-gray-300'><span class='{sentiment_class}'>{event_type}</span>: {description}</li>"
        html += "</ul></div>"
    
    return html if html else "<p class='text-gray-500 italic'>Catalyst analysis not available.</p>"


def format_enhanced_news_html(news_data):
    """Format enhanced news data to HTML"""
    if not news_data:
        return "<p class='text-gray-500 italic'>Enhanced news analysis not available.</p>"
    
    html = ""
    if 'summary' in news_data:
        html += f"<div class='mb-4 p-3' style='background:#f5f7fa;'>{_markdown_to_html(news_data['summary'])}</div>"
    
    if 'sentiment_summary' in news_data:
        sentiment = news_data['sentiment_summary']
        if isinstance(sentiment, dict):
            overall = sentiment.get('overall', 'Neutral')
            sentiment_class = 'catalyst-positive' if overall == 'positive' else ('catalyst-negative' if overall == 'negative' else 'catalyst-neutral')
            html += f"<div class='mb-3'><strong>Overall Sentiment:</strong> <span class='{sentiment_class}'>{overall}</span></div>"
    
    if 'categories' in news_data:
        categories = news_data['categories']
        if isinstance(categories, dict):
            html += "<div class='mb-3'><strong>News by Category:</strong><ul class='list-disc ml-4 mt-1'>"
            for cat, count in categories.items():
                html += f"<li>{cat}: {count} articles</li>"
            html += "</ul></div>"
    
    # Also support 'articles' format - show article count by category
    if 'articles' in news_data and not html:
        articles = news_data['articles']
        if isinstance(articles, list) and len(articles) > 0:
            # Count articles by category
            category_counts = {}
            for article in articles:
                if isinstance(article, dict):
                    cat = article.get('category', 'general')
                    category_counts[cat] = category_counts.get(cat, 0) + 1
            
            html += f"<div class='mb-3'><strong>Total Articles:</strong> {len(articles)}</div>"
            html += "<div class='mb-3'><strong>News by Category:</strong><ul class='list-disc ml-4 mt-1'>"
            for cat, count in sorted(category_counts.items(), key=lambda x: -x[1]):
                html += f"<li>{cat}: {count} articles</li>"
            html += "</ul></div>"
    
    return html if html else "<p class='text-gray-500 italic'>Enhanced news analysis not available.</p>"


def format_enhanced_charts_html(charts_data, report_data=None):
    """Format enhanced charts data to HTML"""
    html = ""
    if not charts_data:
        charts_data = {}
    chart_titles = {
        'eps_pe': 'EPS × PE Trend',
        'revenue_yoy': 'Revenue YoY Growth',
        'ebitda_margin': 'EBITDA Margin Trend',
        'gross_margin': 'Gross Margin Trend',
        'sga_ratio': 'SG&A Ratio',
        'stock_price': 'Stock Price',
        'financial_radar': 'Financial Radar',
        'technical_indicators': 'Technical Indicators',
        'sensitivity_heatmap': 'Sensitivity Heatmap',
        'valuation_waterfall': 'Valuation Waterfall',
        'cash_flow': 'Cash Flow'
    }
    
    for chart_name, chart_paths in charts_data.items():
        if not chart_paths:
            continue
        
        # Handle different data formats
        png_path = None
        if isinstance(chart_paths, dict):
            png_path = chart_paths.get('png')
        elif isinstance(chart_paths, str):
            # chart_paths is directly a path string
            if chart_paths.endswith('.png'):
                png_path = chart_paths
        
        if png_path:
            title = chart_titles.get(chart_name, chart_name.replace('_', ' ').title())
            html += f"""
            <div style='padding: 6px;'>
                <h4 style='font-size: 10px; font-weight: 600; color: #555555; text-transform: uppercase; letter-spacing: 0.03em; margin-bottom: 6px;'>{title}</h4>
                <img src='{png_path}' alt='{title}' class='w-full'/>
            </div>
            """
    
    if html:
        return html

    # Fallback: 文字版技术分析 — 使用真实指标数据
    ti = (report_data or {}).get('technical_indicators', {})
    card_style = 'background:#f5f7fa; padding:8px; border-left:2px solid #002855; margin-bottom:6px;'

    def _sig_label(sig):
        if not sig or sig == 'N/A':
            return ''
        colors = {'Bullish': '#006633', 'Neutral-Bullish': '#006633',
                  'Bearish': '#cc0000', 'Neutral-Bearish': '#cc0000',
                  'Overbought': '#cc0000', 'Oversold': '#006633',
                  'High Activity': '#002855', 'Low Activity': '#8B6914'}
        c = colors.get(sig, '#555555')
        return f' <span style="color:{c}; font-weight:600; font-size:10px;">[{sig}]</span>'

    overall = ti.get('overall_signal', 'N/A')
    overall_color = '#006633' if overall == 'Bullish' else ('#cc0000' if overall == 'Bearish' else '#555555')

    fallback = '<div style="margin-bottom:8px;">'
    fallback += '<h4 style="font-size:11px; font-weight:600; color:#002855; margin-bottom:4px;">Technical Analysis Overview</h4>'
    if overall and overall != 'N/A':
        fallback += f'<p style="font-size:10px; margin-bottom:6px;">Overall Signal: <strong style="color:{overall_color};">{overall}</strong></p>'

    sma50 = ti.get('sma50')
    sma200 = ti.get('sma200')
    ma_val = f'SMA 50: ${sma50:.2f}' if sma50 else ''
    if sma200:
        ma_val += f' | SMA 200: ${sma200:.2f}'
    ma_val = ma_val or 'Data not available'
    fallback += f'<div style="{card_style}"><strong style="font-size:10px; color:#002855;">Moving Averages{_sig_label(ti.get("ma_signal"))}</strong><p style="font-size:10px; color:#555555; margin:2px 0 0 0;">{ma_val}</p></div>'

    rsi = ti.get('rsi14')
    rsi_val = f'RSI (14): {rsi:.1f}' if rsi else 'Data not available'
    fallback += f'<div style="{card_style}"><strong style="font-size:10px; color:#002855;">RSI{_sig_label(ti.get("rsi_signal"))}</strong><p style="font-size:10px; color:#555555; margin:2px 0 0 0;">{rsi_val}</p></div>'

    macd = ti.get('macd')
    if macd is not None:
        macd_val = f'MACD: {macd:.2f} | Signal: {ti.get("macd_signal", 0):.2f} | Histogram: {ti.get("macd_histogram", 0):.2f}'
    else:
        macd_val = 'Data not available'
    fallback += f'<div style="{card_style}"><strong style="font-size:10px; color:#002855;">MACD{_sig_label(ti.get("macd_signal_label"))}</strong><p style="font-size:10px; color:#555555; margin:2px 0 0 0;">{macd_val}</p></div>'

    avg_vol = ti.get('avg_volume_20d')
    latest_vol = ti.get('latest_volume')
    if avg_vol and latest_vol:
        vol_ratio = latest_vol / avg_vol if avg_vol > 0 else 0
        vol_val = f'Latest: {latest_vol/1e6:.1f}M | 20d Avg: {avg_vol/1e6:.1f}M | Ratio: {vol_ratio:.2f}x'
    else:
        vol_val = 'Data not available'
    fallback += f'<div style="{card_style}"><strong style="font-size:10px; color:#002855;">Volume{_sig_label(ti.get("volume_signal"))}</strong><p style="font-size:10px; color:#555555; margin:2px 0 0 0;">{vol_val}</p></div>'

    fallback += '</div>'
    return fallback


def format_analyst_contacts(names, emails):
    html = []
    max_analysts = max(len(names) if names else 0, len(emails) if emails else 0)
    for i in range(max_analysts):
        name = names[i] if names and i < len(names) else "N/A"
        email = emails[i] if emails and i < len(emails) else "N/A"
        html.append(f'<p class="text-gray-500">{name} | {email}</p>')
    return "\n".join(html)

def render_html_report(template_str: str, data: dict) -> str:
    """Renders an HTML report from a template string and data dictionary."""
    try:
        # Prepare analyst contacts
        if "analyst_names" in data or "analyst_emails" in data:
            data["analyst_contacts_html"] = format_analyst_contacts(data.get("analyst_names"), data.get("analyst_emails"))
        else:
            data["analyst_contacts_html"] = "<p class=\"text-gray-500\">N/A</p>"

        # Derive rating
        data["rating"] = _derive_rating(
            data.get("share_price", "N/A"),
            data.get("target_price", "N/A"),
            data.get("rating", "N/A"))

        # Default missing chart paths to an empty string to avoid KeyErrors
        data.setdefault("revenue_chart_path", "")
        data.setdefault("ev_ebitda_chart_path", "")
        data.setdefault("eps_pe_chart_path", "")
        data.setdefault("financial_summary_table_html", "<p>Financial summary not available.</p>")
        data.setdefault("valuation_metrics_table_html", "<p>Valuation metrics not available.</p>")
        data.setdefault("peer_ebitda_table_html", "<p>Peer EBITDA data not available.</p>")
        data.setdefault("peer_ev_ebitda_table_html", "<p>Peer EV/EBITDA data not available.</p>")
        data.setdefault("credit_cashflow_table_html", "<p>Credit & Cashflow metrics not available.</p>")
        data.setdefault("news_summary", "Recent news coverage not available.")
        
        # Safely format enhanced analysis data for Page 4
        # Wrap each call in try-except to prevent one failure from breaking everything
        try:
            data["sensitivity_analysis_html"] = format_sensitivity_analysis_html(data.get("sensitivity_analysis", {}))
        except Exception as e:
            print(f"Warning: Error formatting sensitivity analysis: {e}")
            data["sensitivity_analysis_html"] = "<p class='text-gray-500 italic'>Sensitivity analysis not available.</p>"
        
        try:
            data["catalyst_analysis_html"] = format_catalyst_analysis_html(data.get("catalyst_analysis", {}))
        except Exception as e:
            print(f"Warning: Error formatting catalyst analysis: {e}")
            data["catalyst_analysis_html"] = "<p class='text-gray-500 italic'>Catalyst analysis not available.</p>"
        
        try:
            data["enhanced_news_html"] = format_enhanced_news_html(data.get("enhanced_news", {}))
        except Exception as e:
            print(f"Warning: Error formatting enhanced news: {e}")
            data["enhanced_news_html"] = "<p class='text-gray-500 italic'>Enhanced news analysis not available.</p>"
        
        try:
            data["enhanced_charts_html"] = format_enhanced_charts_html(data.get("enhanced_charts", {}), data)
        except Exception as e:
            print(f"Warning: Error formatting enhanced charts: {e}")
            data["enhanced_charts_html"] = "<p class='text-gray-500 italic'>Enhanced charts not available.</p>"
        
        # Default competitor analysis and takeaways for Page 2 with fallbacks
        if "competitor_analysis" not in data or not data["competitor_analysis"] or (isinstance(data["competitor_analysis"], str) and data["competitor_analysis"].strip() == ""):
            data["competitor_analysis"] = "Comprehensive competitor analysis based on peer financial metrics and industry positioning will be generated using available data."
        
        if "major_takeaways" not in data or not data["major_takeaways"] or (isinstance(data["major_takeaways"], str) and data["major_takeaways"].strip() == ""):
            data["major_takeaways"] = "Revenue Growth: Analysis not available\n\nGross Profit Margin: Analysis not available\n\nSG&A Expense Margin: Analysis not available\n\nEBITDA Margin Stability: Analysis not available"

        return template_str.format(**data)
    except KeyError as e:
        print(f"Error rendering HTML: Missing key {e} in data dictionary.")
        import traceback
        traceback.print_exc()
        return f"<html><body><h1>Error rendering report</h1><p>Missing data: {e}</p></body></html>"
    except Exception as e:
        print(f"An unexpected error occurred during HTML rendering: {e}")
        import traceback
        traceback.print_exc()
        return f"<html><body><h1>Error rendering report</h1><p>Unexpected error: {e}</p></body></html>"

# ============== 合并版 HTML 模板 ==============

HTML_TEMPLATE_COMBINED = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta content="width=device-width, initial-scale=1.0" name="viewport"/>
  <title>US EQUITY RESEARCH - {company_name_ticker}</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&display=swap" rel="stylesheet"/>
  <style>
   body {{ font-family: 'Inter', sans-serif; font-weight: 400; color: #1a1a1a; }}
   h1, h2.serif {{ font-family: 'Georgia', 'Times New Roman', serif; }}
   @media print {{
     .page-break {{ page-break-before: always; }}
     .no-print {{ display: none; }}
   }}
   .page-container {{
     max-width: 8.5in;
     margin: 0 auto;
     padding: 0.5in;
     box-sizing: border-box;
   }}
   .section {{
     margin-bottom: 2rem;
     padding-bottom: 1rem;
     border-bottom: 1px solid #d1d5db;
   }}
   .section:last-child {{
     border-bottom: none;
   }}
   .financial-table tr:not(:last-child) {{ border-bottom: 1px solid #d1d5db; }}
   .financial-table td {{ padding: 5px 0; font-size: 11px; }}
   .data-source {{ border-bottom: 1px dotted #666; cursor: help; }}
   .ai-generated {{ position: relative; border-left: 2px solid #8B6914; padding-left: 8px; margin: 8px 0; }}
   .ai-badge {{ display: inline-block; background: #8B6914; color: white; font-size: 8px; padding: 1px 4px; border-radius: 2px; margin-left: 4px; }}
   .executive-summary {{ background: #f5f7fa; padding: 12px; margin-bottom: 16px; border-top: 2px solid #002855; }}
   .executive-summary h3 {{ color: #002855; margin-bottom: 8px; }}
   .section-summary {{ background: #f5f7fa; padding: 8px; border-left: 3px solid #002855; margin-top: 8px; font-style: italic; }}
   .catalyst-positive {{ color: #006633; background: #E8F5E9; padding: 2px 6px; display: inline-block; }}
   .catalyst-negative {{ color: #cc0000; background: #FFEBEE; padding: 2px 6px; display: inline-block; }}
   .catalyst-neutral {{ color: #555555; background: #F5F5F5; padding: 2px 6px; display: inline-block; }}
   .section-label {{
     font-size: 13px;
     font-weight: 600;
     color: #002855;
     text-transform: uppercase;
     letter-spacing: 0.04em;
     margin-bottom: 6px;
     padding-bottom: 4px;
     border-bottom: 1px solid #d1d5db;
   }}
   .nav-bar {{
     position: sticky;
     top: 0;
     background: white;
     z-index: 100;
     padding: 10px 0;
     border-bottom: 2px solid #002855;
     margin-bottom: 20px;
   }}
   .nav-bar a {{
     color: #002855;
     text-decoration: none;
     margin-right: 20px;
     font-size: 11px;
     font-weight: 500;
     text-transform: uppercase;
     letter-spacing: 0.03em;
   }}
   .nav-bar a:hover {{
     color: #8B6914;
     text-decoration: underline;
   }}
   table {{ width: 100%; border-collapse: collapse; font-size: 11px; }}
   table th {{ background: #002855; color: white; font-weight: 500; text-align: right; padding: 5px 6px; font-size: 10px; text-transform: uppercase; letter-spacing: 0.03em; }}
   table th:first-child {{ text-align: left; }}
   table td {{ padding: 4px 6px; text-align: right; border-bottom: 1px solid #d1d5db; }}
   table td:first-child {{ text-align: left; font-weight: 500; }}
   table tr:nth-child(even) {{ background: #f5f7fa; }}
  </style>
</head>
<body class="bg-white text-xs">
  <div class="page-container mx-auto">
    <!-- Navigation Bar -->
    <nav class="nav-bar no-print">
      <a href="#overview">Overview</a>
      <a href="#financials">Financials</a>
      <a href="#competitor">Competitor</a>
      <a href="#sensitivity">Sensitivity</a>
      <a href="#news">News</a>
    </nav>

    <!-- Header -->
    <header class="mb-6">
      <div class="flex justify-between items-center mb-2">
        <div></div>
        <p style="color: #555555; font-size: 11px;">{research_source}</p>
      </div>
      <div style="background: #002855;" class="text-white px-3 py-1 w-full">
        <h1 class="text-2xl font-normal" style="font-family: 'Georgia', 'Times New Roman', serif; letter-spacing: 0.03em;">US EQUITY RESEARCH</h1>
      </div>
      <div style="height: 2px; background: #8B6914; width: 100%;"></div>
      <p style="color: #555555; font-size: 11px;" class="text-right mt-1">{report_date}</p>
    </header>

    <!-- Section 1: Company Overview -->
    <section id="overview" class="section">
      <div class="flex justify-between mb-6">
        <div>
          <h2 class="text-[20px] mb-2" style="font-family: 'Georgia', 'Times New Roman', serif; color: #002855; font-weight: 600;">{company_name_full}</h2>
          <p style="color: #333333; font-size: 13px; line-height: 1.5;">{tagline}</p>
        </div>
        <div>
          <p style="color: #002855; font-size: 13px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em;">Analysts</p>
          {analyst_contacts_html}
        </div>
      </div>
      <div class="flex gap-6">
        <div class="w-2/3">
          <h3 class="section-label">Company Overview</h3>
          <div class="mb-4 text-xs leading-tight" style="color: #1a1a1a;">{company_overview}</div>
          <h3 class="section-label">Investment Update</h3>
          <div class="mb-4 text-xs leading-tight" style="color: #1a1a1a;">{investment_overview}</div>
          <h3 class="section-label">Recent News Summary</h3>
          <div class="mb-4 text-xs leading-tight" style="color: #1a1a1a;">{news_summary}</div>
          <h3 class="section-label">Valuation</h3>
          <div class="mb-4 text-xs leading-tight" style="color: #1a1a1a;">{valuation_overview}</div>
          {valuation_breakdown_html}
          <h3 class="section-label">Risks</h3>
          <div class="text-xs leading-tight" style="color: #1a1a1a;">{risks}</div>
        </div>
        <div class="w-1/3">
          <h3 class="section-label">Key Financial Data</h3>
          <div style="background: #f5f7fa; border-top: 2px solid #002855;" class="p-3 mb-4">
            <table class="w-full text-xs financial-table">
              <tr><td style="color: #555555;">Bloomberg Ticker</td><td class="text-right" style="color: #1a1a1a; font-weight: 500;">{company_ticker} US</td></tr>
              <tr><td style="color: #555555;">Sector</td><td class="text-right" style="color: #1a1a1a; font-weight: 500;">{sector}</td></tr>
              <tr><td style="color: #555555;">Share Price (USD)</td><td class="text-right" style="color: #1a1a1a; font-weight: 500;">{share_price}</td></tr>
              <tr><td style="color: #555555;">Rating</td><td class="text-right" style="color: #1a1a1a; font-weight: 600;">{rating}</td></tr>
              <tr><td style="color: #555555;">12-mth Target Price (USD)</td><td class="text-right" style="color: #1a1a1a; font-weight: 500;">{target_price}</td></tr>
              <tr><td style="color: #555555;">Market Cap (USDb)</td><td class="text-right" style="color: #1a1a1a; font-weight: 500;">{market_cap}</td></tr>
              <tr><td style="color: #555555;">52-Week Range</td><td class="text-right" style="color: #1a1a1a; font-weight: 500;">{week_52_range}</td></tr>
              <tr><td style="color: #555555;">Volume (m shares)</td><td class="text-right" style="color: #1a1a1a; font-weight: 500;">{volume}</td></tr>
              <tr><td style="color: #555555;">Free float (%)</td><td class="text-right" style="color: #1a1a1a; font-weight: 500;">{free_float}</td></tr>
              <tr><td style="color: #555555;">Dividend yield (%)</td><td class="text-right" style="color: #1a1a1a; font-weight: 500;">{dividend_yield}</td></tr>
              <tr><td style="color: #555555;">Net Debt to Equity (%)</td><td class="text-right" style="color: #1a1a1a; font-weight: 500;">{net_debt_to_equity}</td></tr>
              <tr><td style="color: #555555;">Fwd. P/E (x)</td><td class="text-right" style="color: #1a1a1a; font-weight: 500;">{fwd_pe}</td></tr>
              <tr><td style="color: #555555;">P/Book (x)</td><td class="text-right" style="color: #1a1a1a; font-weight: 500;">{pb_ratio}</td></tr>
              <tr><td style="color: #555555;">ROE (%)</td><td class="text-right" style="color: #1a1a1a; font-weight: 500;">{roe}</td></tr>
            </table>
          </div>
          <p style="font-size: 10px; color: #555555; font-style: italic;" class="mb-2">Closing Price as of {closing_price_date}</p>
          <p style="font-size: 10px; color: #888888;">Source: {data_source_text}</p>
        </div>
      </div>
    </section>

    <!-- Section 2: Competitor Analysis -->
    <section id="competitor" class="section page-break">
      <h2 class="section-label mb-3">Competitor Analysis</h2>

      <h3 style="font-size:11px; font-weight:600; color:#002855; text-transform:uppercase; letter-spacing:0.03em; margin-bottom:8px;">Peer EBITDA Comparison</h3>
      {peer_ebitda_table_html}
      <h3 style="font-size:11px; font-weight:600; color:#002855; text-transform:uppercase; letter-spacing:0.03em; margin:12px 0 8px 0;">Peer EV/EBITDA Comparison</h3>
      {peer_ev_ebitda_table_html_comp}

      <div class="text-xs leading-tight mb-4" style="color: #1a1a1a; margin-top:12px;">{competitor_analysis}</div>

      <div style="background: #f5f7fa; border-top: 2px solid #002855; padding: 12px 16px;" class="mb-6">
        <h3 style="font-weight: 600; font-size: 11px; color: #002855; text-transform: uppercase; letter-spacing: 0.03em;" class="mb-3">Major takeaways from {company_ticker} and peers:</h3>
        <div class="text-xs leading-tight whitespace-pre-line" style="color: #1a1a1a;">{major_takeaways}</div>
      </div>

      <h2 class="section-label mb-3">Financial Metrics and Peer Comparison Charts</h2>
      <div class="grid grid-cols-3 gap-3">
        <div>
          <h3 style="font-size: 10px; color: #555555; text-transform: uppercase; letter-spacing: 0.03em; font-weight: 600;" class="mb-2">Revenue & EBITDA Trend</h3>
          <img src="{revenue_chart_path}" alt="Revenue and EBITDA Trend" class="w-full"/>
        </div>
        <div>
          <h3 style="font-size: 10px; color: #555555; text-transform: uppercase; letter-spacing: 0.03em; font-weight: 600;" class="mb-2">EPS x PE Trend Analysis</h3>
          <img src="{eps_pe_chart_path}" alt="EPS x PE Trend Analysis" class="w-full"/>
        </div>
        <div>
          <h3 style="font-size: 10px; color: #555555; text-transform: uppercase; letter-spacing: 0.03em; font-weight: 600;" class="mb-2">EV/EBITDA Peer Comparison</h3>
          <img src="{ev_ebitda_chart_path}" alt="EV/EBITDA Peer Comparison" class="w-full"/>
        </div>
      </div>
    </section>

    <!-- Section 3: Financial Summary -->
    <section id="financials" class="section page-break">
      <h2 class="section-label mb-3">Financial Summary (USD, unless otherwise stated)</h2>
      {financial_summary_table_html}

      <h2 class="section-label mb-3 mt-6">Credit & Cashflow Metrics</h2>
      {credit_cashflow_table_html}

      <h2 class="section-label mb-3 mt-6">Peer Valuation Metrics (EV/EBITDA, x)</h2>
      {peer_ev_ebitda_table_html}
    </section>

    <!-- Section 4: Sensitivity & Catalyst Analysis -->
    <section id="sensitivity" class="section page-break">
      <div style="background: #002855;" class="text-white px-3 py-1 w-full mb-4">
        <h1 class="text-xl font-normal" style="font-family: 'Georgia', 'Times New Roman', serif; letter-spacing: 0.03em;">SENSITIVITY & CATALYST ANALYSIS</h1>
      </div>
      <div class="mb-6">
        <h2 class="section-label mb-3">Sensitivity Analysis</h2>
        <div class="text-xs leading-tight">{sensitivity_analysis_html}</div>
      </div>
      <div class="mb-6">
        <h2 class="section-label mb-3">Key Catalysts</h2>
        <div class="text-xs leading-tight">{catalyst_analysis_html}</div>
      </div>
    </section>

    <!-- Section 5: News & Enhanced Charts -->
    <section id="news" class="section page-break">
      <div style="background: #002855;" class="text-white px-3 py-1 w-full mb-4">
        <h1 class="text-xl font-normal" style="font-family: 'Georgia', 'Times New Roman', serif; letter-spacing: 0.03em;">NEWS & ENHANCED CHARTS</h1>
      </div>
      <div class="mb-6">
        <h2 class="section-label mb-3">News Impact Analysis</h2>
        <div class="text-xs leading-tight">{enhanced_news_html}</div>
      </div>
      <div class="mb-6">
        <h2 class="section-label mb-3">Enhanced Charts</h2>
        <div class="grid grid-cols-2 gap-3">{enhanced_charts_html}</div>
      </div>
    </section>

    <!-- Footer -->
    <footer class="pt-4" style="border-top: 1px solid #002855;">
      <p style="font-size: 9px; color: #555555; line-height: 1.4;">{disclaimer_text}</p>
      <div class="text-right">
        <img alt="AI4Finance Logo" class="inline-block" height="60" src="https://github.com/AI4Finance-Foundation/FinGPT/assets/31713746/e0371951-1ce1-488e-aa25-0992dafcc139" width="100"/>
      </div>
    </footer>
  </div>
</body>
</html>
"""


def render_combined_html_report(data: dict) -> str:
    """
    Renders a combined HTML report with all sections in a single file.
    """
    try:
        # Prepare analyst contacts
        if "analyst_names" in data or "analyst_emails" in data:
            data["analyst_contacts_html"] = format_analyst_contacts(data.get("analyst_names"), data.get("analyst_emails"))
        else:
            data["analyst_contacts_html"] = "<p class=\"text-gray-500\">N/A</p>"
        
        # Derive rating from price comparison
        data["rating"] = _derive_rating(
            data.get("share_price", "N/A"),
            data.get("target_price", "N/A"),
            data.get("rating", "N/A"))

        # 52w_range
        data.setdefault("week_52_range", data.get("52w_range", "N/A"))

        # Default missing chart paths
        data.setdefault("revenue_chart_path", "")
        data.setdefault("ev_ebitda_chart_path", "")
        data.setdefault("eps_pe_chart_path", "")
        data.setdefault("financial_summary_table_html", "<p>Financial summary not available.</p>")
        data.setdefault("valuation_metrics_table_html", "<p>Valuation metrics not available.</p>")
        data.setdefault("peer_ebitda_table_html", "<p>Peer EBITDA data not available.</p>")
        data.setdefault("peer_ev_ebitda_table_html", "<p>Peer EV/EBITDA data not available.</p>")
        data.setdefault("peer_ev_ebitda_table_html_comp", data.get("peer_ev_ebitda_table_html", "<p>Peer EV/EBITDA data not available.</p>"))
        data.setdefault("credit_cashflow_table_html", "<p>Credit & Cashflow metrics not available.</p>")
        data.setdefault("news_summary", "Recent news coverage not available.")

        # Convert text fields to HTML with auto-bold
        for key in ['company_overview', 'investment_overview', 'valuation_overview',
                     'news_summary', 'risks', 'competitor_analysis']:
            if key in data and isinstance(data[key], str):
                data[key] = _markdown_to_html(data[key])

        # Valuation breakdown
        try:
            data["valuation_breakdown_html"] = format_valuation_breakdown_html(data.get("valuation_analysis", {}))
        except Exception as e:
            print(f"Warning: Error formatting valuation breakdown: {e}")
            data["valuation_breakdown_html"] = ""

        # Format enhanced analysis data
        try:
            data["sensitivity_analysis_html"] = format_sensitivity_analysis_html(data.get("sensitivity_analysis", {}))
        except Exception as e:
            print(f"Warning: Error formatting sensitivity analysis: {e}")
            data["sensitivity_analysis_html"] = "<p class='text-gray-500 italic'>Sensitivity analysis not available.</p>"

        try:
            data["catalyst_analysis_html"] = format_catalyst_analysis_html(data.get("catalyst_analysis", {}))
        except Exception as e:
            print(f"Warning: Error formatting catalyst analysis: {e}")
            data["catalyst_analysis_html"] = "<p class='text-gray-500 italic'>Catalyst analysis not available.</p>"

        try:
            data["enhanced_news_html"] = format_enhanced_news_html(data.get("enhanced_news", {}))
        except Exception as e:
            print(f"Warning: Error formatting enhanced news: {e}")
            data["enhanced_news_html"] = "<p class='text-gray-500 italic'>Enhanced news analysis not available.</p>"

        try:
            data["enhanced_charts_html"] = format_enhanced_charts_html(data.get("enhanced_charts", {}), data)
        except Exception as e:
            print(f"Warning: Error formatting enhanced charts: {e}")
            data["enhanced_charts_html"] = "<p class='text-gray-500 italic'>Enhanced charts not available.</p>"

        # Default competitor analysis and takeaways
        if "competitor_analysis" not in data or not data["competitor_analysis"]:
            data["competitor_analysis"] = _markdown_to_html("Comprehensive competitor analysis based on peer financial metrics and industry positioning will be generated using available data.")

        if "major_takeaways" not in data or not data["major_takeaways"]:
            data["major_takeaways"] = "Revenue Growth: Analysis not available\n\nGross Profit Margin: Analysis not available\n\nSG&A Expense Margin: Analysis not available\n\nEBITDA Margin Stability: Analysis not available"

        return HTML_TEMPLATE_COMBINED.format(**data)
    
    except KeyError as e:
        print(f"Error rendering combined HTML: Missing key {e} in data dictionary.")
        import traceback
        traceback.print_exc()
        return f"<html><body><h1>Error rendering report</h1><p>Missing data: {e}</p></body></html>"
    except Exception as e:
        print(f"An unexpected error occurred during combined HTML rendering: {e}")
        import traceback
        traceback.print_exc()
        return f"<html><body><h1>Error rendering report</h1><p>Unexpected error: {e}</p></body></html>"