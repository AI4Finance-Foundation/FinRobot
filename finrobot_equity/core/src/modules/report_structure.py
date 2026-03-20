#!/usr/bin/env python
# coding: utf-8
"""
报告结构管理器模块
管理报告的结构、数据来源标注和AI内容标记
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from datetime import datetime
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class ReportSection:
    """报告章节数据类"""
    title: str
    content: str
    charts: List[str] = field(default_factory=list)
    data_sources: List[str] = field(default_factory=list)
    is_ai_generated: bool = False
    summary: str = ""
    order: int = 0


class ReportStructureManager:
    """报告结构管理器 - 管理报告结构和标注"""
    
    # 标准报告结构
    STANDARD_SECTIONS = [
        ('executive_summary', 'Executive Summary', 1),
        ('company_overview', 'Company Overview', 2),
        ('financial_analysis', 'Financial Analysis', 3),
        ('valuation_analysis', 'Valuation Analysis', 4),
        ('catalyst_analysis', 'Catalyst Analysis', 5),
        ('risk_factors', 'Risk Factors', 6),
        ('investment_recommendation', 'Investment Recommendation', 7),
        ('appendix', 'Appendix', 8)
    ]
    
    def __init__(self):
        """初始化报告结构管理器"""
        self.sections: Dict[str, ReportSection] = {}
        self.metadata = {
            'created_at': datetime.now().isoformat(),
            'version': '2.0',
            'generator': 'FinRobot Enhanced Report Generator'
        }
    
    def create_report_structure(self) -> Dict[str, ReportSection]:
        """
        创建标准报告结构
        
        Returns:
            章节字典
        """
        logger.info("Creating standard report structure...")
        
        for section_id, title, order in self.STANDARD_SECTIONS:
            self.sections[section_id] = ReportSection(
                title=title,
                content="",
                order=order
            )
        
        logger.info(f"✅ Created {len(self.sections)} report sections")
        return self.sections
    
    def add_section_content(self, section_id: str, content: str, 
                           is_ai_generated: bool = False,
                           data_sources: List[str] = None,
                           charts: List[str] = None):
        """
        添加章节内容
        
        Args:
            section_id: 章节ID
            content: 内容文本
            is_ai_generated: 是否AI生成
            data_sources: 数据来源列表
            charts: 图表路径列表
        """
        if section_id not in self.sections:
            logger.warning(f"Section {section_id} not found, creating new section")
            self.sections[section_id] = ReportSection(
                title=section_id.replace('_', ' ').title(),
                content="",
                order=len(self.sections) + 1
            )
        
        section = self.sections[section_id]
        section.content = content
        section.is_ai_generated = is_ai_generated
        
        if data_sources:
            section.data_sources.extend(data_sources)
        if charts:
            section.charts.extend(charts)
    
    def add_data_source_annotation(self, content: str, source: str, 
                                   date: str = None) -> str:
        """
        添加数据来源标注
        
        Args:
            content: 原始内容
            source: 数据来源
            date: 数据日期
        
        Returns:
            带标注的内容
        """
        date_str = f" as of {date}" if date else ""
        annotation = f'<span class="data-source" title="Source: {source}{date_str}">{content}</span>'
        return annotation
    
    def add_ai_content_marker(self, content: str) -> str:
        """
        添加AI生成内容标记
        
        Args:
            content: AI生成的内容
        
        Returns:
            带标记的内容
        """
        marker = '<div class="ai-generated-content" data-ai="true">'
        end_marker = '<span class="ai-badge">AI Generated</span></div>'
        return f"{marker}{content}{end_marker}"
    
    def generate_section_summary(self, section_id: str, max_length: int = 200) -> str:
        """
        生成章节小结
        
        Args:
            section_id: 章节ID
            max_length: 最大长度
        
        Returns:
            小结文本
        """
        if section_id not in self.sections:
            return ""
        
        content = self.sections[section_id].content
        if not content:
            return ""
        
        # 简单的摘要生成（取前几句）
        sentences = content.split('.')
        summary = ""
        for sentence in sentences:
            if len(summary) + len(sentence) < max_length:
                summary += sentence.strip() + ". "
            else:
                break
        
        self.sections[section_id].summary = summary.strip()
        return summary.strip()
    
    def validate_report_structure(self, report: Dict = None) -> Dict[str, Any]:
        """
        验证报告结构完整性
        
        Args:
            report: 报告数据（默认使用内部sections）
        
        Returns:
            验证结果
        """
        logger.info("Validating report structure...")
        
        sections_to_check = report if report else self.sections
        
        required_sections = ['executive_summary', 'company_overview', 
                           'financial_analysis', 'valuation_analysis',
                           'risk_factors', 'investment_recommendation']
        
        validation_result = {
            'is_valid': True,
            'missing_sections': [],
            'empty_sections': [],
            'warnings': [],
            'section_count': len(sections_to_check)
        }
        
        # 检查必需章节
        for section_id in required_sections:
            if section_id not in sections_to_check:
                validation_result['missing_sections'].append(section_id)
                validation_result['is_valid'] = False
            elif not sections_to_check[section_id].content:
                validation_result['empty_sections'].append(section_id)
                validation_result['warnings'].append(f"Section '{section_id}' is empty")
        
        # 检查章节顺序
        if sections_to_check:
            orders = [s.order for s in sections_to_check.values()]
            if orders != sorted(orders):
                validation_result['warnings'].append("Section order may be incorrect")
        
        logger.info(f"✅ Validation complete: {'PASSED' if validation_result['is_valid'] else 'FAILED'}")
        return validation_result
    
    def get_ordered_sections(self) -> List[ReportSection]:
        """
        获取按顺序排列的章节列表
        
        Returns:
            排序后的章节列表
        """
        return sorted(self.sections.values(), key=lambda x: x.order)
    
    def generate_table_of_contents(self) -> str:
        """
        生成目录
        
        Returns:
            目录HTML
        """
        toc_parts = ['<div class="table-of-contents">', '<h2>Table of Contents</h2>', '<ul>']
        
        for section in self.get_ordered_sections():
            if section.content:  # 只包含有内容的章节
                anchor = section.title.lower().replace(' ', '-')
                toc_parts.append(f'<li><a href="#{anchor}">{section.order}. {section.title}</a></li>')
        
        toc_parts.extend(['</ul>', '</div>'])
        return '\n'.join(toc_parts)
    
    def generate_data_sources_section(self) -> str:
        """
        生成数据来源章节
        
        Returns:
            数据来源HTML
        """
        all_sources = set()
        for section in self.sections.values():
            all_sources.update(section.data_sources)
        
        if not all_sources:
            return ""
        
        sources_html = ['<div class="data-sources">', '<h3>Data Sources</h3>', '<ul>']
        for source in sorted(all_sources):
            sources_html.append(f'<li>{source}</li>')
        sources_html.extend(['</ul>', '</div>'])
        
        return '\n'.join(sources_html)
    
    def generate_ai_disclosure(self) -> str:
        """
        生成AI内容披露
        
        Returns:
            AI披露HTML
        """
        ai_sections = [s.title for s in self.sections.values() if s.is_ai_generated]
        
        if not ai_sections:
            return ""
        
        disclosure = [
            '<div class="ai-disclosure">',
            '<h3>AI-Generated Content Disclosure</h3>',
            '<p>The following sections contain AI-generated content:</p>',
            '<ul>'
        ]
        
        for section_title in ai_sections:
            disclosure.append(f'<li>{section_title}</li>')
        
        disclosure.extend([
            '</ul>',
            '<p><em>AI-generated content has been reviewed but may require additional verification.</em></p>',
            '</div>'
        ])
        
        return '\n'.join(disclosure)
    
    def export_structure(self) -> Dict:
        """
        导出报告结构为字典
        
        Returns:
            结构字典
        """
        return {
            'metadata': self.metadata,
            'sections': {
                section_id: {
                    'title': section.title,
                    'order': section.order,
                    'has_content': bool(section.content),
                    'is_ai_generated': section.is_ai_generated,
                    'charts_count': len(section.charts),
                    'data_sources': section.data_sources
                }
                for section_id, section in self.sections.items()
            }
        }


# CSS样式模板
REPORT_STYLES = """
<style>
.data-source {
    border-bottom: 1px dotted #666;
    cursor: help;
}

.ai-generated-content {
    position: relative;
    border-left: 3px solid #D2A74A;
    padding-left: 10px;
    margin: 10px 0;
}

.ai-badge {
    display: inline-block;
    background: #D2A74A;
    color: white;
    font-size: 10px;
    padding: 2px 6px;
    border-radius: 3px;
    margin-left: 5px;
}

.ai-disclosure {
    background: #f5f5f5;
    padding: 15px;
    border-radius: 5px;
    margin: 20px 0;
}

.data-sources {
    background: #f9f9f9;
    padding: 15px;
    border-radius: 5px;
    margin: 20px 0;
}

.table-of-contents {
    background: #fafafa;
    padding: 20px;
    border-radius: 5px;
    margin-bottom: 30px;
}

.table-of-contents ul {
    list-style-type: none;
    padding-left: 0;
}

.table-of-contents li {
    padding: 5px 0;
}
</style>
"""


def create_report_structure_manager() -> ReportStructureManager:
    """创建报告结构管理器实例"""
    return ReportStructureManager()


if __name__ == "__main__":
    print("Report Structure Manager Module")
    print("Features:")
    print("- Standard report structure creation")
    print("- Data source annotation")
    print("- AI content marking")
    print("- Structure validation")
    print("- Table of contents generation")
    print("- Data sources section")
    print("- AI disclosure generation")
