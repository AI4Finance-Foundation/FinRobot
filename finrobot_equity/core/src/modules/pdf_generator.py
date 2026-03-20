#!/usr/bin/env python
# coding: utf-8
"""
专业股票研究报告PDF生成器
基于用户提供的样式规范设计，支持A4纵向多页报告
"""

import os
import io
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm

# pt (point) = 1/72 inch, define manually since not all versions export it
pt = 1
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, 
    Image, PageBreak, KeepTogether, Frame, PageTemplate, BaseDocTemplate
)
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

import pandas as pd


# =============================================================================
# 颜色规范 (核心4色)
# =============================================================================
class ReportColors:
    """报告颜色规范"""
    # 主色（深蓝）- 用于封面背景、重要标题、图表主色
    PRIMARY = colors.HexColor('#0B1B33')
    
    # 强调色（金色）- 用于重点线条、数据柱、图表对比色
    ACCENT = colors.HexColor('#D2A74A')
    
    # 辅色（中性深灰）- 正文文本、表格文字
    TEXT = colors.HexColor('#333333')
    
    # 背景浅灰 - 表格底色、模块分隔底色
    BACKGROUND = colors.HexColor('#F5F5F5')
    
    # 分隔线浅灰
    SEPARATOR = colors.HexColor('#E0E0E0')
    
    # 白色
    WHITE = colors.white
    
    # 中灰 - 用于同行/指数图表
    MEDIUM_GRAY = colors.HexColor('#666666')
    
    # 浅金色 - 用于时间戳等
    LIGHT_GOLD = colors.HexColor('#C4A35A')


# =============================================================================
# 页面尺寸规范
# =============================================================================
class PageSpec:
    """页面规格"""
    # A4 尺寸
    WIDTH, HEIGHT = A4  # 210mm × 297mm
    
    # 页边距
    MARGIN_TOP = 22 * mm
    MARGIN_BOTTOM = 20 * mm
    MARGIN_LEFT = 18 * mm
    MARGIN_RIGHT = 18 * mm
    
    # 内容区域
    CONTENT_WIDTH = WIDTH - MARGIN_LEFT - MARGIN_RIGHT
    CONTENT_HEIGHT = HEIGHT - MARGIN_TOP - MARGIN_BOTTOM
    
    # 两栏布局
    COLUMN_WIDTH = CONTENT_WIDTH / 2 - 6 * mm  # 减去栏间距一半
    COLUMN_GUTTER = 12 * mm  # 栏间距


# =============================================================================
# 字体规范
# =============================================================================
class FontSpec:
    """字体规格"""
    # 字体名称 (使用系统可用字体)
    FONT_NORMAL = 'Helvetica'
    FONT_BOLD = 'Helvetica-Bold'
    
    # 字号规范
    H1_SIZE = 28  # 主标题
    H2_SIZE = 16  # 二级标题
    H3_SIZE = 12  # 三级标题
    BODY_SIZE = 9  # 正文
    TABLE_SIZE = 9  # 表格
    SMALL_SIZE = 8  # 小字（免责声明等）
    
    # 行距
    LINE_HEIGHT = 1.4


# =============================================================================
# 样式工厂
# =============================================================================
def create_styles() -> Dict[str, ParagraphStyle]:
    """创建报告所需的所有段落样式"""
    styles = {}
    
    # 主标题 H1 - 封面大标题
    styles['H1'] = ParagraphStyle(
        'H1',
        fontName=FontSpec.FONT_BOLD,
        fontSize=FontSpec.H1_SIZE,
        textColor=ReportColors.WHITE,
        alignment=TA_CENTER,
        spaceAfter=6 * pt,
        leading=FontSpec.H1_SIZE * 1.2,
    )
    
    # 主标题 H1 深蓝色版本
    styles['H1_Dark'] = ParagraphStyle(
        'H1_Dark',
        fontName=FontSpec.FONT_BOLD,
        fontSize=FontSpec.H1_SIZE,
        textColor=ReportColors.PRIMARY,
        alignment=TA_LEFT,
        spaceAfter=6 * pt,
        leading=FontSpec.H1_SIZE * 1.2,
    )
    
    # 二级标题 H2
    styles['H2'] = ParagraphStyle(
        'H2',
        fontName=FontSpec.FONT_BOLD,
        fontSize=FontSpec.H2_SIZE,
        textColor=ReportColors.PRIMARY,
        alignment=TA_LEFT,
        spaceBefore=12 * pt,
        spaceAfter=6 * pt,
        leading=FontSpec.H2_SIZE * 1.3,
    )
    
    # 二级标题 H2 浅灰色
    styles['H2_Gray'] = ParagraphStyle(
        'H2_Gray',
        fontName=FontSpec.FONT_BOLD,
        fontSize=FontSpec.H2_SIZE,
        textColor=ReportColors.MEDIUM_GRAY,
        alignment=TA_LEFT,
        spaceBefore=12 * pt,
        spaceAfter=6 * pt,
        leading=FontSpec.H2_SIZE * 1.3,
    )
    
    # 三级标题 H3
    styles['H3'] = ParagraphStyle(
        'H3',
        fontName=FontSpec.FONT_BOLD,
        fontSize=FontSpec.H3_SIZE,
        textColor=ReportColors.PRIMARY,
        alignment=TA_LEFT,
        spaceBefore=8 * pt,
        spaceAfter=4 * pt,
        leading=FontSpec.H3_SIZE * 1.3,
    )
    
    # 正文
    styles['Body'] = ParagraphStyle(
        'Body',
        fontName=FontSpec.FONT_NORMAL,
        fontSize=FontSpec.BODY_SIZE,
        textColor=ReportColors.TEXT,
        alignment=TA_JUSTIFY,
        spaceAfter=6 * pt,
        leading=FontSpec.BODY_SIZE * FontSpec.LINE_HEIGHT,
    )
    
    # 正文 - 左对齐
    styles['Body_Left'] = ParagraphStyle(
        'Body_Left',
        fontName=FontSpec.FONT_NORMAL,
        fontSize=FontSpec.BODY_SIZE,
        textColor=ReportColors.TEXT,
        alignment=TA_LEFT,
        spaceAfter=6 * pt,
        leading=FontSpec.BODY_SIZE * FontSpec.LINE_HEIGHT,
    )
    
    # 要点列表
    styles['Bullet'] = ParagraphStyle(
        'Bullet',
        fontName=FontSpec.FONT_NORMAL,
        fontSize=FontSpec.BODY_SIZE,
        textColor=ReportColors.TEXT,
        alignment=TA_LEFT,
        leftIndent=12 * pt,
        bulletIndent=6 * pt,
        spaceAfter=4 * pt,
        leading=FontSpec.BODY_SIZE * FontSpec.LINE_HEIGHT,
    )
    
    # 标签语 (Tagline)
    styles['Tagline'] = ParagraphStyle(
        'Tagline',
        fontName=FontSpec.FONT_NORMAL,
        fontSize=12,
        textColor=ReportColors.TEXT,
        alignment=TA_LEFT,
        spaceAfter=8 * pt,
        leading=14 * pt,
    )
    
    # 小字 (免责声明)
    styles['Disclaimer'] = ParagraphStyle(
        'Disclaimer',
        fontName=FontSpec.FONT_NORMAL,
        fontSize=FontSpec.SMALL_SIZE,
        textColor=ReportColors.MEDIUM_GRAY,
        alignment=TA_LEFT,
        spaceAfter=4 * pt,
        leading=FontSpec.SMALL_SIZE * 1.3,
    )
    
    # 表格标题
    styles['TableHeader'] = ParagraphStyle(
        'TableHeader',
        fontName=FontSpec.FONT_BOLD,
        fontSize=FontSpec.TABLE_SIZE,
        textColor=ReportColors.PRIMARY,
        alignment=TA_RIGHT,
    )
    
    # 表格内容
    styles['TableCell'] = ParagraphStyle(
        'TableCell',
        fontName=FontSpec.FONT_NORMAL,
        fontSize=FontSpec.TABLE_SIZE,
        textColor=ReportColors.TEXT,
        alignment=TA_RIGHT,
    )
    
    # 封面副标题
    styles['Subtitle'] = ParagraphStyle(
        'Subtitle',
        fontName=FontSpec.FONT_NORMAL,
        fontSize=14,
        textColor=ReportColors.LIGHT_GOLD,
        alignment=TA_CENTER,
        spaceAfter=4 * pt,
    )
    
    # 封面日期
    styles['CoverDate'] = ParagraphStyle(
        'CoverDate',
        fontName=FontSpec.FONT_NORMAL,
        fontSize=10,
        textColor=ReportColors.LIGHT_GOLD,
        alignment=TA_CENTER,
    )
    
    # 页眉文字
    styles['Header'] = ParagraphStyle(
        'Header',
        fontName=FontSpec.FONT_NORMAL,
        fontSize=10,
        textColor=ReportColors.MEDIUM_GRAY,
        alignment=TA_RIGHT,
    )
    
    return styles


# =============================================================================
# 表格样式工厂
# =============================================================================
def create_key_data_table_style() -> TableStyle:
    """创建KEY DATA表格样式"""
    return TableStyle([
        # 背景
        ('BACKGROUND', (0, 0), (-1, -1), ReportColors.BACKGROUND),
        # 字体
        ('FONTNAME', (0, 0), (-1, -1), FontSpec.FONT_NORMAL),
        ('FONTSIZE', (0, 0), (-1, -1), FontSpec.TABLE_SIZE),
        # 文本颜色
        ('TEXTCOLOR', (0, 0), (0, -1), ReportColors.MEDIUM_GRAY),  # 左列标签
        ('TEXTCOLOR', (1, 0), (1, -1), ReportColors.TEXT),  # 右列数值
        # 对齐
        ('ALIGN', (0, 0), (0, -1), 'LEFT'),  # 左列左对齐
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),  # 右列右对齐
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        # 内边距
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        # 边框 - 行分隔线
        ('LINEBELOW', (0, 0), (-1, -2), 0.5, ReportColors.SEPARATOR),
    ])


def create_financial_table_style() -> TableStyle:
    """创建财务摘要表格样式"""
    return TableStyle([
        # 表头行背景
        ('BACKGROUND', (0, 0), (-1, 0), ReportColors.BACKGROUND),
        # 表头字体
        ('FONTNAME', (0, 0), (-1, 0), FontSpec.FONT_BOLD),
        ('FONTSIZE', (0, 0), (-1, -1), FontSpec.TABLE_SIZE),
        # 文本颜色
        ('TEXTCOLOR', (0, 0), (-1, 0), ReportColors.PRIMARY),  # 表头深蓝
        ('TEXTCOLOR', (0, 1), (0, -1), ReportColors.TEXT),  # 行标签
        ('TEXTCOLOR', (1, 1), (-1, -1), ReportColors.TEXT),  # 数值
        # 对齐
        ('ALIGN', (0, 0), (0, -1), 'LEFT'),  # 第一列左对齐
        ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),  # 数值右对齐
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        # 内边距
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        # 边框
        ('LINEBELOW', (0, 0), (-1, 0), 1.5, ReportColors.PRIMARY),  # 表头下粗线
        ('LINEBELOW', (0, 1), (-1, -2), 0.5, ReportColors.SEPARATOR),  # 行分隔细线
        ('LINEBELOW', (0, -1), (-1, -1), 1, ReportColors.PRIMARY),  # 表尾线
    ])


def create_peer_table_style(highlight_row: int = -1) -> TableStyle:
    """创建同行对比表格样式，可选高亮行"""
    style_commands = [
        # 表头行背景
        ('BACKGROUND', (0, 0), (-1, 0), ReportColors.BACKGROUND),
        # 表头字体
        ('FONTNAME', (0, 0), (-1, 0), FontSpec.FONT_BOLD),
        ('FONTSIZE', (0, 0), (-1, -1), FontSpec.TABLE_SIZE),
        # 文本颜色
        ('TEXTCOLOR', (0, 0), (-1, 0), ReportColors.PRIMARY),
        ('TEXTCOLOR', (0, 1), (-1, -1), ReportColors.TEXT),
        # 对齐
        ('ALIGN', (0, 0), (0, -1), 'LEFT'),
        ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        # 内边距
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        # 边框
        ('LINEBELOW', (0, 0), (-1, 0), 1.5, ReportColors.PRIMARY),
        ('LINEBELOW', (0, 1), (-1, -2), 0.5, ReportColors.SEPARATOR),
        ('LINEBELOW', (0, -1), (-1, -1), 1, ReportColors.PRIMARY),
    ]
    
    # 高亮指定行（当前分析对象）
    if highlight_row > 0:
        style_commands.append(
            ('BACKGROUND', (0, highlight_row), (-1, highlight_row), colors.HexColor('#FFF8E5'))
        )
    
    return TableStyle(style_commands)


# =============================================================================
# 数据格式化工具
# =============================================================================
def format_number(value: Any, format_type: str = 'auto') -> str:
    """格式化数字显示"""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return 'N/A'
    
    if isinstance(value, str):
        return value
    
    try:
        num = float(value)
    except (ValueError, TypeError):
        return str(value)
    
    if format_type == 'currency_b':
        return f"${num:,.2f}B"
    elif format_type == 'currency_m':
        return f"${num:,.1f}M"
    elif format_type == 'currency':
        return f"${num:,.2f}"
    elif format_type == 'percent':
        return f"{num:.1f}%"
    elif format_type == 'ratio':
        return f"{num:.2f}x"
    elif format_type == 'auto':
        if abs(num) >= 1e12:
            return f"${num/1e12:,.1f}T"
        elif abs(num) >= 1e9:
            return f"${num/1e9:,.1f}B"
        elif abs(num) >= 1e6:
            return f"${num/1e6:,.1f}M"
        elif abs(num) >= 1000:
            return f"{num:,.0f}"
        elif abs(num) < 1:
            return f"{num:.2%}"
        else:
            return f"{num:.2f}"
    else:
        return f"{num:,.2f}"


def format_percentage(value: Any) -> str:
    """格式化百分比"""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return 'N/A'
    
    if isinstance(value, str):
        if '%' in value:
            return value
        try:
            num = float(value.replace('%', ''))
            return f"{num:.1f}%"
        except ValueError:
            return value
    
    try:
        num = float(value)
        # 如果值小于1，假设是小数形式
        if abs(num) < 1:
            return f"{num * 100:.1f}%"
        return f"{num:.1f}%"
    except (ValueError, TypeError):
        return str(value)


# =============================================================================
# PDF文档构建器
# =============================================================================
class EquityReportPDF:
    """股票研究报告PDF生成器"""
    
    def __init__(self, output_path: str, report_data: Dict[str, Any]):
        """
        初始化PDF生成器
        
        Args:
            output_path: 输出PDF文件路径
            report_data: 报告数据字典
        """
        self.output_path = output_path
        self.data = report_data
        self.styles = create_styles()
        self.elements = []
        
        # 创建文档
        self.doc = SimpleDocTemplate(
            output_path,
            pagesize=A4,
            topMargin=PageSpec.MARGIN_TOP,
            bottomMargin=PageSpec.MARGIN_BOTTOM,
            leftMargin=PageSpec.MARGIN_LEFT,
            rightMargin=PageSpec.MARGIN_RIGHT,
        )
    
    def add_cover_section(self):
        """添加封面区域（页面顶部1/3）"""
        # 封面容器表格 - 深蓝背景
        cover_data = [['']]
        cover_table = Table(cover_data, colWidths=[PageSpec.CONTENT_WIDTH], rowHeights=[80 * mm])
        cover_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), ReportColors.PRIMARY),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        
        # 创建封面内容
        company_name = self.data.get('company_name_full', 'Company Name')
        ticker = self.data.get('company_ticker', 'TICK')
        sector = self.data.get('sector', 'Sector')
        report_date = self.data.get('report_date', datetime.now().strftime('%B %Y'))
        
        cover_content = []
        cover_content.append(Paragraph("STOCK ANALYSIS REPORT", self.styles['H1']))
        cover_content.append(Spacer(1, 8))
        cover_content.append(Paragraph(company_name.upper(), self.styles['H1']))
        cover_content.append(Spacer(1, 4))
        cover_content.append(Paragraph(f"{ticker} | {sector}", self.styles['Subtitle']))
        cover_content.append(Spacer(1, 12))
        cover_content.append(Paragraph(report_date, self.styles['CoverDate']))
        
        # 将内容放入封面区域
        # 使用嵌套表格来实现垂直居中
        inner_table_data = [[cover_content]]
        inner_table = Table(inner_table_data, colWidths=[PageSpec.CONTENT_WIDTH - 20 * mm])
        inner_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ]))
        
        # 封面区域背景
        cover_bg = Table(
            [[inner_table]], 
            colWidths=[PageSpec.CONTENT_WIDTH], 
            rowHeights=[75 * mm]
        )
        cover_bg.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), ReportColors.PRIMARY),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('LEFTPADDING', (0, 0), (-1, -1), 10 * mm),
            ('RIGHTPADDING', (0, 0), (-1, -1), 10 * mm),
        ]))
        
        self.elements.append(cover_bg)
        self.elements.append(Spacer(1, 10 * mm))
    
    def add_key_data_table(self) -> Table:
        """创建KEY DATA表格"""
        data = [
            ['Bloomberg Ticker', f"{self.data.get('company_ticker', 'N/A')} US"],
            ['Sector', self.data.get('sector', 'N/A')],
            ['Share Price (USD)', self.data.get('share_price', 'N/A')],
            ['Rating', self.data.get('rating', 'N/A')],
            ['12-mth Target Price', self.data.get('target_price', 'N/A')],
            ['Market Cap', self.data.get('market_cap', 'N/A')],
            ['Volume (m shares)', self.data.get('volume', 'N/A')],
            ['Free Float (%)', self.data.get('free_float', 'N/A')],
            ['Dividend Yield (%)', self.data.get('dividend_yield', 'N/A')],
            ['Net Debt/Equity', self.data.get('net_debt_to_equity', 'N/A')],
            ['Fwd. P/E (x)', self.data.get('fwd_pe', 'N/A')],
            ['P/Book (x)', self.data.get('pb_ratio', 'N/A')],
            ['ROE (%)', self.data.get('roe', 'N/A')],
        ]
        
        col_widths = [45 * mm, 35 * mm]
        table = Table(data, colWidths=col_widths)
        table.setStyle(create_key_data_table_style())
        
        return table
    
    def add_page1_content(self):
        """添加第1页内容：封面后的基本信息+文本分析"""
        # KEY DATA 标题和表格
        self.elements.append(Paragraph("KEY DATA", self.styles['H2']))
        self.elements.append(self.add_key_data_table())
        self.elements.append(Spacer(1, 3 * mm))
        self.elements.append(Paragraph(
            f"Closing Price as of {self.data.get('closing_price_date', 'N/A')}", 
            self.styles['Disclaimer']
        ))
        self.elements.append(Paragraph(
            f"Source: {self.data.get('data_source_text', 'Company Filings')}", 
            self.styles['Disclaimer']
        ))
        
        self.elements.append(Spacer(1, 6 * mm))
        
        # Tagline
        tagline = self.data.get('tagline', '')
        if tagline:
            # 截断过长的tagline
            if len(tagline) > 500:
                tagline = tagline[:500] + "..."
            self.elements.append(Paragraph(tagline, self.styles['Tagline']))
            self.elements.append(Spacer(1, 4 * mm))
        
        # Company Overview
        self.elements.append(Paragraph("COMPANY OVERVIEW", self.styles['H2']))
        overview = self.data.get('company_overview', 'Company overview not available.')
        # 截断过长的内容
        if len(overview) > 1500:
            overview = overview[:1500] + "..."
        self.elements.append(Paragraph(overview, self.styles['Body']))
        
        # Investment Overview  
        self.elements.append(Paragraph("INVESTMENT OVERVIEW", self.styles['H2']))
        investment = self.data.get('investment_overview', 'Investment overview not available.')
        if len(investment) > 1000:
            investment = investment[:1000] + "..."
        self.elements.append(Paragraph(investment, self.styles['Body']))
        
        # Valuation Analysis
        self.elements.append(Paragraph("VALUATION ANALYSIS", self.styles['H2']))
        valuation = self.data.get('valuation_overview', 'Valuation analysis not available.')
        if len(valuation) > 1000:
            valuation = valuation[:1000] + "..."
        self.elements.append(Paragraph(valuation, self.styles['Body']))
    
    def add_page1_bottom(self):
        """添加第1页底部内容：Risks"""
        self.elements.append(Spacer(1, 6 * mm))
        
        # Risks
        self.elements.append(Paragraph("RISK FACTORS", self.styles['H2']))
        risks_text = self.data.get('risks', 'Risk factors not available.')
        # 将风险文本分割成列表项
        if risks_text:
            risks_lines = risks_text.strip().split('\n')
            for line in risks_lines:
                if line.strip():
                    self.elements.append(Paragraph(f"• {line.strip()}", self.styles['Bullet']))
    
    def add_page2_content(self):
        """添加第2页内容：竞争分析 + 图表"""
        self.elements.append(PageBreak())
        
        # 页面标题
        company = self.data.get('company_name_full', 'Company')
        ticker = self.data.get('company_ticker', 'TICK')
        self.elements.append(Paragraph(f"{company} ({ticker})", self.styles['H2_Gray']))
        self.elements.append(Spacer(1, 4 * mm))
        
        # 竞争分析
        self.elements.append(Paragraph("COMPETITIVE ANALYSIS", self.styles['H2']))
        competitor = self.data.get('competitor_analysis', 'Competitor analysis not available.')
        if len(competitor) > 1500:
            competitor = competitor[:1500] + "..."
        self.elements.append(Paragraph(competitor, self.styles['Body']))
        
        self.elements.append(Spacer(1, 4 * mm))
        
        # 主要要点
        self.elements.append(Paragraph("KEY POINTS", self.styles['H2']))
        takeaways = self.data.get('major_takeaways', '')
        if takeaways:
            lines = takeaways.strip().split('\n')
            for i, line in enumerate(lines[:8]):  # 限制最多8条
                line = line.strip()
                if line and not line.startswith('•'):
                    if ':' in line:
                        parts = line.split(':', 1)
                        self.elements.append(Paragraph(
                            f"• <b>{parts[0]}:</b>{parts[1] if len(parts) > 1 else ''}", 
                            self.styles['Bullet']
                        ))
                    else:
                        self.elements.append(Paragraph(f"• {line}", self.styles['Bullet']))
                elif line:
                    self.elements.append(Paragraph(line, self.styles['Bullet']))
        
        self.elements.append(Spacer(1, 6 * mm))
        
        # 图表区域
        self.elements.append(Paragraph("FINANCIAL METRICS AND CHARTS", self.styles['H2']))
        self.elements.append(Spacer(1, 4 * mm))
        
        # 三张图表横排
        chart_width = (PageSpec.CONTENT_WIDTH - 8 * mm) / 3
        chart_height = 45 * mm
        
        chart_row = []
        
        # 图表1: Revenue & EBITDA
        revenue_chart = self.data.get('revenue_chart_path', '')
        if revenue_chart and revenue_chart.startswith('data:image'):
            chart_row.append(self._create_chart_cell_base64("Revenue & EBITDA", revenue_chart, chart_width, chart_height))
        else:
            chart_row.append([Paragraph("Revenue Chart", self.styles['H3']), Paragraph("Not available", self.styles['Disclaimer'])])
        
        # 图表2: EPS × PE
        eps_chart = self.data.get('eps_pe_chart_path', '')
        if eps_chart and eps_chart.startswith('data:image'):
            chart_row.append(self._create_chart_cell_base64("EPS × PE", eps_chart, chart_width, chart_height))
        else:
            chart_row.append([Paragraph("EPS Chart", self.styles['H3']), Paragraph("Not available", self.styles['Disclaimer'])])
        
        # 图表3: EV/EBITDA Peer
        ev_chart = self.data.get('ev_ebitda_chart_path', '')
        if ev_chart and ev_chart.startswith('data:image'):
            chart_row.append(self._create_chart_cell_base64("EV/EBITDA Peers", ev_chart, chart_width, chart_height))
        else:
            chart_row.append([Paragraph("Peer Chart", self.styles['H3']), Paragraph("Not available", self.styles['Disclaimer'])])
        
        charts_table = Table([chart_row], colWidths=[chart_width] * 3)
        charts_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('LEFTPADDING', (0, 0), (-1, -1), 2 * mm),
            ('RIGHTPADDING', (0, 0), (-1, -1), 2 * mm),
        ]))
        
        self.elements.append(charts_table)
    
    def _create_chart_cell_base64(self, title: str, base64_data: str, width: float, height: float) -> List:
        """从Base64数据创建图表单元"""
        content = []
        content.append(Paragraph(title, self.styles['H3']))
        
        try:
            # 解码base64图片
            import base64
            if base64_data.startswith('data:image'):
                img_data = base64_data.split(',')[1]
            else:
                img_data = base64_data
            
            img_bytes = base64.b64decode(img_data)
            img_buffer = io.BytesIO(img_bytes)
            
            img = Image(img_buffer, width=width - 4 * mm, height=height - 10 * mm)
            content.append(img)
        except Exception as e:
            content.append(Paragraph(f"Error loading chart: {str(e)}", self.styles['Disclaimer']))
        
        return content
    
    def _create_chart_cell(self, title: str, path: str, width: float, height: float) -> List:
        """从文件路径创建图表单元"""
        content = []
        content.append(Paragraph(title, self.styles['H3']))
        
        if path and os.path.exists(path):
            try:
                img = Image(path, width=width - 4 * mm, height=height - 10 * mm)
                content.append(img)
            except Exception as e:
                content.append(Paragraph(f"Error loading chart", self.styles['Disclaimer']))
        else:
            content.append(Paragraph("Chart not available", self.styles['Disclaimer']))
        
        return content
    
    def add_page3_content(self):
        """添加第3页内容：财务表格 + 免责声明"""
        self.elements.append(PageBreak())
        
        # 页面标题
        company = self.data.get('company_name_full', 'Company')
        ticker = self.data.get('company_ticker', 'TICK')
        self.elements.append(Paragraph(f"{company} ({ticker})", self.styles['H2_Gray']))
        self.elements.append(Spacer(1, 4 * mm))
        
        # FINANCIAL SUMMARY 表格
        self.elements.append(Paragraph("FINANCIAL SUMMARY (USD, unless otherwise stated)", self.styles['H2']))
        
        financial_df = self.data.get('financial_summary_df')
        if financial_df is not None and not financial_df.empty:
            self.elements.append(self._create_financial_table(financial_df))
        else:
            self.elements.append(Paragraph("Financial summary data not available.", self.styles['Body']))
        
        self.elements.append(Spacer(1, 6 * mm))
        
        # CREDIT & CASHFLOW METRICS 表格
        self.elements.append(Paragraph("CREDIT & CASHFLOW METRICS", self.styles['H2']))
        
        credit_df = self.data.get('credit_cashflow_df')
        if credit_df is not None and not credit_df.empty:
            self.elements.append(self._create_financial_table(credit_df))
        else:
            self.elements.append(Paragraph("Credit metrics data not available.", self.styles['Body']))
        
        self.elements.append(Spacer(1, 6 * mm))
        
        # PEER COMPARISON 表格
        self.elements.append(Paragraph("PEER VALUATION COMPARISON", self.styles['H2']))
        
        peer_df = self.data.get('peer_comparison_df')
        if peer_df is not None and not peer_df.empty:
            self.elements.append(self._create_peer_table(peer_df))
        else:
            self.elements.append(Paragraph("Peer comparison data not available.", self.styles['Body']))
        
        # 底部免责声明
        self.elements.append(Spacer(1, 10 * mm))
        self.elements.append(Paragraph("DISCLAIMER", self.styles['H3']))
        self.elements.append(Paragraph(
            self.data.get('disclaimer_text', 'Standard disclaimer applies.'),
            self.styles['Disclaimer']
        ))
    
    def _create_financial_table(self, df: pd.DataFrame) -> Table:
        """从DataFrame创建财务表格"""
        # 准备表头
        headers = ['Metrics'] + list(df.columns)
        
        # 准备数据行
        table_data = [headers]
        for idx, row in df.iterrows():
            row_data = [str(idx)]
            for val in row:
                row_data.append(format_number(val))
            table_data.append(row_data)
        
        # 计算列宽
        num_cols = len(headers)
        first_col_width = 40 * mm
        other_col_width = (PageSpec.CONTENT_WIDTH - first_col_width) / (num_cols - 1)
        col_widths = [first_col_width] + [other_col_width] * (num_cols - 1)
        
        table = Table(table_data, colWidths=col_widths)
        table.setStyle(create_financial_table_style())
        
        return table
    
    def _create_peer_table(self, df: pd.DataFrame) -> Table:
        """从DataFrame创建同行对比表格"""
        # 准备表头
        headers = ['Company'] + list(df.columns)
        
        # 准备数据行
        table_data = [headers]
        highlight_row = -1
        target_ticker = self.data.get('company_ticker', '')
        
        for i, (idx, row) in enumerate(df.iterrows()):
            row_data = [str(idx)]
            for val in row:
                row_data.append(format_number(val))
            table_data.append(row_data)
            
            # 检查是否是目标公司
            if target_ticker and target_ticker.upper() in str(idx).upper():
                highlight_row = i + 1  # +1 因为表头占一行
        
        # 计算列宽
        num_cols = len(headers)
        first_col_width = 35 * mm
        other_col_width = (PageSpec.CONTENT_WIDTH - first_col_width) / (num_cols - 1)
        col_widths = [first_col_width] + [other_col_width] * (num_cols - 1)
        
        table = Table(table_data, colWidths=col_widths)
        table.setStyle(create_peer_table_style(highlight_row))
        
        return table
    
    def add_footer(self, canvas_obj, doc):
        """添加页脚"""
        canvas_obj.saveState()
        
        # 页脚文字
        canvas_obj.setFont(FontSpec.FONT_NORMAL, 8)
        canvas_obj.setFillColor(ReportColors.MEDIUM_GRAY)
        
        # 左侧：数据源
        canvas_obj.drawString(
            PageSpec.MARGIN_LEFT, 
            12 * mm,
            f"Source: {self.data.get('research_source', 'AI4Finance FinRobot')}"
        )
        
        # 右侧：页码
        page_num = doc.page
        canvas_obj.drawRightString(
            PageSpec.WIDTH - PageSpec.MARGIN_RIGHT,
            12 * mm,
            f"Page {page_num}"
        )
        
        canvas_obj.restoreState()
    
    def build(self):
        """构建完整的PDF报告"""
        # 第1页：封面 + 基本信息 + 文本分析
        self.add_cover_section()
        self.add_page1_content()
        self.add_page1_bottom()
        
        # 第2页：竞争分析 + 图表
        self.add_page2_content()
        
        # 第3页：财务表格 + 免责声明
        self.add_page3_content()
        
        # 生成PDF
        self.doc.build(
            self.elements,
            onFirstPage=self.add_footer,
            onLaterPages=self.add_footer
        )
        
        print(f"✅ PDF report generated: {self.output_path}")
        return self.output_path


# =============================================================================
# 便捷函数
# =============================================================================
def generate_equity_report_pdf(
    output_path: str,
    report_data: Dict[str, Any]
) -> str:
    """
    生成股票研究报告PDF
    
    Args:
        output_path: 输出PDF文件路径
        report_data: 报告数据字典，包含以下键：
            - company_ticker: 股票代码
            - company_name_full: 公司全名
            - sector: 行业板块
            - report_date: 报告日期
            - share_price, target_price, rating 等市场数据
            - tagline, company_overview, investment_overview 等文本
            - financial_summary_df: 财务摘要DataFrame
            - peer_comparison_df: 同行对比DataFrame
            - revenue_chart_path, eps_pe_chart_path 等图表路径
    
    Returns:
        生成的PDF文件路径
    """
    pdf_generator = EquityReportPDF(output_path, report_data)
    return pdf_generator.build()


if __name__ == "__main__":
    # 测试代码
    test_data = {
        'company_ticker': 'AAPL',
        'company_name_full': 'Apple Inc.',
        'sector': 'Technology',
        'report_date': 'November 2025',
        'share_price': '$255.59',
        'target_price': '$280.00',
        'rating': 'Buy',
        'market_cap': '$3.89T',
        'volume': '45.2M',
        'fwd_pe': '34.1x',
        'pb_ratio': '51.8x',
        'roe': '151.9%',
        'free_float': '99.8%',
        'dividend_yield': '0.40%',
        'net_debt_to_equity': '-43.2%',
        'closing_price_date': 'November 30, 2025',
        'data_source_text': 'FMP, Company Filings',
        'tagline': 'Apple maintains strong financial position with consistent revenue growth and expanding margins.',
        'company_overview': 'Apple Inc. is a global technology leader...',
        'investment_overview': 'We maintain a positive outlook on Apple...',
        'valuation_overview': 'Current valuation reflects premium positioning...',
        'risks': 'Competition in smartphone market\nSupply chain concentration\nRegulatory pressures',
        'competitor_analysis': 'Apple competes primarily with Samsung and Google...',
        'major_takeaways': 'Revenue Growth: Strong 6.4% growth in 2025\nMargin Expansion: Contribution margin improving',
        'disclaimer_text': 'This report is for informational purposes only...',
        'research_source': 'AI4Finance FinRobot',
    }
    
    generate_equity_report_pdf('test_report.pdf', test_data)
