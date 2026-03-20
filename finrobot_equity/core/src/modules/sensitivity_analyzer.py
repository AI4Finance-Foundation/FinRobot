#!/usr/bin/env python
# coding: utf-8
"""
敏感性分析器模块
用于分析财务预测对关键假设变化的敏感性
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class SensitivityResult:
    """敏感性分析结果"""
    metric: str
    base_value: float
    low_value: float
    high_value: float
    sensitivity_range: Tuple[float, float]
    impact_percentage: float


class SensitivityAnalyzer:
    """敏感性分析器 - 分析预测对关键假设的敏感性"""
    
    def __init__(self, base_forecast: pd.DataFrame):
        """
        初始化敏感性分析器
        
        Args:
            base_forecast: 基准预测数据DataFrame
        """
        self.base_forecast = base_forecast.copy()
        self.sensitivity_results = {}
        self.confidence_intervals = {}
    
    def _get_metric_value(self, metric: str, year: str) -> Optional[float]:
        """获取指定指标和年份的值"""
        try:
            row = self.base_forecast[self.base_forecast['metrics'] == metric]
            if row.empty or year not in row.columns:
                return None
            value = row[year].iloc[0]
            if isinstance(value, str):
                value = value.replace('%', '').replace(',', '')
            return float(value)
        except:
            return None
    
    def _get_forecast_years(self) -> List[str]:
        """获取预测年份列（以E结尾）"""
        return [col for col in self.base_forecast.columns 
                if isinstance(col, str) and col.endswith('E')]
    
    def analyze_revenue_sensitivity(self, growth_range: Tuple[float, float] = (-0.05, 0.05),
                                   steps: int = 5) -> pd.DataFrame:
        """
        分析收入增长率敏感性
        
        Args:
            growth_range: 增长率变化范围 (如 -5% 到 +5%)
            steps: 分析步数
        
        Returns:
            敏感性分析表格
        """
        logger.info("Analyzing revenue growth sensitivity...")
        
        forecast_years = self._get_forecast_years()
        if not forecast_years:
            logger.warning("No forecast years found")
            return pd.DataFrame()
        
        # 获取基准收入
        base_revenues = {}
        for year in forecast_years:
            rev = self._get_metric_value('Revenue', year)
            if rev:
                base_revenues[year] = rev
        
        if not base_revenues:
            return pd.DataFrame()
        
        # 生成敏感性场景
        growth_deltas = np.linspace(growth_range[0], growth_range[1], steps)
        
        results = []
        for delta in growth_deltas:
            scenario = {'Growth Delta': f"{delta*100:+.1f}%"}
            for year in forecast_years:
                if year in base_revenues:
                    adjusted_rev = base_revenues[year] * (1 + delta)
                    scenario[year] = adjusted_rev
            results.append(scenario)
        
        df = pd.DataFrame(results)
        self.sensitivity_results['revenue_growth'] = df
        
        logger.info(f"✅ Revenue sensitivity analysis complete: {len(results)} scenarios")
        return df
    
    def analyze_margin_sensitivity(self, margin_range: Tuple[float, float] = (-0.02, 0.02),
                                  steps: int = 5) -> pd.DataFrame:
        """
        分析利润率敏感性
        
        Args:
            margin_range: 利润率变化范围 (如 -2% 到 +2%)
            steps: 分析步数
        
        Returns:
            敏感性分析表格
        """
        logger.info("Analyzing margin sensitivity...")
        
        forecast_years = self._get_forecast_years()
        if not forecast_years:
            return pd.DataFrame()
        
        # 获取基准EBITDA利润率
        base_margins = {}
        for year in forecast_years:
            margin = self._get_metric_value('EBITDA Margin', year)
            if margin:
                base_margins[year] = margin
        
        if not base_margins:
            return pd.DataFrame()
        
        # 生成敏感性场景
        margin_deltas = np.linspace(margin_range[0], margin_range[1], steps)
        
        results = []
        for delta in margin_deltas:
            scenario = {'Margin Delta': f"{delta*100:+.1f}%"}
            for year in forecast_years:
                if year in base_margins:
                    adjusted_margin = base_margins[year] + delta * 100  # 转换为百分比点
                    scenario[f'{year} EBITDA Margin'] = f"{adjusted_margin:.1f}%"
                    
                    # 计算对应的EBITDA
                    rev = self._get_metric_value('Revenue', year)
                    if rev:
                        adjusted_ebitda = rev * (adjusted_margin / 100)
                        scenario[f'{year} EBITDA'] = adjusted_ebitda
            results.append(scenario)
        
        df = pd.DataFrame(results)
        self.sensitivity_results['margin'] = df
        
        logger.info(f"✅ Margin sensitivity analysis complete: {len(results)} scenarios")
        return df
    
    def generate_sensitivity_table(self, revenue_range: Tuple[float, float] = (-0.05, 0.05),
                                   margin_range: Tuple[float, float] = (-0.02, 0.02),
                                   steps: int = 5) -> pd.DataFrame:
        """
        生成综合敏感性分析表格（二维矩阵）
        
        Args:
            revenue_range: 收入增长率变化范围
            margin_range: 利润率变化范围
            steps: 每个维度的步数
        
        Returns:
            二维敏感性矩阵
        """
        logger.info("Generating comprehensive sensitivity table...")
        
        forecast_years = self._get_forecast_years()
        if not forecast_years:
            return pd.DataFrame()
        
        target_year = forecast_years[-1]  # 使用最后一个预测年
        
        base_revenue = self._get_metric_value('Revenue', target_year)
        base_margin = self._get_metric_value('EBITDA Margin', target_year)
        
        if not base_revenue or not base_margin:
            logger.warning("Missing base revenue or margin data")
            return pd.DataFrame()
        
        # 生成变化范围
        rev_deltas = np.linspace(revenue_range[0], revenue_range[1], steps)
        margin_deltas = np.linspace(margin_range[0], margin_range[1], steps)
        
        # 创建二维矩阵
        matrix = []
        for rev_delta in rev_deltas:
            row = {'Revenue Growth': f"{rev_delta*100:+.1f}%"}
            adjusted_rev = base_revenue * (1 + rev_delta)
            
            for margin_delta in margin_deltas:
                adjusted_margin = base_margin + margin_delta * 100
                ebitda = adjusted_rev * (adjusted_margin / 100) / 1e9  # 转为十亿
                col_name = f"Margin {margin_delta*100:+.1f}%"
                row[col_name] = f"${ebitda:.1f}B"
            
            matrix.append(row)
        
        df = pd.DataFrame(matrix)
        df = df.set_index('Revenue Growth')
        
        self.sensitivity_results['combined'] = df
        logger.info(f"✅ Combined sensitivity table generated: {steps}x{steps} matrix")
        
        return df
    
    def calculate_confidence_interval(self, metric: str, confidence: float = 0.95) -> Tuple[float, float]:
        """
        计算预测的置信区间
        
        Args:
            metric: 指标名称
            confidence: 置信水平 (默认95%)
        
        Returns:
            (下限, 上限) 元组
        """
        logger.info(f"Calculating {confidence*100}% confidence interval for {metric}...")
        
        forecast_years = self._get_forecast_years()
        if not forecast_years:
            return (0, 0)
        
        target_year = forecast_years[-1]
        base_value = self._get_metric_value(metric, target_year)
        
        if not base_value:
            return (0, 0)
        
        # 基于历史波动率估算置信区间
        # 简化假设：使用固定的标准差比例
        std_ratio = 0.15  # 假设15%的标准差
        
        z_score = {0.90: 1.645, 0.95: 1.96, 0.99: 2.576}.get(confidence, 1.96)
        
        margin_of_error = base_value * std_ratio * z_score
        lower = base_value - margin_of_error
        upper = base_value + margin_of_error
        
        self.confidence_intervals[metric] = {
            'base': base_value,
            'lower': lower,
            'upper': upper,
            'confidence': confidence
        }
        
        logger.info(f"✅ {metric} CI: [{lower:.2f}, {upper:.2f}] at {confidence*100}% confidence")
        return (lower, upper)
    
    def get_forecast_assumptions(self) -> Dict[str, str]:
        """
        获取预测假设说明
        
        Returns:
            假设说明字典
        """
        assumptions = {}
        
        # 提取增长率假设
        forecast_years = self._get_forecast_years()
        for year in forecast_years:
            growth = self._get_metric_value('Revenue Growth', year)
            if growth:
                assumptions[f'{year} Revenue Growth'] = f"{growth:.1f}%"
            
            margin = self._get_metric_value('EBITDA Margin', year)
            if margin:
                assumptions[f'{year} EBITDA Margin'] = f"{margin:.1f}%"
        
        return assumptions
    
    def generate_sensitivity_summary(self) -> str:
        """
        生成敏感性分析摘要文本
        
        Returns:
            摘要文本
        """
        summary_parts = []
        
        summary_parts.append("## Sensitivity Analysis Summary\n")
        
        # 假设说明
        assumptions = self.get_forecast_assumptions()
        if assumptions:
            summary_parts.append("### Key Assumptions:")
            for key, value in assumptions.items():
                summary_parts.append(f"- {key}: {value}")
            summary_parts.append("")
        
        # 置信区间
        if self.confidence_intervals:
            summary_parts.append("### Confidence Intervals:")
            for metric, ci in self.confidence_intervals.items():
                summary_parts.append(
                    f"- {metric}: ${ci['lower']/1e9:.1f}B - ${ci['upper']/1e9:.1f}B "
                    f"({ci['confidence']*100:.0f}% confidence)"
                )
            summary_parts.append("")
        
        # 敏感性说明
        summary_parts.append("### Sensitivity Notes:")
        summary_parts.append("- Revenue growth sensitivity: ±5% change in growth rate")
        summary_parts.append("- Margin sensitivity: ±2% change in EBITDA margin")
        summary_parts.append("- Combined effects shown in sensitivity matrix")
        
        return "\n".join(summary_parts)


def create_sensitivity_analyzer(forecast_df: pd.DataFrame) -> SensitivityAnalyzer:
    """创建敏感性分析器实例"""
    return SensitivityAnalyzer(forecast_df)


if __name__ == "__main__":
    print("Sensitivity Analyzer Module")
    print("Features:")
    print("- Revenue growth sensitivity analysis")
    print("- Margin sensitivity analysis")
    print("- Combined sensitivity matrix")
    print("- Confidence interval calculation")
    print("- Forecast assumptions documentation")
