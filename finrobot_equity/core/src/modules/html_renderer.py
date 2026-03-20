#!/usr/bin/env python
# coding: utf-8

import os
import pandas as pd

HTML_TEMPLATE_PAGE_1 = """
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta content="width=device-width, initial-scale=1.0" name="viewport"/>
  <title>
   US EQUITY RESEARCH - {company_name_ticker}
  </title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@300&amp;display=swap" rel="stylesheet"/>
  <style>
   body {{ font-family: 'DM Sans', sans-serif; font-weight: 300; }}
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
   .financial-table tr:not(:last-child) {{ border-bottom: 1px solid #e5e7eb; }}
   .financial-table td {{ padding: 4px 0; }}
   /* 数据来源标注样式 */
   .data-source {{ border-bottom: 1px dotted #666; cursor: help; }}
   /* AI生成内容标记样式 */
   .ai-generated {{ position: relative; border-left: 2px solid #D2A74A; padding-left: 8px; margin: 8px 0; }}
   .ai-badge {{ display: inline-block; background: #D2A74A; color: white; font-size: 8px; padding: 1px 4px; border-radius: 2px; margin-left: 4px; }}
   /* 执行摘要样式 */
   .executive-summary {{ background: #f8f9fa; padding: 12px; border-radius: 4px; margin-bottom: 16px; }}
   .executive-summary h3 {{ color: #0B1B33; margin-bottom: 8px; }}
   /* 章节小结样式 */
   .section-summary {{ background: #fafafa; padding: 8px; border-left: 3px solid #0B1B33; margin-top: 8px; font-style: italic; }}
   /* 催化剂标签样式 */
   .catalyst-positive {{ color: #4A7C59; }}
   .catalyst-negative {{ color: #8B4513; }}
   .catalyst-neutral {{ color: #666666; }}
  </style>
</head>
<body class="bg-white text-xs">
  <div class="page-container mx-auto">
   <header class="mb-6">
    <div class="flex justify-between items-center mb-2">
     <div></div>
     <p class="text-gray-500 text-[12px]">
      {research_source}
     </p>
    </div>
    <div class="bg-black text-white px-2 py-1 w-full">
     <h1 class="text-2xl font-normal">
      US EQUITY RESEARCH
     </h1>
    </div>
    <p class="text-gray-500 text-[12px] text-right mt-1">
     {report_date}
    </p>
   </header>
   <main>
    <div class="flex justify-between mb-6">
     <div>
      <h2 class="text-[20px] text-gray-400 mb-3">
       {company_name_full}
      </h2>
      <p class="text-gray-600 text-[14px] leading-tight">
       {tagline}
      </p>
     </div>
     <div>
      <p class="text-gray-400 text-[14px]">
       Analysts
      </p>
      {analyst_contacts_html}
     </div>
    </div>
    <div class="flex gap-6">
     <div class="w-2/3">
      <h3 class="font-normal mb-2 text-[14px] text-gray-400">
       Company Overview
      </h3>
      <p class="mb-4 text-xs leading-tight">
       {company_overview}
      </p>
      <h3 class="font-normal mb-2 text-[14px] text-gray-400">
       Investment Update
      </h3>
      <p class="mb-4 text-xs leading-tight">
       {investment_overview}
      </p>
      <h3 class="font-normal mb-2 text-[14px] text-gray-400">
       Recent News Summary
      </h3>
      <p class="mb-4 text-xs leading-tight">
       {news_summary}
      </p>
      <h3 class="font-normal mb-2 text-[14px] text-gray-400">
       Valuation
      </h3>
      <p class="mb-4 text-xs leading-tight">
       {valuation_overview}
      </p>
      <h3 class="font-normal mb-2 text-[14px] text-gray-400">
       Risks
      </h3>
      <p class="mb-4 text-xs leading-tight">
       {risks}
      </p>
     </div>
     <div class="w-1/3">
      <h3 class="font-normal mb-2 text-[14px] text-gray-400">
       Key Financial Data
      </h3>
      <div class="bg-gray-100 p-4 mb-4">
       <table class="w-full text-xs financial-table">
        <tr>
          <td class="text-gray-500">Bloomberg Ticker</td>
          <td class="text-black text-right">{company_ticker} US</td>
        </tr>
        <tr>
          <td class="text-gray-500">Sector</td>
          <td class="text-black text-right">{sector}</td>
        </tr>
        <tr>
          <td class="text-gray-500">Share Price (USD)</td>
          <td class="text-black text-right">{share_price}</td>
        </tr>
        <tr>
          <td class="text-gray-500">Rating</td>
          <td class="text-black text-right">{rating}</td>
        </tr>
        <tr>
          <td class="text-gray-500">12-mth Target Price (USD)</td>
          <td class="text-black text-right">{target_price}</td>
        </tr>
        <tr>
          <td class="text-gray-500">Market Cap (USDb)</td>
          <td class="text-black text-right">{market_cap}</td>
        </tr>
        <tr>
          <td class="text-gray-500">Volume (m shares)</td>
          <td class="text-black text-right">{volume}</td>
        </tr>
        <tr>
          <td class="text-gray-500">Free float (%)</td>
          <td class="text-black text-right">{free_float}</td>
        </tr>
        <tr>
          <td class="text-gray-500">Dividend yield (%)</td>
          <td class="text-black text-right">{dividend_yield}</td>
        </tr>
        <tr>
          <td class="text-gray-500">Net Debt to Equity (%)</td>
          <td class="text-black text-right">{net_debt_to_equity}</td>
        </tr>
        <tr>
          <td class="text-gray-500">Fwd. P/E (x)</td>
          <td class="text-black text-right">{fwd_pe}</td>
        </tr>
        <tr>
          <td class="text-gray-500">P/Book (x)</td>
          <td class="text-black text-right">{pb_ratio}</td>
        </tr>
        <tr>
          <td class="text-gray-500">ROE (%)</td>
          <td class="text-black text-right">{roe}</td>
        </tr>
       </table>
      </div>
      <p class="text-[12px] text-gray-500 mb-2 italic">
       Closing Price as of {closing_price_date}
      </p>
      <p class="text-[12px] text-gray-500 mb-4">
       Source: {data_source_text}
      </p>
     </div>
    </div>
   </main>
   <footer class="text-xs text-gray-500 pt-4">
    <p class="mb-2">{disclaimer_text}</p>
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
  <link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@300&display=swap" rel="stylesheet"/>
  <style>
   body {{ font-family: 'DM Sans', sans-serif; font-weight: 300; }}
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
      <div class="flex justify-between items-center mb-2">
        <div><h2 class="text-lg font-normal text-gray-700">{company_name_full} ({company_ticker})</h2></div>
        <p class="text-gray-500 text-[12px]">
          {research_source}
        </p>
      </div>
    </header>
    <main>
      <div class="w-full">
        <div class="mb-6">
          <h2 class="text-gray-500 text-[14px] font-bold mb-3">COMPETITOR ANALYSIS</h2>
          <p class="text-xs leading-tight mb-4">
            {competitor_analysis}
          </p>
          
          <div class="border border-gray-300 p-4 mb-6">
            <h3 class="font-bold text-xs mb-3">Major takeaways from {company_ticker} and peers:</h3>
            <div class="text-xs leading-tight whitespace-pre-line">
              {major_takeaways}
            </div>
          </div>
        </div>
        
        <div class="mb-4">
          <h2 class="text-gray-500 text-[14px] font-bold mb-3">FINANCIAL METRICS AND PEER COMPARISON CHARTS</h2>
          <div class="grid grid-cols-3 gap-3">
              <div>
                  <h3 class="font-normal mb-2 text-[12px] text-gray-500">Revenue & EBITDA Trend</h3>
                  <img src="{revenue_chart_path}" alt="Revenue and EBITDA Trend" class="w-full border"/>
              </div>
              <div>
                  <h3 class="font-normal mb-2 text-[12px] text-gray-500">EPS × PE Trend Analysis</h3>
                  <img src="{eps_pe_chart_path}" alt="EPS × PE Trend Analysis" class="w-full border"/>
              </div>
              <div>
                  <h3 class="font-normal mb-2 text-[12px] text-gray-500">EV/EBITDA Peer Comparison</h3>
                  <img src="{ev_ebitda_chart_path}" alt="EV/EBITDA Peer Comparison" class="w-full border"/>
              </div>
          </div>
        </div>
      </div>
    </main>
    <footer class="text-xs text-gray-500 pt-4">
      <p class="mb-2">{disclaimer_text}</p>
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
  <link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@300&display=swap" rel="stylesheet"/>
  <style>
   body {{ font-family: 'DM Sans', sans-serif; font-weight: 300; }}
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
      <div class="flex justify-between items-center mb-2">
        <div><h2 class="text-lg font-normal text-gray-700">{company_name_full} ({company_ticker})</h2></div>
        <p class="text-gray-500 text-[12px]">
          {research_source}
        </p>
      </div>
    </header>
    <main>
      <div class="w-full">
        <div class="mb-6">
          <h2 class="text-gray-500 text-[14px] font-bold mb-3">FINANCIAL SUMMARY (USD, unless otherwise stated)</h2>
          {financial_summary_table_html}
        </div>

        <div class="mb-4">
          <h2 class="text-gray-500 text-[14px] font-bold mb-3">CREDIT & CASHFLOW METRICS </h2>
          {credit_cashflow_table_html}
        </div>
        
        <div class="mb-4">
          <h2 class="text-gray-500 text-[14px] font-bold mb-3">PEER VALUATION METRICS (EV/EBITDA, x)</h2>
          {peer_ev_ebitda_table_html}
        </div>
        
        
      </div>
    </main>
    <footer class="text-xs text-gray-500 pt-4">
      <p class="mb-2">{disclaimer_text}</p>
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
    """Converts a pandas DataFrame to an HTML table with Tailwind CSS classes."""
    if df is None or df.empty:
        return "<p>No data available.</p>"
    
    html = f"<table id='{table_id}' class='w-full text-xs table-auto'>\n"
    html += "  <thead>\n    <tr class='border-b-2 border-black'>\n"
    
    index_header = df.index.name if df.index.name else ""
    html += f"      <th class='text-left {header_class} p-2'>{index_header}</th>\n"
    
    for col_name in df.columns:
        html += f"      <th class='text-right {header_class} p-2'>{col_name}</th>\n"
    html += "    </tr>\n  </thead>\n"
    html += "  <tbody>\n"
    for i, (index_val, row) in enumerate(df.iterrows()):
        row_class = row_class_cycle[i % len(row_class_cycle)]
        html += f"    <tr class='{row_class} border-b border-gray-200'>\n"
        html += f"      <td class='text-left p-2 font-semibold'>{index_val}</td>\n"
        for val in row:
            formatted_val = _format_value(val)
            html += f"      <td class='text-right p-2'>{formatted_val}</td>\n"
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
  <link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@300&display=swap" rel="stylesheet"/>
  <style>
   body {{ font-family: 'DM Sans', sans-serif; font-weight: 300; }}
   @page {{ size: 8.5in 11in; margin: 0; }}
   .page-container {{ width: 8.5in; height: 11in; padding: 0.5in; box-sizing: border-box; display: flex; flex-direction: column; }}
   .catalyst-positive {{ color: #4A7C59; background: #E8F5E9; padding: 2px 6px; border-radius: 4px; display: inline-block; }}
   .catalyst-negative {{ color: #8B4513; background: #FFEBEE; padding: 2px 6px; border-radius: 4px; display: inline-block; }}
   .catalyst-neutral {{ color: #666666; background: #F5F5F5; padding: 2px 6px; border-radius: 4px; display: inline-block; }}
  </style>
</head>
<body class="bg-white text-xs">
  <div class="page-container mx-auto">
    <header>
      <div class="flex justify-between items-center mb-2">
        <div><h2 class="text-lg font-normal text-gray-700">{company_name_full} ({company_ticker})</h2></div>
        <p class="text-gray-500 text-[12px]">{research_source}</p>
      </div>
      <div class="bg-black text-white px-2 py-1 w-full mb-4">
        <h1 class="text-xl font-normal">SENSITIVITY & CATALYST ANALYSIS</h1>
      </div>
    </header>
    <main class="flex-grow">
      <div class="mb-6">
        <h2 class="text-gray-500 text-[14px] font-bold mb-3 border-b border-gray-300 pb-1">SENSITIVITY ANALYSIS</h2>
        <div class="text-xs leading-tight">{sensitivity_analysis_html}</div>
      </div>
      <div class="mb-6">
        <h2 class="text-gray-500 text-[14px] font-bold mb-3 border-b border-gray-300 pb-1">KEY CATALYSTS</h2>
        <div class="text-xs leading-tight">{catalyst_analysis_html}</div>
      </div>
    </main>
    <footer class="text-xs text-gray-500 pt-4 mt-auto">
      <p class="mb-2">{disclaimer_text}</p>
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
  <link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@300&display=swap" rel="stylesheet"/>
  <style>
   body {{ font-family: 'DM Sans', sans-serif; font-weight: 300; }}
   @page {{ size: 8.5in 11in; margin: 0; }}
   .page-container {{ width: 8.5in; height: 11in; padding: 0.5in; box-sizing: border-box; display: flex; flex-direction: column; }}
  </style>
</head>
<body class="bg-white text-xs">
  <div class="page-container mx-auto">
    <header>
      <div class="flex justify-between items-center mb-2">
        <div><h2 class="text-lg font-normal text-gray-700">{company_name_full} ({company_ticker})</h2></div>
        <p class="text-gray-500 text-[12px]">{research_source}</p>
      </div>
      <div class="bg-black text-white px-2 py-1 w-full mb-4">
        <h1 class="text-xl font-normal">NEWS & ENHANCED CHARTS</h1>
      </div>
    </header>
    <main class="flex-grow">
      <div class="mb-6">
        <h2 class="text-gray-500 text-[14px] font-bold mb-3 border-b border-gray-300 pb-1">NEWS IMPACT ANALYSIS</h2>
        <div class="text-xs leading-tight">{enhanced_news_html}</div>
      </div>
      <div class="mb-6">
        <h2 class="text-gray-500 text-[14px] font-bold mb-3 border-b border-gray-300 pb-1">ENHANCED CHARTS</h2>
        <div class="grid grid-cols-2 gap-3">{enhanced_charts_html}</div>
      </div>
    </main>
    <footer class="text-xs text-gray-500 pt-4 mt-auto">
      <p class="mb-2">{disclaimer_text}</p>
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


def format_sensitivity_analysis_html(sensitivity_data):
    """Format sensitivity analysis data to HTML"""
    if not sensitivity_data:
        return "<p class='text-gray-500 italic'>Sensitivity analysis not available.</p>"
    
    html = ""
    if 'summary' in sensitivity_data:
        html += f"<div class='mb-4 p-3 bg-gray-50 rounded'>{sensitivity_data['summary']}</div>"
    
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
        html += f"<div class='mb-4 p-3 bg-gray-50 rounded'>{catalyst_data['summary']}</div>"
    
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
        html += f"<div class='mb-4 p-3 bg-gray-50 rounded'>{news_data['summary']}</div>"
    
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


def format_enhanced_charts_html(charts_data):
    """Format enhanced charts data to HTML"""
    if not charts_data:
        return "<p class='text-gray-500 italic'>Enhanced charts not available.</p>"
    
    html = ""
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
            <div class='border rounded p-2'>
                <h4 class='text-[11px] font-semibold mb-2 text-gray-600'>{title}</h4>
                <img src='{png_path}' alt='{title}' class='w-full'/>
            </div>
            """
    
    return html if html else "<p class='text-gray-500 italic'>Enhanced charts not available.</p>"


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
            data["enhanced_charts_html"] = format_enhanced_charts_html(data.get("enhanced_charts", {}))
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
  <link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500&display=swap" rel="stylesheet"/>
  <style>
   body {{ font-family: 'DM Sans', sans-serif; font-weight: 300; }}
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
     border-bottom: 1px solid #e5e7eb;
   }}
   .section:last-child {{
     border-bottom: none;
   }}
   .financial-table tr:not(:last-child) {{ border-bottom: 1px solid #e5e7eb; }}
   .financial-table td {{ padding: 4px 0; }}
   .data-source {{ border-bottom: 1px dotted #666; cursor: help; }}
   .ai-generated {{ position: relative; border-left: 2px solid #D2A74A; padding-left: 8px; margin: 8px 0; }}
   .ai-badge {{ display: inline-block; background: #D2A74A; color: white; font-size: 8px; padding: 1px 4px; border-radius: 2px; margin-left: 4px; }}
   .executive-summary {{ background: #f8f9fa; padding: 12px; border-radius: 4px; margin-bottom: 16px; }}
   .executive-summary h3 {{ color: #0B1B33; margin-bottom: 8px; }}
   .section-summary {{ background: #fafafa; padding: 8px; border-left: 3px solid #0B1B33; margin-top: 8px; font-style: italic; }}
   .catalyst-positive {{ color: #4A7C59; background: #E8F5E9; padding: 2px 6px; border-radius: 4px; display: inline-block; }}
   .catalyst-negative {{ color: #8B4513; background: #FFEBEE; padding: 2px 6px; border-radius: 4px; display: inline-block; }}
   .catalyst-neutral {{ color: #666666; background: #F5F5F5; padding: 2px 6px; border-radius: 4px; display: inline-block; }}
   .nav-bar {{
     position: sticky;
     top: 0;
     background: white;
     z-index: 100;
     padding: 10px 0;
     border-bottom: 2px solid #0B1B33;
     margin-bottom: 20px;
   }}
   .nav-bar a {{
     color: #0B1B33;
     text-decoration: none;
     margin-right: 20px;
     font-size: 12px;
     font-weight: 500;
   }}
   .nav-bar a:hover {{
     color: #D2A74A;
     text-decoration: underline;
   }}
   table {{ width: 100%; border-collapse: collapse; }}
   table th {{ background: #f3f4f6; font-weight: 600; text-align: right; padding: 8px; }}
   table th:first-child {{ text-align: left; }}
   table td {{ padding: 8px; text-align: right; border-bottom: 1px solid #e5e7eb; }}
   table td:first-child {{ text-align: left; font-weight: 500; }}
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
        <p class="text-gray-500 text-[12px]">{research_source}</p>
      </div>
      <div class="bg-black text-white px-2 py-1 w-full">
        <h1 class="text-2xl font-normal">US EQUITY RESEARCH</h1>
      </div>
      <p class="text-gray-500 text-[12px] text-right mt-1">{report_date}</p>
    </header>

    <!-- Section 1: Company Overview -->
    <section id="overview" class="section">
      <div class="flex justify-between mb-6">
        <div>
          <h2 class="text-[20px] text-gray-400 mb-3">{company_name_full}</h2>
          <p class="text-gray-600 text-[14px] leading-tight">{tagline}</p>
        </div>
        <div>
          <p class="text-gray-400 text-[14px]">Analysts</p>
          {analyst_contacts_html}
        </div>
      </div>
      <div class="flex gap-6">
        <div class="w-2/3">
          <h3 class="font-normal mb-2 text-[14px] text-gray-400">Company Overview</h3>
          <p class="mb-4 text-xs leading-tight">{company_overview}</p>
          <h3 class="font-normal mb-2 text-[14px] text-gray-400">Investment Update</h3>
          <p class="mb-4 text-xs leading-tight">{investment_overview}</p>
          <h3 class="font-normal mb-2 text-[14px] text-gray-400">Recent News Summary</h3>
          <p class="mb-4 text-xs leading-tight">{news_summary}</p>
          <h3 class="font-normal mb-2 text-[14px] text-gray-400">Valuation</h3>
          <p class="mb-4 text-xs leading-tight">{valuation_overview}</p>
          <h3 class="font-normal mb-2 text-[14px] text-gray-400">Risks</h3>
          <p class="text-xs leading-tight">{risks}</p>
        </div>
        <div class="w-1/3">
          <h3 class="font-normal mb-2 text-[14px] text-gray-400">Key Financial Data</h3>
          <div class="bg-gray-100 p-4 mb-4">
            <table class="w-full text-xs financial-table">
              <tr><td class="text-gray-500">Bloomberg Ticker</td><td class="text-black text-right">{company_ticker} US</td></tr>
              <tr><td class="text-gray-500">Sector</td><td class="text-black text-right">{sector}</td></tr>
              <tr><td class="text-gray-500">Share Price (USD)</td><td class="text-black text-right">{share_price}</td></tr>
              <tr><td class="text-gray-500">Rating</td><td class="text-black text-right">{rating}</td></tr>
              <tr><td class="text-gray-500">12-mth Target Price (USD)</td><td class="text-black text-right">{target_price}</td></tr>
              <tr><td class="text-gray-500">Market Cap (USDb)</td><td class="text-black text-right">{market_cap}</td></tr>
              <tr><td class="text-gray-500">Volume (m shares)</td><td class="text-black text-right">{volume}</td></tr>
              <tr><td class="text-gray-500">Free float (%)</td><td class="text-black text-right">{free_float}</td></tr>
              <tr><td class="text-gray-500">Dividend yield (%)</td><td class="text-black text-right">{dividend_yield}</td></tr>
              <tr><td class="text-gray-500">Net Debt to Equity (%)</td><td class="text-black text-right">{net_debt_to_equity}</td></tr>
              <tr><td class="text-gray-500">Fwd. P/E (x)</td><td class="text-black text-right">{fwd_pe}</td></tr>
              <tr><td class="text-gray-500">P/Book (x)</td><td class="text-black text-right">{pb_ratio}</td></tr>
              <tr><td class="text-gray-500">ROE (%)</td><td class="text-black text-right">{roe}</td></tr>
            </table>
          </div>
          <p class="text-[12px] text-gray-500 mb-2 italic">Closing Price as of {closing_price_date}</p>
          <p class="text-[12px] text-gray-500 mb-4">Source: {data_source_text}</p>
        </div>
      </div>
    </section>

    <!-- Section 2: Competitor Analysis -->
    <section id="competitor" class="section page-break">
      <h2 class="text-gray-500 text-[14px] font-bold mb-3">COMPETITOR ANALYSIS</h2>
      <p class="text-xs leading-tight mb-4">{competitor_analysis}</p>
      
      <div class="border border-gray-300 p-4 mb-6">
        <h3 class="font-bold text-xs mb-3">Major takeaways from {company_ticker} and peers:</h3>
        <div class="text-xs leading-tight whitespace-pre-line">{major_takeaways}</div>
      </div>
      
      <h2 class="text-gray-500 text-[14px] font-bold mb-3">FINANCIAL METRICS AND PEER COMPARISON CHARTS</h2>
      <div class="grid grid-cols-3 gap-3">
        <div>
          <h3 class="font-normal mb-2 text-[12px] text-gray-500">Revenue & EBITDA Trend</h3>
          <img src="{revenue_chart_path}" alt="Revenue and EBITDA Trend" class="w-full border"/>
        </div>
        <div>
          <h3 class="font-normal mb-2 text-[12px] text-gray-500">EPS × PE Trend Analysis</h3>
          <img src="{eps_pe_chart_path}" alt="EPS × PE Trend Analysis" class="w-full border"/>
        </div>
        <div>
          <h3 class="font-normal mb-2 text-[12px] text-gray-500">EV/EBITDA Peer Comparison</h3>
          <img src="{ev_ebitda_chart_path}" alt="EV/EBITDA Peer Comparison" class="w-full border"/>
        </div>
      </div>
    </section>

    <!-- Section 3: Financial Summary -->
    <section id="financials" class="section page-break">
      <h2 class="text-gray-500 text-[14px] font-bold mb-3">FINANCIAL SUMMARY (USD, unless otherwise stated)</h2>
      {financial_summary_table_html}
      
      <h2 class="text-gray-500 text-[14px] font-bold mb-3 mt-6">CREDIT & CASHFLOW METRICS</h2>
      {credit_cashflow_table_html}
      
      <h2 class="text-gray-500 text-[14px] font-bold mb-3 mt-6">PEER VALUATION METRICS (EV/EBITDA, x)</h2>
      {peer_ev_ebitda_table_html}
    </section>

    <!-- Section 4: Sensitivity & Catalyst Analysis -->
    <section id="sensitivity" class="section page-break">
      <div class="bg-black text-white px-2 py-1 w-full mb-4">
        <h1 class="text-xl font-normal">SENSITIVITY & CATALYST ANALYSIS</h1>
      </div>
      <div class="mb-6">
        <h2 class="text-gray-500 text-[14px] font-bold mb-3 border-b border-gray-300 pb-1">SENSITIVITY ANALYSIS</h2>
        <div class="text-xs leading-tight">{sensitivity_analysis_html}</div>
      </div>
      <div class="mb-6">
        <h2 class="text-gray-500 text-[14px] font-bold mb-3 border-b border-gray-300 pb-1">KEY CATALYSTS</h2>
        <div class="text-xs leading-tight">{catalyst_analysis_html}</div>
      </div>
    </section>

    <!-- Section 5: News & Enhanced Charts -->
    <section id="news" class="section page-break">
      <div class="bg-black text-white px-2 py-1 w-full mb-4">
        <h1 class="text-xl font-normal">NEWS & ENHANCED CHARTS</h1>
      </div>
      <div class="mb-6">
        <h2 class="text-gray-500 text-[14px] font-bold mb-3 border-b border-gray-300 pb-1">NEWS IMPACT ANALYSIS</h2>
        <div class="text-xs leading-tight">{enhanced_news_html}</div>
      </div>
      <div class="mb-6">
        <h2 class="text-gray-500 text-[14px] font-bold mb-3 border-b border-gray-300 pb-1">ENHANCED CHARTS</h2>
        <div class="grid grid-cols-2 gap-3">{enhanced_charts_html}</div>
      </div>
    </section>

    <!-- Footer -->
    <footer class="text-xs text-gray-500 pt-4">
      <p class="mb-2">{disclaimer_text}</p>
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
        
        # Default missing chart paths
        data.setdefault("revenue_chart_path", "")
        data.setdefault("ev_ebitda_chart_path", "")
        data.setdefault("eps_pe_chart_path", "")
        data.setdefault("financial_summary_table_html", "<p>Financial summary not available.</p>")
        data.setdefault("valuation_metrics_table_html", "<p>Valuation metrics not available.</p>")
        data.setdefault("peer_ebitda_table_html", "<p>Peer EBITDA data not available.</p>")
        data.setdefault("peer_ev_ebitda_table_html", "<p>Peer EV/EBITDA data not available.</p>")
        data.setdefault("credit_cashflow_table_html", "<p>Credit & Cashflow metrics not available.</p>")
        data.setdefault("news_summary", "Recent news coverage not available.")
        
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
            data["enhanced_charts_html"] = format_enhanced_charts_html(data.get("enhanced_charts", {}))
        except Exception as e:
            print(f"Warning: Error formatting enhanced charts: {e}")
            data["enhanced_charts_html"] = "<p class='text-gray-500 italic'>Enhanced charts not available.</p>"
        
        # Default competitor analysis and takeaways
        if "competitor_analysis" not in data or not data["competitor_analysis"]:
            data["competitor_analysis"] = "Comprehensive competitor analysis based on peer financial metrics and industry positioning will be generated using available data."
        
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