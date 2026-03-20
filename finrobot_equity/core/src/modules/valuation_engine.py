#!/usr/bin/env python
# coding: utf-8
"""
增强估值引擎模块
支持多种估值方法的综合分析
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class ValuationResult:
    """估值结果数据类"""
    method: str
    target_price: float
    low_estimate: float
    high_estimate: float
    assumptions: Dict = field(default_factory=dict)
    confidence: float = 0.5
    description: str = ""


class ValuationEngine:
    """增强估值引擎 - 支持多种估值方法"""
    
    def __init__(self, financial_data: Dict, peer_data: Dict = None):
        """
        初始化估值引擎
        
        Args:
            financial_data: 公司财务数据
            peer_data: 同行公司数据
        """
        self.financial_data = financial_data
        self.peer_data = peer_data or {}
        self.valuation_results: List[ValuationResult] = []
        self.current_price = financial_data.get('current_price', 0)
        self.shares_outstanding = financial_data.get('shares_outstanding', 1)
    
    def _get_metric(self, metric: str, year: str = None) -> Optional[float]:
        """获取财务指标"""
        try:
            if 'analysis' in self.financial_data:
                df = self.financial_data['analysis']
                row = df[df['metrics'] == metric]
                if not row.empty:
                    if year:
                        val = row[year].iloc[0]
                    else:
                        # 获取最新年份
                        years = [c for c in df.columns if c.endswith('A') or c.endswith('E')]
                        if years:
                            val = row[years[-1]].iloc[0]
                        else:
                            return None
                    if isinstance(val, str):
                        val = val.replace('%', '').replace(',', '')
                    return float(val)
            return None
        except:
            return None
    
    def calculate_ev_ebitda_valuation(self, target_multiple: float = None) -> ValuationResult:
        """
        计算EV/EBITDA估值
        
        Args:
            target_multiple: 目标倍数（默认使用历史平均）
        
        Returns:
            估值结果
        """
        logger.info("Calculating EV/EBITDA valuation...")
        
        # 获取EBITDA
        ebitda = self._get_metric('EBITDA')
        if not ebitda:
            ebitda = self.financial_data.get('ebitda', 0)
        
        # 获取历史EV/EBITDA倍数
        key_metrics = self.financial_data.get('key_metrics', pd.DataFrame())
        if not key_metrics.empty and 'enterpriseValueOverEBITDA' in key_metrics.columns:
            hist_multiples = key_metrics['enterpriseValueOverEBITDA'].dropna()
            avg_multiple = hist_multiples.mean()
            std_multiple = hist_multiples.std()
        else:
            avg_multiple = 12.0  # 默认倍数
            std_multiple = 3.0
        
        if target_multiple is None:
            target_multiple = avg_multiple
        
        # 计算企业价值
        ev = ebitda * target_multiple
        
        # 调整为股权价值（简化：假设净债务为EV的10%）
        net_debt = ev * 0.1
        equity_value = ev - net_debt
        
        # 计算每股价值
        if self.shares_outstanding > 0:
            target_price = equity_value / self.shares_outstanding
            low_price = (ebitda * (target_multiple - std_multiple) - net_debt) / self.shares_outstanding
            high_price = (ebitda * (target_multiple + std_multiple) - net_debt) / self.shares_outstanding
        else:
            target_price = low_price = high_price = 0
        
        result = ValuationResult(
            method='EV/EBITDA',
            target_price=max(target_price, 0),
            low_estimate=max(low_price, 0),
            high_estimate=max(high_price, 0),
            assumptions={
                'EBITDA': ebitda,
                'Target Multiple': target_multiple,
                'Historical Avg Multiple': avg_multiple
            },
            confidence=0.7,
            description=f"Based on {target_multiple:.1f}x EV/EBITDA multiple"
        )
        
        self.valuation_results.append(result)
        logger.info(f"✅ EV/EBITDA valuation: ${target_price:.2f}")
        return result
    
    def calculate_peer_comparison_valuation(self) -> ValuationResult:
        """
        计算同行比较估值
        
        Returns:
            估值结果
        """
        logger.info("Calculating peer comparison valuation...")
        
        if not self.peer_data:
            logger.warning("No peer data available")
            return ValuationResult(
                method='Peer Comparison',
                target_price=0,
                low_estimate=0,
                high_estimate=0,
                confidence=0
            )
        
        # 收集同行估值倍数
        peer_multiples = []
        for ticker, data in self.peer_data.items():
            if 'ev_ebitda' in data and data['ev_ebitda']:
                peer_multiples.append(data['ev_ebitda'])
        
        if not peer_multiples:
            return ValuationResult(
                method='Peer Comparison',
                target_price=0,
                low_estimate=0,
                high_estimate=0,
                confidence=0
            )
        
        # 计算同行平均和范围
        avg_multiple = np.mean(peer_multiples)
        min_multiple = np.min(peer_multiples)
        max_multiple = np.max(peer_multiples)
        
        # 获取公司EBITDA
        ebitda = self._get_metric('EBITDA') or self.financial_data.get('ebitda', 0)
        
        # 计算估值
        net_debt = ebitda * avg_multiple * 0.1  # 简化假设
        
        if self.shares_outstanding > 0:
            target_price = (ebitda * avg_multiple - net_debt) / self.shares_outstanding
            low_price = (ebitda * min_multiple - net_debt) / self.shares_outstanding
            high_price = (ebitda * max_multiple - net_debt) / self.shares_outstanding
        else:
            target_price = low_price = high_price = 0
        
        result = ValuationResult(
            method='Peer Comparison',
            target_price=max(target_price, 0),
            low_estimate=max(low_price, 0),
            high_estimate=max(high_price, 0),
            assumptions={
                'Peer Avg Multiple': avg_multiple,
                'Peer Range': f"{min_multiple:.1f}x - {max_multiple:.1f}x",
                'Number of Peers': len(peer_multiples)
            },
            confidence=0.6,
            description=f"Based on {len(peer_multiples)} peer companies"
        )
        
        self.valuation_results.append(result)
        logger.info(f"✅ Peer comparison valuation: ${target_price:.2f}")
        return result
    
    def calculate_dcf_valuation(self, assumptions: Dict = None) -> ValuationResult:
        """
        计算DCF估值（简化版）
        
        Args:
            assumptions: DCF假设参数
        
        Returns:
            估值结果
        """
        logger.info("Calculating DCF valuation...")
        
        # 默认假设
        default_assumptions = {
            'growth_rate_1_5': 0.10,  # 1-5年增长率
            'growth_rate_6_10': 0.05,  # 6-10年增长率
            'terminal_growth': 0.025,  # 永续增长率
            'wacc': 0.10,  # 加权平均资本成本
            'projection_years': 10
        }
        
        if assumptions:
            default_assumptions.update(assumptions)
        
        # 获取基础FCF
        fcf = self.financial_data.get('free_cash_flow', 0)
        if not fcf:
            ebitda = self._get_metric('EBITDA') or self.financial_data.get('ebitda', 0)
            fcf = ebitda * 0.6  # 简化假设：FCF = EBITDA * 60%
        
        # 计算预测期现金流现值
        pv_fcf = 0
        current_fcf = fcf
        wacc = default_assumptions['wacc']
        
        for year in range(1, default_assumptions['projection_years'] + 1):
            if year <= 5:
                growth = default_assumptions['growth_rate_1_5']
            else:
                growth = default_assumptions['growth_rate_6_10']
            
            current_fcf *= (1 + growth)
            pv_fcf += current_fcf / ((1 + wacc) ** year)
        
        # 计算终值
        terminal_value = current_fcf * (1 + default_assumptions['terminal_growth']) / \
                        (wacc - default_assumptions['terminal_growth'])
        pv_terminal = terminal_value / ((1 + wacc) ** default_assumptions['projection_years'])
        
        # 企业价值
        enterprise_value = pv_fcf + pv_terminal
        
        # 股权价值
        net_debt = enterprise_value * 0.1  # 简化假设
        equity_value = enterprise_value - net_debt
        
        # 每股价值
        if self.shares_outstanding > 0:
            target_price = equity_value / self.shares_outstanding
            # 敏感性范围（WACC ±1%）
            low_ev = pv_fcf + terminal_value / ((1 + wacc + 0.01) ** default_assumptions['projection_years'])
            high_ev = pv_fcf + terminal_value / ((1 + wacc - 0.01) ** default_assumptions['projection_years'])
            low_price = (low_ev - net_debt) / self.shares_outstanding
            high_price = (high_ev - net_debt) / self.shares_outstanding
        else:
            target_price = low_price = high_price = 0
        
        result = ValuationResult(
            method='DCF',
            target_price=max(target_price, 0),
            low_estimate=max(low_price, 0),
            high_estimate=max(high_price, 0),
            assumptions=default_assumptions,
            confidence=0.5,
            description=f"Based on {default_assumptions['wacc']*100:.1f}% WACC"
        )
        
        self.valuation_results.append(result)
        logger.info(f"✅ DCF valuation: ${target_price:.2f}")
        return result
    
    def generate_football_field_data(self) -> Dict[str, Dict]:
        """
        生成足球场图数据
        
        Returns:
            估值方法和区间字典
        """
        if not self.valuation_results:
            # 运行所有估值方法
            self.calculate_ev_ebitda_valuation()
            self.calculate_peer_comparison_valuation()
            self.calculate_dcf_valuation()
        
        football_data = {}
        for result in self.valuation_results:
            if result.target_price > 0:
                football_data[result.method] = {
                    'low': result.low_estimate,
                    'mid': result.target_price,
                    'high': result.high_estimate
                }
        
        # 添加当前价格
        if self.current_price > 0:
            football_data['current_price'] = self.current_price
        
        return football_data
    
    def synthesize_valuation(self) -> Dict:
        """
        综合多种估值方法得出结论
        
        Returns:
            综合估值结果
        """
        logger.info("Synthesizing valuation results...")
        
        if not self.valuation_results:
            self.calculate_ev_ebitda_valuation()
            self.calculate_peer_comparison_valuation()
            self.calculate_dcf_valuation()
        
        # 加权平均（按置信度加权）
        total_weight = sum(r.confidence for r in self.valuation_results if r.target_price > 0)
        
        if total_weight == 0:
            return {'target_price': 0, 'range': (0, 0), 'methods_used': 0}
        
        weighted_price = sum(r.target_price * r.confidence 
                           for r in self.valuation_results if r.target_price > 0) / total_weight
        
        all_lows = [r.low_estimate for r in self.valuation_results if r.low_estimate > 0]
        all_highs = [r.high_estimate for r in self.valuation_results if r.high_estimate > 0]
        
        synthesis = {
            'target_price': weighted_price,
            'range': (min(all_lows) if all_lows else 0, max(all_highs) if all_highs else 0),
            'methods_used': len([r for r in self.valuation_results if r.target_price > 0]),
            'current_price': self.current_price,
            'upside': ((weighted_price / self.current_price) - 1) * 100 if self.current_price > 0 else 0,
            'individual_results': [
                {
                    'method': r.method,
                    'target': r.target_price,
                    'range': (r.low_estimate, r.high_estimate),
                    'confidence': r.confidence
                }
                for r in self.valuation_results if r.target_price > 0
            ]
        }
        
        logger.info(f"✅ Synthesized target price: ${weighted_price:.2f} "
                   f"(Range: ${synthesis['range'][0]:.2f} - ${synthesis['range'][1]:.2f})")
        
        return synthesis
    
    def explain_valuation_differences(self) -> str:
        """
        解释不同估值方法的差异
        
        Returns:
            差异解释文本
        """
        if len(self.valuation_results) < 2:
            return "Insufficient valuation methods for comparison."
        
        prices = [(r.method, r.target_price) for r in self.valuation_results if r.target_price > 0]
        if len(prices) < 2:
            return "Insufficient valid valuations for comparison."
        
        prices.sort(key=lambda x: x[1])
        lowest = prices[0]
        highest = prices[-1]
        
        diff_pct = ((highest[1] - lowest[1]) / lowest[1]) * 100 if lowest[1] > 0 else 0
        
        explanation_parts = [
            f"## Valuation Method Comparison\n",
            f"The valuation analysis reveals a range of ${lowest[1]:.2f} to ${highest[1]:.2f}, "
            f"representing a {diff_pct:.1f}% spread between methods.\n",
            f"\n### Key Differences:\n",
            f"- **{lowest[0]}** provides the most conservative estimate at ${lowest[1]:.2f}",
            f"- **{highest[0]}** suggests the highest value at ${highest[1]:.2f}",
        ]
        
        # 添加方法特定说明
        for result in self.valuation_results:
            if result.target_price > 0:
                explanation_parts.append(f"\n**{result.method}**: {result.description}")
        
        # 综合建议
        synthesis = self.synthesize_valuation()
        explanation_parts.append(f"\n### Synthesis:")
        explanation_parts.append(f"Weighted average target price: ${synthesis['target_price']:.2f}")
        if synthesis['upside'] != 0:
            direction = "upside" if synthesis['upside'] > 0 else "downside"
            explanation_parts.append(f"Implied {direction}: {abs(synthesis['upside']):.1f}%")
        
        return "\n".join(explanation_parts)


def create_valuation_engine(financial_data: Dict, peer_data: Dict = None) -> ValuationEngine:
    """创建估值引擎实例"""
    return ValuationEngine(financial_data, peer_data)


if __name__ == "__main__":
    print("Valuation Engine Module")
    print("Supported Methods:")
    print("- EV/EBITDA Multiple")
    print("- Peer Comparison")
    print("- DCF (Simplified)")
    print("Features:")
    print("- Football field chart data")
    print("- Valuation synthesis")
    print("- Difference explanation")
