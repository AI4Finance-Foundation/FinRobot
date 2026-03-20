#!/usr/bin/env python
# coding: utf-8
"""
专业股票研究报告图表生成器
按照用户规范设计：深蓝主色、金色强调色、浅灰坐标轴
"""

import matplotlib
matplotlib.use("Agg")  # Use a non-interactive backend for running in scripts
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import pandas as pd
import os
import re
import io
import base64
from typing import Optional, List, Tuple


# =============================================================================
# 颜色规范 (与 pdf_generator.py 保持一致)
# =============================================================================
class ChartColors:
    """图表颜色规范"""
    # 主色（深蓝）- 主要数据线/柱
    PRIMARY = '#0B1B33'
    
    # 强调色（金色）- 对比数据线/柱
    ACCENT = '#D2A74A'
    
    # 辅色（中性深灰）- 文本
    TEXT = '#333333'
    
    # 背景浅灰 - 图表背景
    BACKGROUND = '#F5F5F5'
    
    # 分隔线/网格浅灰
    GRID = '#E0E0E0'
    
    # 中灰 - 次要数据
    MEDIUM_GRAY = '#666666'
    
    # 额外颜色 - 用于多数据系列
    SECONDARY_COLORS = [
        '#0B1B33',  # 深蓝 (主色)
        '#D2A74A',  # 金色 (强调色)
        '#666666',  # 中灰
        '#4A7C59',  # 绿色
        '#8B4513',  # 棕色
        '#2F4F4F',  # 暗青色
    ]


# =============================================================================
# 图表样式配置
# =============================================================================
def setup_chart_style():
    """设置全局图表样式"""
    plt.rcParams.update({
        'font.family': 'sans-serif',
        'font.sans-serif': ['Arial', 'Helvetica', 'DejaVu Sans'],
        'font.size': 9,
        'axes.titlesize': 11,
        'axes.titleweight': 'bold',
        'axes.labelsize': 9,
        'axes.labelcolor': ChartColors.TEXT,
        'axes.edgecolor': ChartColors.GRID,
        'axes.linewidth': 0.8,
        'axes.grid': True,
        'axes.facecolor': 'white',
        'grid.color': ChartColors.GRID,
        'grid.linestyle': '--',
        'grid.alpha': 0.7,
        'grid.linewidth': 0.5,
        'xtick.color': ChartColors.TEXT,
        'ytick.color': ChartColors.TEXT,
        'legend.fontsize': 8,
        'legend.framealpha': 0.9,
        'figure.facecolor': 'white',
        'figure.edgecolor': 'white',
        'savefig.facecolor': 'white',
        'savefig.edgecolor': 'white',
    })


def save_chart_to_base64(fig, output_path: str) -> str:
    """保存图表并返回Base64字符串"""
    buffer = io.BytesIO()
    fig.savefig(buffer, format='png', bbox_inches='tight', dpi=150, 
                facecolor='white', edgecolor='none')
    buffer.seek(0)
    
    # 保存到文件
    with open(output_path, "wb") as f:
        f.write(buffer.getvalue())
    
    # 返回Base64
    buffer.seek(0)
    image_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
    plt.close(fig)
    
    return f"data:image/png;base64,{image_base64}"


# =============================================================================
# 图表生成函数
# =============================================================================
def generate_revenue_ebitda_chart(analysis_df: pd.DataFrame, output_path: str, company_ticker: str) -> Optional[str]:
    """
    生成 Revenue & EBITDA 组合图表（柱状图 + 折线图）
    
    Args:
        analysis_df: 包含财务数据的DataFrame
        output_path: 输出图片路径
        company_ticker: 股票代码
    
    Returns:
        Base64编码的图片字符串
    """
    setup_chart_style()
    
    try:
        if analysis_df.empty or "metrics" not in analysis_df.columns:
            print("Warning: Analysis data is empty or missing 'metrics' column for revenue/EBITDA chart.")
            return None

        year_pattern = re.compile(r'^\d{4}[AE]$')
        years = sorted([col for col in analysis_df.columns if year_pattern.match(col)], 
                      key=lambda x: (int(x[:4]), x[-1]))
        if not years:
            print("Warning: No valid year columns found for charting.")
            return None

        revenue_data = pd.to_numeric(
            analysis_df[analysis_df["metrics"] == "Revenue"][years].iloc[0], 
            errors='coerce'
        )
        ebitda_data = pd.to_numeric(
            analysis_df[analysis_df["metrics"] == "EBITDA"][years].iloc[0], 
            errors='coerce'
        )

        if revenue_data.isnull().all() or ebitda_data.isnull().all():
            print("Warning: Revenue or EBITDA data is non-numeric.")
            return None

        # 转换为十亿美元
        revenue_billions = revenue_data / 1e9
        ebitda_billions = ebitda_data / 1e9

        fig, ax1 = plt.subplots(figsize=(7, 4))
        
        x = np.arange(len(years))
        width = 0.6
        
        # 柱状图 - Revenue (深蓝色)
        bars = ax1.bar(x, revenue_billions, width, color=ChartColors.PRIMARY, 
                       alpha=0.85, label='Revenue', edgecolor='white', linewidth=0.5)
        
        ax1.set_xlabel('Year', fontsize=9, color=ChartColors.TEXT)
        ax1.set_ylabel('Revenue ($B)', fontsize=9, color=ChartColors.PRIMARY)
        ax1.tick_params(axis='y', labelcolor=ChartColors.PRIMARY)
        ax1.set_xticks(x)
        ax1.set_xticklabels(years, rotation=45, ha='right')
        
        # 折线图 - EBITDA (金色)
        ax2 = ax1.twinx()
        line = ax2.plot(x, ebitda_billions, color=ChartColors.ACCENT, marker='o', 
                        markersize=6, linewidth=2.5, label='EBITDA')
        ax2.set_ylabel('EBITDA ($B)', fontsize=9, color=ChartColors.ACCENT)
        ax2.tick_params(axis='y', labelcolor=ChartColors.ACCENT)
        
        # 标题
        ax1.set_title(f"{company_ticker} - Revenue & EBITDA Trend", 
                     fontsize=11, fontweight='bold', color=ChartColors.TEXT, pad=15)
        
        # 图例
        bar_patch = mpatches.Patch(color=ChartColors.PRIMARY, label='Revenue')
        line_patch = mpatches.Patch(color=ChartColors.ACCENT, label='EBITDA')
        ax1.legend(handles=[bar_patch, line_patch], loc='upper left', 
                   framealpha=0.9, fontsize=8)
        
        # 网格只在主轴
        ax1.grid(True, axis='y', linestyle='--', alpha=0.5)
        ax1.set_axisbelow(True)
        
        fig.tight_layout()
        
        result = save_chart_to_base64(fig, output_path)
        print(f"✅ Revenue/EBITDA chart saved to {output_path}")
        return result

    except Exception as e:
        print(f"❌ Error generating Revenue/EBITDA chart: {e}")
        import traceback
        traceback.print_exc()
        return None


def generate_ev_ebitda_peer_chart(peer_ev_ebitda_df: pd.DataFrame, output_path: str, 
                                  target_ticker: str) -> Optional[str]:
    """
    生成 EV/EBITDA 同行对比图表（分组柱状图或折线图）
    
    Args:
        peer_ev_ebitda_df: 同行EV/EBITDA数据DataFrame
        output_path: 输出图片路径
        target_ticker: 目标股票代码
    
    Returns:
        Base64编码的图片字符串
    """
    setup_chart_style()
    
    try:
        if peer_ev_ebitda_df.empty:
            print("Warning: Peer EV/EBITDA data is empty for chart generation.")
            return None

        fig, ax = plt.subplots(figsize=(7, 4))
        
        # 如果是多年数据，使用折线图
        if len(peer_ev_ebitda_df) > 1:
            years = peer_ev_ebitda_df.index.astype(str)
            x = np.arange(len(years))
            
            for i, ticker in enumerate(peer_ev_ebitda_df.columns):
                color = ChartColors.PRIMARY if ticker == target_ticker else ChartColors.SECONDARY_COLORS[i % len(ChartColors.SECONDARY_COLORS)]
                linewidth = 2.5 if ticker == target_ticker else 1.5
                marker = 's' if ticker == target_ticker else 'o'
                markersize = 7 if ticker == target_ticker else 5
                
                ax.plot(x, peer_ev_ebitda_df[ticker], marker=marker, 
                       markersize=markersize, linewidth=linewidth, 
                       color=color, label=ticker)
            
            ax.set_xticks(x)
            ax.set_xticklabels(years, rotation=45, ha='right')
        else:
            # 单年数据，使用柱状图
            companies = peer_ev_ebitda_df.columns.tolist()
            values = peer_ev_ebitda_df.iloc[0].values
            x = np.arange(len(companies))
            
            colors = [ChartColors.PRIMARY if c == target_ticker else ChartColors.MEDIUM_GRAY 
                     for c in companies]
            
            bars = ax.bar(x, values, color=colors, edgecolor='white', linewidth=0.5)
            ax.set_xticks(x)
            ax.set_xticklabels(companies, rotation=45, ha='right')
        
        ax.set_xlabel('', fontsize=9)
        ax.set_ylabel('EV/EBITDA (x)', fontsize=9, color=ChartColors.TEXT)
        ax.set_title(f"EV/EBITDA Peer Comparison", 
                    fontsize=11, fontweight='bold', color=ChartColors.TEXT, pad=15)
        
        if len(peer_ev_ebitda_df) > 1:
            ax.legend(loc='upper right', framealpha=0.9, fontsize=8)
        
        ax.grid(True, axis='y', linestyle='--', alpha=0.5)
        ax.set_axisbelow(True)
        
        fig.tight_layout()
        
        result = save_chart_to_base64(fig, output_path)
        print(f"✅ EV/EBITDA peer chart saved to {output_path}")
        return result

    except Exception as e:
        print(f"❌ Error generating EV/EBITDA peer chart: {e}")
        import traceback
        traceback.print_exc()
        return None


def generate_eps_pe_chart(analysis_df: pd.DataFrame, output_path: str, 
                          company_ticker: str) -> Optional[str]:
    """
    生成 EPS × PE 双折线趋势图
    
    Args:
        analysis_df: 包含财务数据的DataFrame
        output_path: 输出图片路径
        company_ticker: 股票代码
    
    Returns:
        Base64编码的图片字符串
    """
    setup_chart_style()
    
    try:
        if analysis_df.empty or "metrics" not in analysis_df.columns:
            print("Warning: Analysis data is empty or missing 'metrics' column for EPS × PE chart.")
            return None

        year_pattern = re.compile(r'^\d{4}[AE]$')
        years = sorted([col for col in analysis_df.columns if year_pattern.match(col)], 
                      key=lambda x: (int(x[:4]), x[-1]))
        if not years:
            print("Warning: No valid year columns found for charting.")
            return None

        eps_row = analysis_df[analysis_df["metrics"] == "EPS"]
        pe_row = analysis_df[analysis_df["metrics"] == "PE Ratio"]
        
        if eps_row.empty or pe_row.empty:
            print("Warning: EPS or PE Ratio data not found.")
            return None

        eps_data = pd.to_numeric(eps_row[years].iloc[0], errors='coerce')
        pe_data = pd.to_numeric(pe_row[years].iloc[0], errors='coerce')

        if eps_data.isnull().all() or pe_data.isnull().all():
            print("Warning: EPS or PE data is non-numeric.")
            return None

        fig, ax1 = plt.subplots(figsize=(7, 4))
        
        x = np.arange(len(years))
        
        # EPS 折线 (深蓝色，左轴)
        line1 = ax1.plot(x, eps_data, color=ChartColors.PRIMARY, marker='o', 
                        markersize=6, linewidth=2.5, label='EPS ($)')
        ax1.set_xlabel('Year', fontsize=9, color=ChartColors.TEXT)
        ax1.set_ylabel('EPS ($)', fontsize=9, color=ChartColors.PRIMARY)
        ax1.tick_params(axis='y', labelcolor=ChartColors.PRIMARY)
        ax1.set_xticks(x)
        ax1.set_xticklabels(years, rotation=45, ha='right')
        
        # PE Ratio 折线 (金色，右轴)
        ax2 = ax1.twinx()
        line2 = ax2.plot(x, pe_data, color=ChartColors.ACCENT, marker='s', 
                        markersize=6, linewidth=2.5, linestyle='--', label='PE Ratio (x)')
        ax2.set_ylabel('PE Ratio (x)', fontsize=9, color=ChartColors.ACCENT)
        ax2.tick_params(axis='y', labelcolor=ChartColors.ACCENT)
        
        # 标题
        ax1.set_title(f"{company_ticker} - EPS × PE Trend Analysis", 
                     fontsize=11, fontweight='bold', color=ChartColors.TEXT, pad=15)
        
        # 合并图例
        lines1, labels1 = ax1.get_legend_handles_labels()
        lines2, labels2 = ax2.get_legend_handles_labels()
        ax1.legend(lines1 + lines2, labels1 + labels2, loc='upper left', 
                  framealpha=0.9, fontsize=8)
        
        ax1.grid(True, axis='y', linestyle='--', alpha=0.5)
        ax1.set_axisbelow(True)
        
        fig.tight_layout()
        
        result = save_chart_to_base64(fig, output_path)
        print(f"✅ EPS × PE chart saved to {output_path}")
        return result

    except Exception as e:
        print(f"❌ Error generating EPS × PE chart: {e}")
        import traceback
        traceback.print_exc()
        return None


def generate_margin_trend_chart(analysis_df: pd.DataFrame, output_path: str,
                                 company_ticker: str) -> Optional[str]:
    """
    生成利润率趋势图（多条折线）
    
    Args:
        analysis_df: 包含财务数据的DataFrame
        output_path: 输出图片路径
        company_ticker: 股票代码
    
    Returns:
        Base64编码的图片字符串
    """
    setup_chart_style()
    
    try:
        if analysis_df.empty or "metrics" not in analysis_df.columns:
            return None

        year_pattern = re.compile(r'^\d{4}[AE]$')
        years = sorted([col for col in analysis_df.columns if year_pattern.match(col)], 
                      key=lambda x: (int(x[:4]), x[-1]))
        if not years:
            return None

        # 提取各种利润率
        margin_metrics = ['Contribution Margin', 'EBITDA Margin', 'SG&A Margin']
        margin_data = {}
        
        for metric in margin_metrics:
            row = analysis_df[analysis_df["metrics"] == metric]
            if not row.empty:
                data = row[years].iloc[0]
                # 转换百分比字符串为数值
                values = []
                for v in data:
                    if isinstance(v, str) and '%' in v:
                        values.append(float(v.replace('%', '')))
                    elif pd.notna(v):
                        val = float(v)
                        if val < 1:  # 假设是小数形式
                            values.append(val * 100)
                        else:
                            values.append(val)
                    else:
                        values.append(np.nan)
                margin_data[metric] = values

        if not margin_data:
            return None

        fig, ax = plt.subplots(figsize=(7, 4))
        
        x = np.arange(len(years))
        colors = [ChartColors.PRIMARY, ChartColors.ACCENT, ChartColors.MEDIUM_GRAY]
        markers = ['o', 's', '^']
        
        for i, (metric, values) in enumerate(margin_data.items()):
            ax.plot(x, values, color=colors[i % len(colors)], 
                   marker=markers[i % len(markers)], markersize=6, 
                   linewidth=2, label=metric)
        
        ax.set_xlabel('Year', fontsize=9, color=ChartColors.TEXT)
        ax.set_ylabel('Margin (%)', fontsize=9, color=ChartColors.TEXT)
        ax.set_xticks(x)
        ax.set_xticklabels(years, rotation=45, ha='right')
        ax.set_title(f"{company_ticker} - Profit Margin Trends", 
                    fontsize=11, fontweight='bold', color=ChartColors.TEXT, pad=15)
        ax.legend(loc='best', framealpha=0.9, fontsize=8)
        ax.grid(True, axis='y', linestyle='--', alpha=0.5)
        ax.set_axisbelow(True)
        
        fig.tight_layout()
        
        result = save_chart_to_base64(fig, output_path)
        print(f"✅ Margin trend chart saved to {output_path}")
        return result

    except Exception as e:
        print(f"❌ Error generating margin trend chart: {e}")
        return None


def generate_revenue_breakdown_pie(revenue_segments: dict, output_path: str,
                                   company_ticker: str) -> Optional[str]:
    """
    生成收入构成饼状图
    
    Args:
        revenue_segments: 收入分类字典 {"iPhone": 200B, "Services": 80B, ...}
        output_path: 输出图片路径
        company_ticker: 股票代码
    
    Returns:
        Base64编码的图片字符串
    """
    setup_chart_style()
    
    try:
        if not revenue_segments:
            return None

        fig, ax = plt.subplots(figsize=(7, 5))
        
        labels = list(revenue_segments.keys())
        sizes = list(revenue_segments.values())
        
        # 生成颜色
        colors = ChartColors.SECONDARY_COLORS[:len(labels)]
        if len(labels) > len(colors):
            # 扩展颜色
            import matplotlib.cm as cm
            cmap = cm.get_cmap('Blues')
            colors = [cmap(i/len(labels)) for i in range(len(labels))]
        
        # 饼图
        wedges, texts, autotexts = ax.pie(
            sizes, labels=labels, colors=colors, autopct='%1.1f%%',
            startangle=90, pctdistance=0.75,
            wedgeprops={'edgecolor': 'white', 'linewidth': 2}
        )
        
        # 设置文字颜色
        for text in texts:
            text.set_color(ChartColors.TEXT)
            text.set_fontsize(9)
        for autotext in autotexts:
            autotext.set_color('white')
            autotext.set_fontweight('bold')
            autotext.set_fontsize(8)
        
        ax.set_title(f"{company_ticker} - Revenue Breakdown", 
                    fontsize=11, fontweight='bold', color=ChartColors.TEXT, pad=15)
        
        fig.tight_layout()
        
        result = save_chart_to_base64(fig, output_path)
        print(f"✅ Revenue breakdown pie chart saved to {output_path}")
        return result

    except Exception as e:
        print(f"❌ Error generating revenue breakdown chart: {e}")
        return None


# =============================================================================
# 高级图表 - 股价走势图
# =============================================================================
def generate_stock_price_chart(price_data: pd.DataFrame, output_path: str,
                               company_ticker: str, period: str = "1Y") -> Optional[str]:
    """
    生成股价走势图（含移动平均线）
    
    Args:
        price_data: 包含日期和价格的DataFrame (columns: date, close, volume)
        output_path: 输出图片路径
        company_ticker: 股票代码
        period: 时间周期标签
    
    Returns:
        Base64编码的图片字符串
    """
    setup_chart_style()
    
    try:
        if price_data.empty:
            print("Warning: Price data is empty for stock price chart.")
            return None

        df = price_data.copy()
        if 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date'])
            df = df.sort_values('date')
        
        # 计算移动平均线
        if len(df) >= 20:
            df['MA20'] = df['close'].rolling(window=20).mean()
        if len(df) >= 50:
            df['MA50'] = df['close'].rolling(window=50).mean()
        if len(df) >= 200:
            df['MA200'] = df['close'].rolling(window=200).mean()

        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 7), 
                                        gridspec_kw={'height_ratios': [3, 1]})
        
        # 上图：股价和移动平均线
        ax1.plot(df['date'], df['close'], color=ChartColors.PRIMARY, 
                linewidth=1.5, label='Price', alpha=0.9)
        
        if 'MA20' in df.columns:
            ax1.plot(df['date'], df['MA20'], color=ChartColors.ACCENT, 
                    linewidth=1.2, label='MA20', linestyle='--')
        if 'MA50' in df.columns:
            ax1.plot(df['date'], df['MA50'], color=ChartColors.MEDIUM_GRAY, 
                    linewidth=1.2, label='MA50', linestyle='-.')
        if 'MA200' in df.columns:
            ax1.plot(df['date'], df['MA200'], color='#4A7C59', 
                    linewidth=1.2, label='MA200', linestyle=':')
        
        ax1.set_ylabel('Price ($)', fontsize=10, color=ChartColors.TEXT)
        ax1.set_title(f"{company_ticker} Stock Price ({period})", 
                     fontsize=12, fontweight='bold', color=ChartColors.TEXT, pad=15)
        ax1.legend(loc='upper left', framealpha=0.9, fontsize=8)
        ax1.grid(True, linestyle='--', alpha=0.5)
        ax1.set_xlim(df['date'].min(), df['date'].max())
        
        # 下图：成交量
        if 'volume' in df.columns:
            colors = [ChartColors.PRIMARY if df['close'].iloc[i] >= df['close'].iloc[i-1] 
                     else ChartColors.ACCENT for i in range(1, len(df))]
            colors.insert(0, ChartColors.PRIMARY)
            ax2.bar(df['date'], df['volume'] / 1e6, color=colors, alpha=0.7, width=1)
            ax2.set_ylabel('Volume (M)', fontsize=10, color=ChartColors.TEXT)
            ax2.set_xlabel('Date', fontsize=10, color=ChartColors.TEXT)
            ax2.grid(True, axis='y', linestyle='--', alpha=0.5)
            ax2.set_xlim(df['date'].min(), df['date'].max())
        
        fig.tight_layout()
        
        result = save_chart_to_base64(fig, output_path)
        print(f"✅ Stock price chart saved to {output_path}")
        return result

    except Exception as e:
        print(f"❌ Error generating stock price chart: {e}")
        import traceback
        traceback.print_exc()
        return None


# =============================================================================
# 高级图表 - 财务比率雷达图
# =============================================================================
def generate_financial_radar_chart(ratios: dict, output_path: str,
                                   company_ticker: str, 
                                   peer_ratios: dict = None) -> Optional[str]:
    """
    生成财务比率雷达图
    
    Args:
        ratios: 公司财务比率字典 {"ROE": 15, "ROA": 8, "Gross Margin": 40, ...}
        output_path: 输出图片路径
        company_ticker: 股票代码
        peer_ratios: 同行平均比率（可选）
    
    Returns:
        Base64编码的图片字符串
    """
    setup_chart_style()
    
    try:
        if not ratios:
            print("Warning: No ratio data for radar chart.")
            return None

        categories = list(ratios.keys())
        values = list(ratios.values())
        
        # 标准化数值到0-100范围
        max_val = max(abs(v) for v in values if v is not None) or 1
        normalized_values = [(v / max_val * 100 if v else 0) for v in values]
        
        # 闭合雷达图
        num_vars = len(categories)
        angles = [n / float(num_vars) * 2 * np.pi for n in range(num_vars)]
        angles += angles[:1]
        normalized_values += normalized_values[:1]
        
        fig, ax = plt.subplots(figsize=(8, 8), subplot_kw=dict(polar=True))
        
        # 绘制公司数据
        ax.plot(angles, normalized_values, 'o-', linewidth=2, 
               color=ChartColors.PRIMARY, label=company_ticker)
        ax.fill(angles, normalized_values, alpha=0.25, color=ChartColors.PRIMARY)
        
        # 绘制同行数据（如果有）
        if peer_ratios:
            peer_values = [peer_ratios.get(cat, 0) for cat in categories]
            peer_normalized = [(v / max_val * 100 if v else 0) for v in peer_values]
            peer_normalized += peer_normalized[:1]
            ax.plot(angles, peer_normalized, 'o-', linewidth=2, 
                   color=ChartColors.ACCENT, label='Peer Average', linestyle='--')
            ax.fill(angles, peer_normalized, alpha=0.15, color=ChartColors.ACCENT)
        
        # 设置标签
        ax.set_xticks(angles[:-1])
        ax.set_xticklabels(categories, fontsize=9, color=ChartColors.TEXT)
        
        ax.set_title(f"{company_ticker} Financial Ratios", 
                    fontsize=12, fontweight='bold', color=ChartColors.TEXT, pad=20)
        ax.legend(loc='upper right', bbox_to_anchor=(1.3, 1.0), fontsize=9)
        ax.grid(True, linestyle='--', alpha=0.5)
        
        fig.tight_layout()
        
        result = save_chart_to_base64(fig, output_path)
        print(f"✅ Financial radar chart saved to {output_path}")
        return result

    except Exception as e:
        print(f"❌ Error generating financial radar chart: {e}")
        import traceback
        traceback.print_exc()
        return None



# =============================================================================
# 高级图表 - 时序分析图（多指标对比）
# =============================================================================
def generate_time_series_chart(data: pd.DataFrame, metrics: List[str], 
                               output_path: str, company_ticker: str,
                               title: str = "Time Series Analysis") -> Optional[str]:
    """
    生成时序分析图（多指标对比）
    
    Args:
        data: 包含时间序列数据的DataFrame
        metrics: 要绘制的指标列表
        output_path: 输出图片路径
        company_ticker: 股票代码
        title: 图表标题
    
    Returns:
        Base64编码的图片字符串
    """
    setup_chart_style()
    
    try:
        if data.empty or not metrics:
            print("Warning: No data for time series chart.")
            return None

        fig, ax = plt.subplots(figsize=(10, 6))
        
        colors = ChartColors.SECONDARY_COLORS
        markers = ['o', 's', '^', 'D', 'v', '<', '>', 'p']
        
        for i, metric in enumerate(metrics):
            if metric in data.columns:
                color = colors[i % len(colors)]
                marker = markers[i % len(markers)]
                ax.plot(data.index, data[metric], color=color, marker=marker,
                       markersize=5, linewidth=1.8, label=metric, alpha=0.85)
        
        ax.set_xlabel('Period', fontsize=10, color=ChartColors.TEXT)
        ax.set_ylabel('Value', fontsize=10, color=ChartColors.TEXT)
        ax.set_title(f"{company_ticker} - {title}", 
                    fontsize=12, fontweight='bold', color=ChartColors.TEXT, pad=15)
        ax.legend(loc='best', framealpha=0.9, fontsize=9)
        ax.grid(True, linestyle='--', alpha=0.5)
        
        # 旋转x轴标签
        plt.setp(ax.get_xticklabels(), rotation=45, ha='right')
        
        fig.tight_layout()
        
        result = save_chart_to_base64(fig, output_path)
        print(f"✅ Time series chart saved to {output_path}")
        return result

    except Exception as e:
        print(f"❌ Error generating time series chart: {e}")
        import traceback
        traceback.print_exc()
        return None


# =============================================================================
# 高级图表 - 敏感性热力图
# =============================================================================
def generate_sensitivity_heatmap(sensitivity_data: pd.DataFrame, output_path: str,
                                 company_ticker: str, 
                                 title: str = "Sensitivity Analysis") -> Optional[str]:
    """
    生成敏感性分析热力图
    
    Args:
        sensitivity_data: 敏感性分析矩阵DataFrame
        output_path: 输出图片路径
        company_ticker: 股票代码
        title: 图表标题
    
    Returns:
        Base64编码的图片字符串
    """
    setup_chart_style()
    
    try:
        if sensitivity_data.empty:
            print("Warning: No data for sensitivity heatmap.")
            return None

        fig, ax = plt.subplots(figsize=(10, 8))
        
        # 创建热力图
        import matplotlib.colors as mcolors
        
        # 自定义颜色映射：红-白-绿
        colors_list = ['#8B0000', '#FF6B6B', '#FFFFFF', '#90EE90', '#006400']
        cmap = mcolors.LinearSegmentedColormap.from_list('custom', colors_list)
        
        # 转换数据为数值
        numeric_data = sensitivity_data.apply(pd.to_numeric, errors='coerce')
        
        im = ax.imshow(numeric_data.values, cmap=cmap, aspect='auto')
        
        # 设置刻度
        ax.set_xticks(np.arange(len(sensitivity_data.columns)))
        ax.set_yticks(np.arange(len(sensitivity_data.index)))
        ax.set_xticklabels(sensitivity_data.columns, fontsize=9)
        ax.set_yticklabels(sensitivity_data.index, fontsize=9)
        
        # 旋转x轴标签
        plt.setp(ax.get_xticklabels(), rotation=45, ha='right')
        
        # 添加数值标签
        for i in range(len(sensitivity_data.index)):
            for j in range(len(sensitivity_data.columns)):
                val = sensitivity_data.iloc[i, j]
                if pd.notna(val):
                    text_color = 'white' if abs(numeric_data.iloc[i, j]) > numeric_data.values.max() * 0.5 else 'black'
                    ax.text(j, i, f'{val}', ha='center', va='center', 
                           fontsize=8, color=text_color)
        
        # 颜色条
        cbar = ax.figure.colorbar(im, ax=ax, shrink=0.8)
        cbar.ax.set_ylabel('Value', fontsize=10)
        
        ax.set_title(f"{company_ticker} - {title}", 
                    fontsize=12, fontweight='bold', color=ChartColors.TEXT, pad=15)
        
        fig.tight_layout()
        
        result = save_chart_to_base64(fig, output_path)
        print(f"✅ Sensitivity heatmap saved to {output_path}")
        return result

    except Exception as e:
        print(f"❌ Error generating sensitivity heatmap: {e}")
        import traceback
        traceback.print_exc()
        return None


# =============================================================================
# 高级图表 - 技术指标图（RSI, MACD）
# =============================================================================
def generate_technical_indicators_chart(price_data: pd.DataFrame, output_path: str,
                                        company_ticker: str) -> Optional[str]:
    """
    生成技术指标图（RSI和MACD）
    
    Args:
        price_data: 包含日期和价格的DataFrame
        output_path: 输出图片路径
        company_ticker: 股票代码
    
    Returns:
        Base64编码的图片字符串
    """
    setup_chart_style()
    
    try:
        if price_data.empty or 'close' not in price_data.columns:
            print("Warning: No price data for technical indicators.")
            return None

        df = price_data.copy()
        if 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date'])
            df = df.sort_values('date')
        
        # 计算RSI
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['RSI'] = 100 - (100 / (1 + rs))
        
        # 计算MACD
        exp1 = df['close'].ewm(span=12, adjust=False).mean()
        exp2 = df['close'].ewm(span=26, adjust=False).mean()
        df['MACD'] = exp1 - exp2
        df['Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
        df['MACD_Hist'] = df['MACD'] - df['Signal']

        fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(10, 9), 
                                            gridspec_kw={'height_ratios': [2, 1, 1]})
        
        # 上图：股价
        ax1.plot(df['date'], df['close'], color=ChartColors.PRIMARY, 
                linewidth=1.5, label='Price')
        ax1.set_ylabel('Price ($)', fontsize=10)
        ax1.set_title(f"{company_ticker} Technical Analysis", 
                     fontsize=12, fontweight='bold', pad=15)
        ax1.legend(loc='upper left', fontsize=8)
        ax1.grid(True, linestyle='--', alpha=0.5)
        ax1.set_xlim(df['date'].min(), df['date'].max())
        
        # 中图：RSI
        ax2.plot(df['date'], df['RSI'], color=ChartColors.ACCENT, linewidth=1.5)
        ax2.axhline(y=70, color='red', linestyle='--', alpha=0.7, label='Overbought (70)')
        ax2.axhline(y=30, color='green', linestyle='--', alpha=0.7, label='Oversold (30)')
        ax2.fill_between(df['date'], 30, 70, alpha=0.1, color='gray')
        ax2.set_ylabel('RSI', fontsize=10)
        ax2.set_ylim(0, 100)
        ax2.legend(loc='upper left', fontsize=8)
        ax2.grid(True, linestyle='--', alpha=0.5)
        ax2.set_xlim(df['date'].min(), df['date'].max())
        
        # 下图：MACD
        ax3.plot(df['date'], df['MACD'], color=ChartColors.PRIMARY, 
                linewidth=1.5, label='MACD')
        ax3.plot(df['date'], df['Signal'], color=ChartColors.ACCENT, 
                linewidth=1.5, label='Signal', linestyle='--')
        
        # MACD柱状图
        colors = [ChartColors.PRIMARY if v >= 0 else '#8B0000' for v in df['MACD_Hist']]
        ax3.bar(df['date'], df['MACD_Hist'], color=colors, alpha=0.5, width=1)
        
        ax3.axhline(y=0, color='black', linestyle='-', linewidth=0.5)
        ax3.set_ylabel('MACD', fontsize=10)
        ax3.set_xlabel('Date', fontsize=10)
        ax3.legend(loc='upper left', fontsize=8)
        ax3.grid(True, linestyle='--', alpha=0.5)
        ax3.set_xlim(df['date'].min(), df['date'].max())
        
        fig.tight_layout()
        
        result = save_chart_to_base64(fig, output_path)
        print(f"✅ Technical indicators chart saved to {output_path}")
        return result

    except Exception as e:
        print(f"❌ Error generating technical indicators chart: {e}")
        import traceback
        traceback.print_exc()
        return None


# =============================================================================
# 高级图表 - 估值对比瀑布图
# =============================================================================
def generate_valuation_waterfall_chart(valuation_components: dict, output_path: str,
                                       company_ticker: str) -> Optional[str]:
    """
    生成估值瀑布图
    
    Args:
        valuation_components: 估值组成部分 {"Base Value": 100, "Growth Premium": 20, ...}
        output_path: 输出图片路径
        company_ticker: 股票代码
    
    Returns:
        Base64编码的图片字符串
    """
    setup_chart_style()
    
    try:
        if not valuation_components:
            print("Warning: No valuation data for waterfall chart.")
            return None

        labels = list(valuation_components.keys())
        values = list(valuation_components.values())
        
        # 计算累计值
        cumulative = [0]
        for v in values[:-1]:
            cumulative.append(cumulative[-1] + v)
        
        fig, ax = plt.subplots(figsize=(10, 6))
        
        # 绘制瀑布图
        for i, (label, value) in enumerate(zip(labels, values)):
            if i == 0:
                # 起始值
                ax.bar(i, value, color=ChartColors.PRIMARY, edgecolor='white')
            elif i == len(labels) - 1:
                # 最终值
                ax.bar(i, value, color=ChartColors.PRIMARY, edgecolor='white')
            else:
                # 中间变化
                color = ChartColors.ACCENT if value >= 0 else '#8B0000'
                ax.bar(i, value, bottom=cumulative[i], color=color, 
                      edgecolor='white', alpha=0.85)
                
                # 连接线
                if i < len(labels) - 1:
                    ax.plot([i - 0.4, i + 0.4], [cumulative[i] + value, cumulative[i] + value],
                           color='gray', linestyle='--', linewidth=0.8)
        
        # 添加数值标签
        for i, (label, value) in enumerate(zip(labels, values)):
            y_pos = value / 2 if i == 0 or i == len(labels) - 1 else cumulative[i] + value / 2
            ax.text(i, y_pos, f'${value:.0f}', ha='center', va='center', 
                   fontsize=9, fontweight='bold', color='white')
        
        ax.set_xticks(range(len(labels)))
        ax.set_xticklabels(labels, rotation=45, ha='right', fontsize=9)
        ax.set_ylabel('Value ($)', fontsize=10)
        ax.set_title(f"{company_ticker} - Valuation Bridge", 
                    fontsize=12, fontweight='bold', pad=15)
        ax.grid(True, axis='y', linestyle='--', alpha=0.5)
        
        fig.tight_layout()
        
        result = save_chart_to_base64(fig, output_path)
        print(f"✅ Valuation waterfall chart saved to {output_path}")
        return result

    except Exception as e:
        print(f"❌ Error generating valuation waterfall chart: {e}")
        import traceback
        traceback.print_exc()
        return None


# =============================================================================
# 高级图表 - 季度财务对比图
# =============================================================================
def generate_quarterly_comparison_chart(quarterly_data: pd.DataFrame, 
                                        metrics: List[str],
                                        output_path: str, 
                                        company_ticker: str) -> Optional[str]:
    """
    生成季度财务对比图（同比/环比）
    
    Args:
        quarterly_data: 季度财务数据DataFrame
        metrics: 要对比的指标列表
        output_path: 输出图片路径
        company_ticker: 股票代码
    
    Returns:
        Base64编码的图片字符串
    """
    setup_chart_style()
    
    try:
        if quarterly_data.empty or not metrics:
            print("Warning: No quarterly data for comparison chart.")
            return None

        fig, axes = plt.subplots(len(metrics), 1, figsize=(10, 4 * len(metrics)))
        if len(metrics) == 1:
            axes = [axes]
        
        colors = ChartColors.SECONDARY_COLORS
        
        for i, metric in enumerate(metrics):
            ax = axes[i]
            if metric in quarterly_data.columns:
                data = quarterly_data[metric]
                
                # 计算同比增长
                yoy_growth = data.pct_change(4) * 100  # 假设季度数据
                
                # 柱状图
                x = np.arange(len(data))
                bar_colors = [ChartColors.PRIMARY if g >= 0 else '#8B0000' 
                             for g in yoy_growth.fillna(0)]
                ax.bar(x, data, color=bar_colors, alpha=0.85, edgecolor='white')
                
                # 增长率折线
                ax2 = ax.twinx()
                ax2.plot(x, yoy_growth, color=ChartColors.ACCENT, 
                        marker='o', linewidth=2, label='YoY Growth %')
                ax2.axhline(y=0, color='gray', linestyle='--', alpha=0.5)
                ax2.set_ylabel('YoY Growth (%)', fontsize=9, color=ChartColors.ACCENT)
                
                ax.set_ylabel(metric, fontsize=9)
                ax.set_title(f"{metric} - Quarterly Trend", fontsize=10, fontweight='bold')
                ax.set_xticks(x)
                ax.set_xticklabels(quarterly_data.index, rotation=45, ha='right', fontsize=8)
                ax.grid(True, axis='y', linestyle='--', alpha=0.5)
        
        fig.suptitle(f"{company_ticker} - Quarterly Financial Analysis", 
                    fontsize=12, fontweight='bold', y=1.02)
        fig.tight_layout()
        
        result = save_chart_to_base64(fig, output_path)
        print(f"✅ Quarterly comparison chart saved to {output_path}")
        return result

    except Exception as e:
        print(f"❌ Error generating quarterly comparison chart: {e}")
        import traceback
        traceback.print_exc()
        return None


# =============================================================================
# 高级图表 - 现金流分析图
# =============================================================================
def generate_cash_flow_chart(cash_flow_data: dict, output_path: str,
                             company_ticker: str) -> Optional[str]:
    """
    生成现金流分析图（堆叠柱状图）
    
    Args:
        cash_flow_data: 现金流数据 {"Operating": [...], "Investing": [...], "Financing": [...]}
        output_path: 输出图片路径
        company_ticker: 股票代码
    
    Returns:
        Base64编码的图片字符串
    """
    setup_chart_style()
    
    try:
        if not cash_flow_data:
            print("Warning: No cash flow data for chart.")
            return None

        fig, ax = plt.subplots(figsize=(10, 6))
        
        periods = cash_flow_data.get('periods', [f'Q{i+1}' for i in range(len(list(cash_flow_data.values())[0]))])
        x = np.arange(len(periods))
        width = 0.25
        
        # 三种现金流
        operating = cash_flow_data.get('Operating', [0] * len(periods))
        investing = cash_flow_data.get('Investing', [0] * len(periods))
        financing = cash_flow_data.get('Financing', [0] * len(periods))
        
        # 转换为十亿
        operating = [v / 1e9 if v else 0 for v in operating]
        investing = [v / 1e9 if v else 0 for v in investing]
        financing = [v / 1e9 if v else 0 for v in financing]
        
        ax.bar(x - width, operating, width, label='Operating CF', 
              color=ChartColors.PRIMARY, edgecolor='white')
        ax.bar(x, investing, width, label='Investing CF', 
              color=ChartColors.ACCENT, edgecolor='white')
        ax.bar(x + width, financing, width, label='Financing CF', 
              color=ChartColors.MEDIUM_GRAY, edgecolor='white')
        
        # 净现金流线
        net_cf = [o + i + f for o, i, f in zip(operating, investing, financing)]
        ax.plot(x, net_cf, color='#4A7C59', marker='D', linewidth=2, 
               markersize=6, label='Net Cash Flow')
        
        ax.axhline(y=0, color='black', linestyle='-', linewidth=0.5)
        ax.set_xlabel('Period', fontsize=10)
        ax.set_ylabel('Cash Flow ($B)', fontsize=10)
        ax.set_title(f"{company_ticker} - Cash Flow Analysis", 
                    fontsize=12, fontweight='bold', pad=15)
        ax.set_xticks(x)
        ax.set_xticklabels(periods, rotation=45, ha='right')
        ax.legend(loc='best', framealpha=0.9, fontsize=9)
        ax.grid(True, axis='y', linestyle='--', alpha=0.5)
        
        fig.tight_layout()
        
        result = save_chart_to_base64(fig, output_path)
        print(f"✅ Cash flow chart saved to {output_path}")
        return result

    except Exception as e:
        print(f"❌ Error generating cash flow chart: {e}")
        import traceback
        traceback.print_exc()
        return None
