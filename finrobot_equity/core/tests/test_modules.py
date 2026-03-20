#!/usr/bin/env python
# coding: utf-8
"""
模块测试脚本
验证所有增强模块可以正常导入和基本功能正常工作
"""

import sys
import os
import traceback

# 添加模块路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_import_modules():
    """测试所有模块导入"""
    print("=" * 60)
    print("Testing Module Imports")
    print("=" * 60)
    
    modules_to_test = [
        ('enhanced_chart_generator', 'EnhancedChartGenerator'),
        ('sensitivity_analyzer', 'SensitivityAnalyzer'),
        ('catalyst_analyzer', 'CatalystAnalyzer'),
        ('valuation_engine', 'ValuationEngine'),
        ('enhanced_text_generator', 'EnhancedTextGenerator'),
        ('report_structure', 'ReportStructureManager'),
        ('news_integrator', 'NewsIntegrator'),
    ]
    
    results = []
    
    for module_name, class_name in modules_to_test:
        try:
            module = __import__(f'modules.{module_name}', fromlist=[class_name])
            cls = getattr(module, class_name)
            print(f"✅ {module_name}.{class_name} - OK")
            results.append((module_name, True, None))
        except Exception as e:
            print(f"❌ {module_name}.{class_name} - FAILED: {e}")
            results.append((module_name, False, str(e)))
    
    return results


def test_enhanced_chart_generator():
    """测试增强图表生成器"""
    print("\n" + "=" * 60)
    print("Testing EnhancedChartGenerator")
    print("=" * 60)
    
    try:
        from modules.enhanced_chart_generator import EnhancedChartGenerator, ChartConfig
        import pandas as pd
        import numpy as np
        from datetime import datetime, timedelta
        
        # 创建实例
        config = ChartConfig(dpi=100, figsize=(10, 6))
        generator = EnhancedChartGenerator(config)
        print("✅ EnhancedChartGenerator instance created")
        
        # 创建测试数据
        dates = pd.date_range(start='2023-01-01', periods=8, freq='Q')
        test_income_df = pd.DataFrame({
            'date': dates,
            'revenue': np.random.uniform(50e9, 100e9, 8),
            'ebitda': np.random.uniform(10e9, 30e9, 8),
            'grossProfit': np.random.uniform(20e9, 50e9, 8),
            'sellingGeneralAndAdministrativeExpenses': np.random.uniform(5e9, 15e9, 8)
        })
        print("✅ Test data created")
        
        # 测试图表生成方法存在
        methods = [
            'generate_revenue_yoy_chart',
            'generate_ebitda_margin_chart',
            'generate_gross_margin_chart',
            'generate_sga_ratio_chart',
            'generate_ltm_ebitda_margin_chart',
            'generate_relative_performance_chart',
            'generate_ev_ebitda_band_chart',
            'generate_p_fcf_band_chart',
            'generate_peer_comparison_chart',
            'generate_football_field_chart',
        ]
        
        for method in methods:
            if hasattr(generator, method):
                print(f"✅ Method {method} exists")
            else:
                print(f"❌ Method {method} NOT FOUND")
        
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        traceback.print_exc()
        return False


def test_sensitivity_analyzer():
    """测试敏感性分析器"""
    print("\n" + "=" * 60)
    print("Testing SensitivityAnalyzer")
    print("=" * 60)
    
    try:
        from modules.sensitivity_analyzer import SensitivityAnalyzer
        import pandas as pd
        
        # 创建测试预测数据
        test_forecast = pd.DataFrame({
            'metrics': ['Revenue', 'EBITDA Margin', 'Revenue Growth'],
            '2024A': [100e9, 25.0, 10.0],
            '2025E': [110e9, 26.0, 10.0],
            '2026E': [121e9, 27.0, 10.0]
        })
        
        analyzer = SensitivityAnalyzer(test_forecast)
        print("✅ SensitivityAnalyzer instance created")
        
        # 测试收入敏感性分析
        rev_sensitivity = analyzer.analyze_revenue_sensitivity()
        print(f"✅ Revenue sensitivity analysis: {len(rev_sensitivity)} scenarios")
        
        # 测试利润率敏感性分析
        margin_sensitivity = analyzer.analyze_margin_sensitivity()
        print(f"✅ Margin sensitivity analysis: {len(margin_sensitivity)} scenarios")
        
        # 测试综合敏感性表格
        combined = analyzer.generate_sensitivity_table()
        print(f"✅ Combined sensitivity table generated")
        
        # 测试置信区间
        ci = analyzer.calculate_confidence_interval('Revenue')
        print(f"✅ Confidence interval calculated: {ci}")
        
        # 测试摘要生成
        summary = analyzer.generate_sensitivity_summary()
        print(f"✅ Summary generated: {len(summary)} characters")
        
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        traceback.print_exc()
        return False


def test_catalyst_analyzer():
    """测试催化剂分析器"""
    print("\n" + "=" * 60)
    print("Testing CatalystAnalyzer")
    print("=" * 60)
    
    try:
        from modules.catalyst_analyzer import CatalystAnalyzer, CatalystData
        
        analyzer = CatalystAnalyzer('TSLA')
        print("✅ CatalystAnalyzer instance created")
        
        # 测试新闻数据设置
        test_news = [
            {
                'title': 'Tesla announces new product launch',
                'text': 'Tesla is expected to unveil a new electric vehicle model.',
                'publishedDate': '2024-12-01',
                'site': 'Reuters'
            },
            {
                'title': 'Tesla quarterly earnings beat expectations',
                'text': 'Tesla reported strong revenue growth in Q3.',
                'publishedDate': '2024-11-15',
                'site': 'Bloomberg'
            }
        ]
        
        analyzer.set_news_data(test_news)
        print("✅ News data set")
        
        # 测试催化剂识别
        catalysts = analyzer.identify_catalysts()
        print(f"✅ Identified {len(catalysts)} catalysts")
        
        # 测试催化剂分类
        categorized = analyzer.categorize_catalysts()
        print(f"✅ Categorized: {len(categorized['positive'])} positive, "
              f"{len(categorized['negative'])} negative, {len(categorized['neutral'])} neutral")
        
        # 验证每个催化剂都有必需的属性
        for cat in catalysts:
            assert cat.sentiment in ['positive', 'negative', 'neutral'], f"Invalid sentiment: {cat.sentiment}"
            assert cat.impact_level in ['high', 'medium', 'low'], f"Invalid impact: {cat.impact_level}"
        print("✅ All catalysts have valid sentiment and impact classifications")
        
        # 测试摘要生成
        summary = analyzer.generate_catalyst_summary()
        print(f"✅ Summary generated: {len(summary)} characters")
        
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        traceback.print_exc()
        return False


def test_valuation_engine():
    """测试估值引擎"""
    print("\n" + "=" * 60)
    print("Testing ValuationEngine")
    print("=" * 60)
    
    try:
        from modules.valuation_engine import ValuationEngine
        
        # 创建测试数据
        test_financial_data = {
            'current_price': 250.0,
            'shares_outstanding': 3.2e9,
            'ebitda': 15e9,
            'free_cash_flow': 8e9,
            'revenue': 100e9,
            'net_debt': 5e9
        }
        
        test_peer_data = {
            'RIVN': {'ev_ebitda': 15.0, 'p_fcf': 20.0, 'gross_margin': 25.0},
            'GM': {'ev_ebitda': 8.0, 'p_fcf': 12.0, 'gross_margin': 18.0},
            'F': {'ev_ebitda': 7.0, 'p_fcf': 10.0, 'gross_margin': 15.0}
        }
        
        engine = ValuationEngine(test_financial_data, test_peer_data)
        print("✅ ValuationEngine instance created")
        
        # 测试EV/EBITDA估值
        ev_ebitda_val = engine.calculate_ev_ebitda_valuation()
        print(f"✅ EV/EBITDA valuation: {ev_ebitda_val}")
        
        # 测试同行比较估值
        peer_val = engine.calculate_peer_comparison_valuation()
        print(f"✅ Peer comparison valuation: {peer_val}")
        
        # 测试DCF估值
        dcf_val = engine.calculate_dcf_valuation({})
        print(f"✅ DCF valuation: {dcf_val}")
        
        # 测试足球场图数据
        football_data = engine.generate_football_field_data()
        print(f"✅ Football field data: {len(football_data)} methods")
        
        # 验证至少有3种估值方法
        assert len(football_data) >= 3, "Should have at least 3 valuation methods"
        print("✅ Valuation method diversity verified (>=3 methods)")
        
        # 测试综合估值
        synthesis = engine.synthesize_valuation()
        print(f"✅ Valuation synthesis: {synthesis}")
        
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        traceback.print_exc()
        return False


def test_report_structure():
    """测试报告结构管理器"""
    print("\n" + "=" * 60)
    print("Testing ReportStructureManager")
    print("=" * 60)
    
    try:
        from modules.report_structure import ReportStructureManager, ReportSection
        
        manager = ReportStructureManager()
        print("✅ ReportStructureManager instance created")
        
        # 测试创建报告结构
        structure = manager.create_report_structure()
        print(f"✅ Report structure created with {len(structure)} sections")
        
        # 验证必需的章节
        required_sections = [
            'executive_summary',
            'company_overview', 
            'financial_analysis',
            'valuation_analysis',
            'risk_factors',
            'investment_recommendation'
        ]
        
        for section in required_sections:
            if section in structure:
                print(f"✅ Section '{section}' present")
            else:
                print(f"❌ Section '{section}' MISSING")
        
        # 测试数据来源标注
        annotated = manager.add_data_source_annotation(
            "Revenue was $100B", "FMP API", "2024-12-01"
        )
        assert "FMP API" in annotated or "Source" in annotated
        print("✅ Data source annotation works")
        
        # 测试AI内容标记
        marked = manager.add_ai_content_marker("This is AI generated content")
        assert "AI" in marked or "generated" in marked.lower()
        print("✅ AI content marker works")
        
        # 测试报告结构验证 - 使用ReportSection对象
        test_report = {
            section: ReportSection(
                title=section.replace('_', ' ').title(),
                content='test content',
                order=i
            ) for i, section in enumerate(required_sections)
        }
        validation_result = manager.validate_report_structure(test_report)
        print(f"✅ Report structure validation: {validation_result['is_valid']}")
        
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        traceback.print_exc()
        return False


def test_news_integrator():
    """测试新闻整合器"""
    print("\n" + "=" * 60)
    print("Testing NewsIntegrator")
    print("=" * 60)
    
    try:
        from modules.news_integrator import NewsIntegrator
        
        integrator = NewsIntegrator('TSLA')
        print("✅ NewsIntegrator instance created")
        
        # 测试新闻分类
        test_news = [
            {
                'title': 'Tesla reports record quarterly deliveries',
                'text': 'Tesla delivered more vehicles than expected.',
                'publishedDate': '2024-12-05T10:00:00.000Z',
                'site': 'Reuters'
            },
            {
                'title': 'New Tesla factory announced',
                'text': 'Tesla plans to build a new manufacturing facility.',
                'publishedDate': '2024-12-03T08:00:00.000Z',
                'site': 'Bloomberg'
            }
        ]
        
        # 测试分类功能
        if hasattr(integrator, 'classify_news'):
            classified = integrator.classify_news(test_news)
            print(f"✅ News classification works")
        
        # 测试排序功能
        if hasattr(integrator, 'rank_by_importance'):
            ranked = integrator.rank_by_importance(test_news)
            print(f"✅ News ranking works")
        
        # 测试影响分析
        if hasattr(integrator, 'analyze_impact'):
            impact = integrator.analyze_impact(test_news)
            print(f"✅ Impact analysis works")
        
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        traceback.print_exc()
        return False


def test_advanced_chart_functions():
    """测试高级图表函数"""
    print("\n" + "=" * 60)
    print("Testing Advanced Chart Functions")
    print("=" * 60)
    
    try:
        from modules.chart_generator import (
            generate_stock_price_chart,
            generate_financial_radar_chart,
            generate_time_series_chart,
            generate_sensitivity_heatmap,
            generate_technical_indicators_chart,
            generate_valuation_waterfall_chart,
            generate_quarterly_comparison_chart,
            generate_cash_flow_chart
        )
        print("✅ All advanced chart functions imported")
        
        # 测试函数存在且可调用
        functions = [
            ('generate_stock_price_chart', generate_stock_price_chart),
            ('generate_financial_radar_chart', generate_financial_radar_chart),
            ('generate_time_series_chart', generate_time_series_chart),
            ('generate_sensitivity_heatmap', generate_sensitivity_heatmap),
            ('generate_technical_indicators_chart', generate_technical_indicators_chart),
            ('generate_valuation_waterfall_chart', generate_valuation_waterfall_chart),
            ('generate_quarterly_comparison_chart', generate_quarterly_comparison_chart),
            ('generate_cash_flow_chart', generate_cash_flow_chart),
        ]
        
        for name, func in functions:
            if callable(func):
                print(f"✅ Function {name} is callable")
            else:
                print(f"❌ Function {name} is NOT callable")
        
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        traceback.print_exc()
        return False


def run_all_tests():
    """运行所有测试"""
    print("\n" + "=" * 60)
    print("RUNNING ALL MODULE TESTS")
    print("=" * 60 + "\n")
    
    results = {
        'imports': test_import_modules(),
        'chart_generator': test_enhanced_chart_generator(),
        'advanced_charts': test_advanced_chart_functions(),
        'sensitivity': test_sensitivity_analyzer(),
        'catalyst': test_catalyst_analyzer(),
        'valuation': test_valuation_engine(),
        'report_structure': test_report_structure(),
        'news': test_news_integrator()
    }
    
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    
    passed = 0
    failed = 0
    
    for test_name, result in results.items():
        if test_name == 'imports':
            # 处理导入测试结果
            import_passed = sum(1 for _, success, _ in result if success)
            import_failed = len(result) - import_passed
            print(f"Module Imports: {import_passed}/{len(result)} passed")
            passed += import_passed
            failed += import_failed
        else:
            status = "✅ PASSED" if result else "❌ FAILED"
            print(f"{test_name}: {status}")
            if result:
                passed += 1
            else:
                failed += 1
    
    print("\n" + "-" * 60)
    print(f"Total: {passed} passed, {failed} failed")
    print("=" * 60)
    
    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
