#!/usr/bin/env python
# coding: utf-8
"""
增强版股票研究报告图表生成器
集成11种专业图表类型，支持PNG和PDF双格式输出
"""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.dates as mdates
import numpy as np
import pandas as pd
import os
import re
import io
import base64
import logging
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Tuple, Any
from datetime import datetime

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


@dataclass
class ChartConfig:
    """图表配置数据类"""
    figsize: Tuple[int, int] = (14, 10)
    dpi: int = 300
    style: str = 'professional'
    color_scheme: str = 'corporate'
    font_family: str = 'Arial'
    title_fontsize: int = 16
    label_fontsize: int = 12
    tick_fontsize: int = 10
    output_formats: List[str] = field(default_factory=lambda: ['png', 'pdf'])


class ChartColors:
    """图表颜色规范"""
    PRIMARY = '#0B1B33'      # 深蓝 - 主要数据
    ACCENT = '#D2A74A'       # 金色 - 强调数据
    TEXT = '#333333'         # 文本颜色
    BACKGROUND = '#F5F5F5'   # 背景色
    GRID = '#E0E0E0'         # 网格线
    MEDIUM_GRAY = '#666666'  # 中灰
    SUCCESS = '#4A7C59'      # 绿色 - 正面
    WARNING = '#D2A74A'      # 金色 - 警告
    DANGER = '#8B4513'       # 棕色 - 负面
    
    SECONDARY_COLORS = [
        '#0B1B33', '#D2A74A', '#666666', '#4A7C59', 
        '#8B4513', '#2F4F4F', '#4169E1', '#DC143C'
    ]


class EnhancedChartGenerator:
    """增强版图表生成器 - 支持11种专业图表"""
    
    def __init__(self, config: ChartConfig = None):
        """初始化图表生成器"""
        self.config = config or ChartConfig()
        self._setup_matplotlib()
        self.generated_charts = {}
        self.errors = []
    
    def _setup_matplotlib(self):
        """设置matplotlib全局样式"""
        plt.rcParams.update({
            'font.family': 'sans-serif',
            'font.sans-serif': [self.config.font_family, 'Arial', 'Helvetica', 'DejaVu Sans'],
            'font.size': self.config.tick_fontsize,
            'axes.titlesize': self.config.title_fontsize,
            'axes.titleweight': 'bold',
            'axes.labelsize': self.config.label_fontsize,
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
            'xtick.labelsize': self.config.tick_fontsize,
            'ytick.labelsize': self.config.tick_fontsize,
            'legend.fontsize': self.config.tick_fontsize,
            'legend.framealpha': 0.9,
            'figure.facecolor': 'white',
            'figure.edgecolor': 'white',
            'savefig.facecolor': 'white',
            'savefig.edgecolor': 'white',
            'savefig.dpi': self.config.dpi,
        })
    
    def _save_chart(self, fig: plt.Figure, output_dir: str, filename: str) -> Dict[str, str]:
        """保存图表为多种格式"""
        os.makedirs(output_dir, exist_ok=True)
        saved_paths = {}
        
        for fmt in self.config.output_formats:
            filepath = os.path.join(output_dir, f"{filename}.{fmt}")
            try:
                fig.savefig(filepath, format=fmt, bbox_inches='tight', 
                           dpi=self.config.dpi, facecolor='white', edgecolor='none')
                saved_paths[fmt] = filepath
                logger.info(f"✅ Chart saved: {filepath}")
            except Exception as e:
                logger.error(f"❌ Failed to save {fmt}: {e}")
                self.errors.append(f"Save {filename}.{fmt}: {e}")
        
        plt.close(fig)
        return saved_paths
    
    def _get_year_columns(self, df: pd.DataFrame) -> List[str]:
        """获取年份列（如2024A, 2025E）"""
        year_pattern = re.compile(r'^\d{4}[AE]$')
        years = [col for col in df.columns if year_pattern.match(str(col))]
        return sorted(years, key=lambda x: (int(x[:4]), x[-1]))
    
    def _parse_percentage(self, value) -> float:
        """解析百分比值"""
        if pd.isna(value):
            return np.nan
        if isinstance(value, str):
            value = value.replace('%', '').strip()
            try:
                return float(value)
            except:
                return np.nan
        return float(value) if value < 1 else float(value)

    # =========================================================================
    # 图表1: 收入YoY增长图表
    # =========================================================================
    def generate_revenue_yoy_chart(self, income_df: pd.DataFrame, ticker: str, 
                                   output_dir: str) -> Optional[Dict[str, str]]:
        """
        生成收入YoY增长图表
        包含季度收入柱状图和同比增长率趋势线
        """
        try:
            if income_df.empty:
                logger.warning(f"No income data for {ticker}")
                return None
            
            df = income_df.sort_values('date').copy()
            df['RevenueBn'] = df['revenue'] / 1e9
            df['YoY'] = df['RevenueBn'].pct_change(4) * 100  # 同比增长
            
            fig, ax1 = plt.subplots(figsize=self.config.figsize)
            
            # 收入柱状图
            bars = ax1.bar(df['date'], df['RevenueBn'], color=ChartColors.PRIMARY, 
                          alpha=0.85, label='Revenue ($B)', edgecolor='white', linewidth=0.5)
            ax1.set_ylabel('Revenue ($B)', fontweight='bold', color=ChartColors.PRIMARY)
            ax1.tick_params(axis='y', labelcolor=ChartColors.PRIMARY)
            
            # YoY增长率折线图
            ax2 = ax1.twinx()
            ax2.plot(df['date'], df['YoY'], color=ChartColors.ACCENT, linewidth=2.5, 
                    marker='o', markersize=6, label='YoY Growth (%)')
            ax2.set_ylabel('YoY Growth (%)', fontweight='bold', color=ChartColors.ACCENT)
            ax2.tick_params(axis='y', labelcolor=ChartColors.ACCENT)
            ax2.axhline(y=0, color='black', linestyle='--', alpha=0.5)
            
            ax1.set_title(f'{ticker} Revenue Growth Analysis', fontweight='bold', pad=20)
            ax1.set_xlabel('Quarter', fontweight='bold')
            ax1.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
            ax1.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
            plt.setp(ax1.get_xticklabels(), rotation=45, ha='right')
            
            # 图例
            lines1, labels1 = ax1.get_legend_handles_labels()
            lines2, labels2 = ax2.get_legend_handles_labels()
            ax1.legend(lines1 + lines2, labels1 + labels2, loc='upper left')
            
            ax1.grid(True, axis='y', linestyle='--', alpha=0.5)
            fig.tight_layout()
            
            return self._save_chart(fig, output_dir, f'{ticker}_revenue_yoy')
            
        except Exception as e:
            logger.error(f"❌ Error generating revenue YoY chart: {e}")
            self.errors.append(f"revenue_yoy: {e}")
            return None
    
    # =========================================================================
    # 图表2: EBITDA利润率图表
    # =========================================================================
    def generate_ebitda_margin_chart(self, income_df: pd.DataFrame, ticker: str,
                                     output_dir: str) -> Optional[Dict[str, str]]:
        """
        生成EBITDA利润率图表
        包含EBITDA金额和利润率双轴展示
        """
        try:
            if income_df.empty:
                logger.warning(f"No income data for {ticker}")
                return None
            
            df = income_df.sort_values('date').copy()
            df['EBITDABn'] = df['ebitda'] / 1e9
            df['EBITDA_Margin'] = (df['ebitda'] / df['revenue']) * 100
            
            fig, ax1 = plt.subplots(figsize=self.config.figsize)
            
            # EBITDA柱状图
            bars = ax1.bar(df['date'], df['EBITDABn'], color=ChartColors.PRIMARY,
                          alpha=0.85, label='EBITDA ($B)', edgecolor='white')
            ax1.set_ylabel('EBITDA ($B)', fontweight='bold', color=ChartColors.PRIMARY)
            ax1.tick_params(axis='y', labelcolor=ChartColors.PRIMARY)
            
            # EBITDA利润率折线图
            ax2 = ax1.twinx()
            ax2.plot(df['date'], df['EBITDA_Margin'], color=ChartColors.ACCENT,
                    linewidth=2.5, marker='o', markersize=6, label='EBITDA Margin (%)')
            ax2.set_ylabel('EBITDA Margin (%)', fontweight='bold', color=ChartColors.ACCENT)
            ax2.tick_params(axis='y', labelcolor=ChartColors.ACCENT)
            
            ax1.set_title(f'{ticker} EBITDA & Margin Analysis', fontweight='bold', pad=20)
            ax1.set_xlabel('Quarter', fontweight='bold')
            ax1.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
            plt.setp(ax1.get_xticklabels(), rotation=45, ha='right')
            
            lines1, labels1 = ax1.get_legend_handles_labels()
            lines2, labels2 = ax2.get_legend_handles_labels()
            ax1.legend(lines1 + lines2, labels1 + labels2, loc='upper left')
            
            ax1.grid(True, axis='y', linestyle='--', alpha=0.5)
            fig.tight_layout()
            
            return self._save_chart(fig, output_dir, f'{ticker}_ebitda_margin')
            
        except Exception as e:
            logger.error(f"❌ Error generating EBITDA margin chart: {e}")
            self.errors.append(f"ebitda_margin: {e}")
            return None
    
    # =========================================================================
    # 图表3: 毛利率趋势图表
    # =========================================================================
    def generate_gross_margin_chart(self, income_df: pd.DataFrame, ticker: str,
                                    output_dir: str) -> Optional[Dict[str, str]]:
        """生成毛利率趋势图表"""
        try:
            if income_df.empty:
                return None
            
            df = income_df.sort_values('date').copy()
            df['GrossMargin'] = (df['grossProfit'] / df['revenue']) * 100
            
            fig, ax = plt.subplots(figsize=self.config.figsize)
            
            ax.bar(df['date'], df['GrossMargin'], color=ChartColors.SUCCESS,
                  alpha=0.85, edgecolor='white')
            
            # 添加平均线
            avg_margin = df['GrossMargin'].mean()
            ax.axhline(y=avg_margin, color=ChartColors.ACCENT, linestyle='--',
                      linewidth=2, label=f'Average: {avg_margin:.1f}%')
            
            ax.set_title(f'{ticker} Gross Margin Trend', fontweight='bold', pad=20)
            ax.set_ylabel('Gross Margin (%)', fontweight='bold')
            ax.set_xlabel('Quarter', fontweight='bold')
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
            plt.setp(ax.get_xticklabels(), rotation=45, ha='right')
            ax.legend(loc='upper right')
            ax.grid(True, axis='y', linestyle='--', alpha=0.5)
            
            fig.tight_layout()
            return self._save_chart(fig, output_dir, f'{ticker}_gross_margin')
            
        except Exception as e:
            logger.error(f"❌ Error generating gross margin chart: {e}")
            self.errors.append(f"gross_margin: {e}")
            return None
    
    # =========================================================================
    # 图表4: SG&A费用比率图表
    # =========================================================================
    def generate_sga_ratio_chart(self, income_df: pd.DataFrame, ticker: str,
                                 output_dir: str) -> Optional[Dict[str, str]]:
        """生成SG&A费用比率图表"""
        try:
            if income_df.empty or 'sellingGeneralAndAdministrativeExpenses' not in income_df.columns:
                logger.warning(f"Missing SG&A data for {ticker}")
                return None
            
            df = income_df.sort_values('date').copy()
            df['SGA_Ratio'] = (df['sellingGeneralAndAdministrativeExpenses'] / df['revenue']) * 100
            
            fig, ax = plt.subplots(figsize=self.config.figsize)
            
            ax.bar(df['date'], df['SGA_Ratio'], color=ChartColors.MEDIUM_GRAY,
                  alpha=0.85, edgecolor='white')
            
            avg_ratio = df['SGA_Ratio'].mean()
            ax.axhline(y=avg_ratio, color=ChartColors.ACCENT, linestyle='--',
                      linewidth=2, label=f'Average: {avg_ratio:.1f}%')
            
            ax.set_title(f'{ticker} SG&A as % of Revenue', fontweight='bold', pad=20)
            ax.set_ylabel('SG&A / Revenue (%)', fontweight='bold')
            ax.set_xlabel('Quarter', fontweight='bold')
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
            plt.setp(ax.get_xticklabels(), rotation=45, ha='right')
            ax.legend(loc='upper right')
            ax.grid(True, axis='y', linestyle='--', alpha=0.5)
            
            fig.tight_layout()
            return self._save_chart(fig, output_dir, f'{ticker}_sga_ratio')
            
        except Exception as e:
            logger.error(f"❌ Error generating SG&A ratio chart: {e}")
            self.errors.append(f"sga_ratio: {e}")
            return None

    # =========================================================================
    # 图表5: LTM EBITDA利润率图表
    # =========================================================================
    def generate_ltm_ebitda_margin_chart(self, income_df: pd.DataFrame, ticker: str,
                                         output_dir: str) -> Optional[Dict[str, str]]:
        """生成LTM EBITDA利润率图表（滚动12个月）"""
        try:
            if income_df.empty:
                return None
            
            df = income_df.sort_values('date').copy()
            df['EBITDA_LTM'] = df['ebitda'].rolling(4).sum()
            df['Revenue_LTM'] = df['revenue'].rolling(4).sum()
            df['LTM_EBITDA_Margin'] = (df['EBITDA_LTM'] / df['Revenue_LTM']) * 100
            
            fig, ax = plt.subplots(figsize=self.config.figsize)
            
            ax.plot(df['date'], df['LTM_EBITDA_Margin'], color=ChartColors.PRIMARY,
                   linewidth=2.5, marker='o', markersize=5)
            ax.fill_between(df['date'], df['LTM_EBITDA_Margin'], alpha=0.3, 
                           color=ChartColors.PRIMARY)
            
            ax.set_title(f'{ticker} LTM EBITDA Margin Trend', fontweight='bold', pad=20)
            ax.set_ylabel('LTM EBITDA Margin (%)', fontweight='bold')
            ax.set_xlabel('Quarter', fontweight='bold')
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
            plt.setp(ax.get_xticklabels(), rotation=45, ha='right')
            ax.grid(True, linestyle='--', alpha=0.5)
            
            fig.tight_layout()
            return self._save_chart(fig, output_dir, f'{ticker}_ltm_ebitda_margin')
            
        except Exception as e:
            logger.error(f"❌ Error generating LTM EBITDA margin chart: {e}")
            self.errors.append(f"ltm_ebitda_margin: {e}")
            return None
    
    # =========================================================================
    # 图表6: 相对表现图表
    # =========================================================================
    def generate_relative_performance_chart(self, prices_df: pd.DataFrame, 
                                            benchmark_df: pd.DataFrame,
                                            ticker: str, benchmark: str,
                                            output_dir: str) -> Optional[Dict[str, str]]:
        """生成相对表现图表（对比基准指数）"""
        try:
            if prices_df.empty or benchmark_df.empty:
                logger.warning(f"Missing price data for relative performance")
                return None
            
            # 对齐日期
            p1 = prices_df.set_index('date')['close']
            p2 = benchmark_df.set_index('date')['close']
            
            common_dates = p1.index.intersection(p2.index)
            if len(common_dates) < 10:
                logger.warning("Not enough common dates for relative performance")
                return None
            
            p1 = p1.loc[common_dates]
            p2 = p2.loc[common_dates]
            
            # 计算相对收益
            rel_return = (p1 / p1.iloc[0]) / (p2 / p2.iloc[0]) - 1.0
            
            fig, ax = plt.subplots(figsize=self.config.figsize)
            
            ax.plot(rel_return.index, rel_return.values * 100, color=ChartColors.PRIMARY,
                   linewidth=2)
            ax.fill_between(rel_return.index, rel_return.values * 100, 0, 
                           where=(rel_return.values >= 0), alpha=0.3, color=ChartColors.SUCCESS)
            ax.fill_between(rel_return.index, rel_return.values * 100, 0,
                           where=(rel_return.values < 0), alpha=0.3, color=ChartColors.DANGER)
            ax.axhline(y=0, color='black', linestyle='-', linewidth=1)
            
            ax.set_title(f'{ticker} vs {benchmark} Relative Performance', 
                        fontweight='bold', pad=20)
            ax.set_ylabel(f'Relative to {benchmark} (%)', fontweight='bold')
            ax.set_xlabel('Date', fontweight='bold')
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
            plt.setp(ax.get_xticklabels(), rotation=45, ha='right')
            ax.grid(True, linestyle='--', alpha=0.5)
            
            fig.tight_layout()
            return self._save_chart(fig, output_dir, f'{ticker}_relative_perf')
            
        except Exception as e:
            logger.error(f"❌ Error generating relative performance chart: {e}")
            self.errors.append(f"relative_performance: {e}")
            return None
    
    # =========================================================================
    # 图表7: EV/EBITDA估值区间图表
    # =========================================================================
    def generate_ev_ebitda_band_chart(self, key_metrics_df: pd.DataFrame, ticker: str,
                                      output_dir: str) -> Optional[Dict[str, str]]:
        """生成EV/EBITDA估值区间图表（含均值和标准差）"""
        try:
            if key_metrics_df.empty or 'enterpriseValueOverEBITDA' not in key_metrics_df.columns:
                logger.warning(f"Missing EV/EBITDA data for {ticker}")
                return None
            
            df = key_metrics_df.sort_values('date').copy()
            ratio = df['enterpriseValueOverEBITDA']
            
            mu = ratio.mean()
            sd = ratio.std()
            
            fig, ax = plt.subplots(figsize=self.config.figsize)
            
            ax.plot(df['date'], ratio, color=ChartColors.PRIMARY, linewidth=2,
                   marker='o', markersize=4, label='EV/EBITDA')
            ax.axhline(y=mu, color=ChartColors.ACCENT, linestyle='--', linewidth=2,
                      label=f'Mean: {mu:.1f}x')
            ax.axhline(y=mu+sd, color=ChartColors.MEDIUM_GRAY, linestyle=':', linewidth=1.5,
                      label=f'+1 Std: {mu+sd:.1f}x')
            ax.axhline(y=mu-sd, color=ChartColors.MEDIUM_GRAY, linestyle=':', linewidth=1.5,
                      label=f'-1 Std: {mu-sd:.1f}x')
            
            ax.fill_between(df['date'], mu-sd, mu+sd, alpha=0.2, color=ChartColors.PRIMARY)
            
            ax.set_title(f'{ticker} EV/EBITDA Valuation Band', fontweight='bold', pad=20)
            ax.set_ylabel('EV/EBITDA (x)', fontweight='bold')
            ax.set_xlabel('Date', fontweight='bold')
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
            plt.setp(ax.get_xticklabels(), rotation=45, ha='right')
            ax.legend(loc='upper right')
            ax.grid(True, linestyle='--', alpha=0.5)
            
            fig.tight_layout()
            return self._save_chart(fig, output_dir, f'{ticker}_ev_ebitda_band')
            
        except Exception as e:
            logger.error(f"❌ Error generating EV/EBITDA band chart: {e}")
            self.errors.append(f"ev_ebitda_band: {e}")
            return None
    
    # =========================================================================
    # 图表8: P/FCF估值区间图表
    # =========================================================================
    def generate_p_fcf_band_chart(self, key_metrics_df: pd.DataFrame, ticker: str,
                                  output_dir: str) -> Optional[Dict[str, str]]:
        """生成P/FCF估值区间图表（含均值和标准差）"""
        try:
            if key_metrics_df.empty or 'priceToFreeCashFlowsRatio' not in key_metrics_df.columns:
                logger.warning(f"Missing P/FCF data for {ticker}")
                return None
            
            df = key_metrics_df.sort_values('date').copy()
            ratio = df['priceToFreeCashFlowsRatio']
            
            mu = ratio.mean()
            sd = ratio.std()
            
            fig, ax = plt.subplots(figsize=self.config.figsize)
            
            ax.plot(df['date'], ratio, color=ChartColors.PRIMARY, linewidth=2,
                   marker='o', markersize=4, label='P/FCF')
            ax.axhline(y=mu, color=ChartColors.ACCENT, linestyle='--', linewidth=2,
                      label=f'Mean: {mu:.1f}x')
            ax.axhline(y=mu+sd, color=ChartColors.MEDIUM_GRAY, linestyle=':', linewidth=1.5,
                      label=f'+1 Std: {mu+sd:.1f}x')
            ax.axhline(y=mu-sd, color=ChartColors.MEDIUM_GRAY, linestyle=':', linewidth=1.5,
                      label=f'-1 Std: {mu-sd:.1f}x')
            
            ax.fill_between(df['date'], mu-sd, mu+sd, alpha=0.2, color=ChartColors.PRIMARY)
            
            ax.set_title(f'{ticker} P/FCF Valuation Band', fontweight='bold', pad=20)
            ax.set_ylabel('P/FCF (x)', fontweight='bold')
            ax.set_xlabel('Date', fontweight='bold')
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
            plt.setp(ax.get_xticklabels(), rotation=45, ha='right')
            ax.legend(loc='upper right')
            ax.grid(True, linestyle='--', alpha=0.5)
            
            fig.tight_layout()
            return self._save_chart(fig, output_dir, f'{ticker}_p_fcf_band')
            
        except Exception as e:
            logger.error(f"❌ Error generating P/FCF band chart: {e}")
            self.errors.append(f"p_fcf_band: {e}")
            return None

    # =========================================================================
    # 图表9: 同行比较图表
    # =========================================================================
    def generate_peer_comparison_chart(self, peer_data: Dict[str, Dict], ticker: str,
                                       output_dir: str) -> Optional[Dict[str, str]]:
        """
        生成同行比较图表
        对比收入、EBITDA和毛利率
        """
        try:
            if not peer_data:
                logger.warning("No peer data for comparison")
                return None
            
            # 准备数据
            tickers = list(peer_data.keys())
            revenues = [peer_data[t].get('revenue', 0) / 1e9 for t in tickers]
            ebitdas = [peer_data[t].get('ebitda', 0) / 1e9 for t in tickers]
            gross_margins = [peer_data[t].get('gross_margin', 0) for t in tickers]
            
            # 按收入排序
            sorted_indices = np.argsort(revenues)[::-1]
            tickers = [tickers[i] for i in sorted_indices]
            revenues = [revenues[i] for i in sorted_indices]
            ebitdas = [ebitdas[i] for i in sorted_indices]
            gross_margins = [gross_margins[i] for i in sorted_indices]
            
            fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(self.config.figsize[0], self.config.figsize[1] * 0.7))
            
            # 左图: 收入和EBITDA对比
            x = np.arange(len(tickers))
            width = 0.35
            
            colors_rev = [ChartColors.PRIMARY if t == ticker else ChartColors.MEDIUM_GRAY for t in tickers]
            colors_ebitda = [ChartColors.ACCENT if t == ticker else '#B8B8B8' for t in tickers]
            
            bars1 = ax1.bar(x - width/2, revenues, width, color=colors_rev, label='Revenue ($B)')
            bars2 = ax1.bar(x + width/2, ebitdas, width, color=colors_ebitda, label='EBITDA ($B)')
            
            ax1.set_ylabel('$B', fontweight='bold')
            ax1.set_title('Revenue & EBITDA Comparison', fontweight='bold')
            ax1.set_xticks(x)
            ax1.set_xticklabels(tickers, rotation=45, ha='right')
            ax1.legend(loc='upper right')
            ax1.grid(True, axis='y', linestyle='--', alpha=0.5)
            
            # 右图: 毛利率对比
            colors_gm = [ChartColors.SUCCESS if t == ticker else ChartColors.MEDIUM_GRAY for t in tickers]
            bars3 = ax2.barh(tickers, gross_margins, color=colors_gm)
            
            ax2.set_xlabel('Gross Margin (%)', fontweight='bold')
            ax2.set_title('Gross Margin Comparison', fontweight='bold')
            ax2.grid(True, axis='x', linestyle='--', alpha=0.5)
            
            # 添加数值标签
            for bar, val in zip(bars3, gross_margins):
                ax2.text(bar.get_width() + 0.5, bar.get_y() + bar.get_height()/2,
                        f'{val:.1f}%', va='center', fontsize=9)
            
            fig.suptitle(f'{ticker} Peer Comparison', fontweight='bold', fontsize=14, y=1.02)
            fig.tight_layout()
            
            return self._save_chart(fig, output_dir, f'{ticker}_peer_comparison')
            
        except Exception as e:
            logger.error(f"❌ Error generating peer comparison chart: {e}")
            self.errors.append(f"peer_comparison: {e}")
            return None
    
    # =========================================================================
    # 图表10: 估值足球场图
    # =========================================================================
    def generate_football_field_chart(self, valuation_data: Dict[str, Dict], ticker: str,
                                      output_dir: str) -> Optional[Dict[str, str]]:
        """
        生成估值足球场图
        展示不同估值方法得出的估值区间
        """
        try:
            if not valuation_data:
                logger.warning("No valuation data for football field chart")
                return None
            
            methods = list(valuation_data.keys())
            lows = [valuation_data[m].get('low', 0) for m in methods]
            mids = [valuation_data[m].get('mid', 0) for m in methods]
            highs = [valuation_data[m].get('high', 0) for m in methods]
            
            # 按中值排序
            sorted_indices = np.argsort(mids)
            methods = [methods[i] for i in sorted_indices]
            lows = [lows[i] for i in sorted_indices]
            mids = [mids[i] for i in sorted_indices]
            highs = [highs[i] for i in sorted_indices]
            
            fig, ax = plt.subplots(figsize=self.config.figsize)
            
            y = np.arange(len(methods))
            
            # 绘制区间条
            for i, (method, low, mid, high) in enumerate(zip(methods, lows, mids, highs)):
                ax.plot([low, high], [i, i], linewidth=12, color=ChartColors.PRIMARY, 
                       alpha=0.6, solid_capstyle='round')
                ax.plot(mid, i, 'o', markersize=12, color=ChartColors.ACCENT, 
                       markeredgecolor='white', markeredgewidth=2)
                
                # 添加数值标签
                ax.text(low - 2, i, f'${low:.0f}', va='center', ha='right', fontsize=9)
                ax.text(high + 2, i, f'${high:.0f}', va='center', ha='left', fontsize=9)
            
            ax.set_yticks(y)
            ax.set_yticklabels(methods)
            ax.set_xlabel('Target Price ($)', fontweight='bold')
            ax.set_title(f'{ticker} Valuation Football Field', fontweight='bold', pad=20)
            ax.grid(True, axis='x', linestyle='--', alpha=0.5)
            
            # 添加当前价格线（如果有）
            if 'current_price' in valuation_data:
                current = valuation_data['current_price']
                ax.axvline(x=current, color=ChartColors.DANGER, linestyle='--', 
                          linewidth=2, label=f'Current: ${current:.0f}')
                ax.legend(loc='upper right')
            
            fig.tight_layout()
            return self._save_chart(fig, output_dir, f'{ticker}_football_field')
            
        except Exception as e:
            logger.error(f"❌ Error generating football field chart: {e}")
            self.errors.append(f"football_field: {e}")
            return None
    
    # =========================================================================
    # 图表11: EPS × PE趋势图
    # =========================================================================
    def generate_eps_pe_chart(self, analysis_df: pd.DataFrame, ticker: str,
                              output_dir: str) -> Optional[Dict[str, str]]:
        """生成EPS × PE双折线趋势图"""
        try:
            if analysis_df.empty or 'metrics' not in analysis_df.columns:
                return None
            
            years = self._get_year_columns(analysis_df)
            if not years:
                return None
            
            eps_row = analysis_df[analysis_df['metrics'] == 'EPS']
            pe_row = analysis_df[analysis_df['metrics'] == 'PE Ratio']
            
            if eps_row.empty or pe_row.empty:
                logger.warning("EPS or PE Ratio data not found")
                return None
            
            eps_data = pd.to_numeric(eps_row[years].iloc[0], errors='coerce')
            pe_data = pd.to_numeric(pe_row[years].iloc[0], errors='coerce')
            
            fig, ax1 = plt.subplots(figsize=self.config.figsize)
            
            x = np.arange(len(years))
            
            # EPS折线
            ax1.plot(x, eps_data, color=ChartColors.PRIMARY, marker='o',
                    markersize=8, linewidth=2.5, label='EPS ($)')
            ax1.set_ylabel('EPS ($)', fontweight='bold', color=ChartColors.PRIMARY)
            ax1.tick_params(axis='y', labelcolor=ChartColors.PRIMARY)
            
            # PE折线
            ax2 = ax1.twinx()
            ax2.plot(x, pe_data, color=ChartColors.ACCENT, marker='s',
                    markersize=8, linewidth=2.5, linestyle='--', label='PE Ratio (x)')
            ax2.set_ylabel('PE Ratio (x)', fontweight='bold', color=ChartColors.ACCENT)
            ax2.tick_params(axis='y', labelcolor=ChartColors.ACCENT)
            
            ax1.set_xticks(x)
            ax1.set_xticklabels(years, rotation=45, ha='right')
            ax1.set_xlabel('Year', fontweight='bold')
            ax1.set_title(f'{ticker} EPS × PE Trend Analysis', fontweight='bold', pad=20)
            
            lines1, labels1 = ax1.get_legend_handles_labels()
            lines2, labels2 = ax2.get_legend_handles_labels()
            ax1.legend(lines1 + lines2, labels1 + labels2, loc='upper left')
            
            ax1.grid(True, axis='y', linestyle='--', alpha=0.5)
            fig.tight_layout()
            
            return self._save_chart(fig, output_dir, f'{ticker}_eps_pe')
            
        except Exception as e:
            logger.error(f"❌ Error generating EPS × PE chart: {e}")
            self.errors.append(f"eps_pe: {e}")
            return None
    
    # =========================================================================
    # 主入口: 生成所有图表
    # =========================================================================
    def generate_all_charts(self, financial_data: Dict[str, Any], ticker: str,
                           output_dir: str, benchmark: str = 'SPY') -> Dict[str, Dict]:
        """
        生成所有11种图表
        
        Args:
            financial_data: 包含所有财务数据的字典
            ticker: 股票代码
            output_dir: 输出目录
            benchmark: 基准指数代码
        
        Returns:
            图表路径字典
        """
        logger.info(f"🚀 Starting chart generation for {ticker}")
        self.generated_charts = {}
        self.errors = []
        
        os.makedirs(output_dir, exist_ok=True)
        
        # 提取数据
        income_df = financial_data.get('income_statement', pd.DataFrame())
        key_metrics_df = financial_data.get('key_metrics', pd.DataFrame())
        prices_df = financial_data.get('prices', pd.DataFrame())
        benchmark_df = financial_data.get('benchmark_prices', pd.DataFrame())
        analysis_df = financial_data.get('analysis', pd.DataFrame())
        peer_data = financial_data.get('peer_data', {})
        valuation_data = financial_data.get('valuation_data', {})
        
        # 生成各图表（错误不中断流程）
        chart_methods = [
            ('revenue_yoy', lambda: self.generate_revenue_yoy_chart(income_df, ticker, output_dir)),
            ('ebitda_margin', lambda: self.generate_ebitda_margin_chart(income_df, ticker, output_dir)),
            ('gross_margin', lambda: self.generate_gross_margin_chart(income_df, ticker, output_dir)),
            ('sga_ratio', lambda: self.generate_sga_ratio_chart(income_df, ticker, output_dir)),
            ('ltm_ebitda_margin', lambda: self.generate_ltm_ebitda_margin_chart(income_df, ticker, output_dir)),
            ('relative_performance', lambda: self.generate_relative_performance_chart(prices_df, benchmark_df, ticker, benchmark, output_dir)),
            ('ev_ebitda_band', lambda: self.generate_ev_ebitda_band_chart(key_metrics_df, ticker, output_dir)),
            ('p_fcf_band', lambda: self.generate_p_fcf_band_chart(key_metrics_df, ticker, output_dir)),
            ('peer_comparison', lambda: self.generate_peer_comparison_chart(peer_data, ticker, output_dir)),
            ('football_field', lambda: self.generate_football_field_chart(valuation_data, ticker, output_dir)),
            ('eps_pe', lambda: self.generate_eps_pe_chart(analysis_df, ticker, output_dir)),
        ]
        
        for chart_name, generate_func in chart_methods:
            try:
                result = generate_func()
                if result:
                    self.generated_charts[chart_name] = result
                    logger.info(f"✅ Generated: {chart_name}")
                else:
                    logger.warning(f"⚠️ Skipped: {chart_name} (no data)")
            except Exception as e:
                logger.error(f"❌ Failed: {chart_name} - {e}")
                self.errors.append(f"{chart_name}: {e}")
        
        # 汇总结果
        logger.info(f"📊 Chart generation complete: {len(self.generated_charts)}/11 charts generated")
        if self.errors:
            logger.warning(f"⚠️ Errors encountered: {len(self.errors)}")
            for err in self.errors:
                logger.warning(f"   - {err}")
        
        return self.generated_charts


# =============================================================================
# 便捷函数
# =============================================================================
def create_enhanced_chart_generator(config: ChartConfig = None) -> EnhancedChartGenerator:
    """创建增强图表生成器实例"""
    return EnhancedChartGenerator(config)


if __name__ == "__main__":
    # 测试代码
    print("Enhanced Chart Generator Module")
    print("Supports 11 professional chart types:")
    print("1. Revenue YoY Growth")
    print("2. EBITDA Margin")
    print("3. Gross Margin Trend")
    print("4. SG&A Ratio")
    print("5. LTM EBITDA Margin")
    print("6. Relative Performance")
    print("7. EV/EBITDA Valuation Band")
    print("8. P/FCF Valuation Band")
    print("9. Peer Comparison")
    print("10. Football Field Valuation")
    print("11. EPS × PE Trend")
