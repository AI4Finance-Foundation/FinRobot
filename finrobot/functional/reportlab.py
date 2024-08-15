import os
import traceback
from reportlab.lib import colors
from reportlab.lib import pagesizes
from reportlab.platypus import (
    SimpleDocTemplate,
    Frame,
    Paragraph,
    Image,
    PageTemplate,
    FrameBreak,
    Spacer,
    Table,
    TableStyle,
    NextPageTemplate,
    PageBreak,
)
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT

from ..data_source import FMPUtils, YFinanceUtils
from .analyzer import ReportAnalysisUtils
from typing import Annotated


class ReportLabUtils:

    def build_annual_report(
        ticker_symbol: Annotated[str, "ticker symbol"],
        save_path: Annotated[str, "path to save the annual report pdf"],
        operating_results: Annotated[
            str,
            "a paragraph of text: the company's income summarization from its financial report",
        ],
        market_position: Annotated[
            str,
            "a paragraph of text: the company's current situation and end market (geography), major customers (blue chip or not), market share from its financial report, avoid similar sentences also generated in the business overview section, classify it into either of the two",
        ],
        business_overview: Annotated[
            str,
            "a paragraph of text: the company's description and business highlights from its financial report",
        ],
        risk_assessment: Annotated[
            str,
            "a paragraph of text: the company's risk assessment from its financial report",
        ],
        competitors_analysis: Annotated[
            str,
            "a paragraph of text: the company's competitors analysis from its financial report and competitors' financial report",
        ],
        share_performance_image_path: Annotated[
            str, "path to the share performance image"
        ],
        pe_eps_performance_image_path: Annotated[
            str, "path to the PE and EPS performance image"
        ],
        filing_date: Annotated[str, "filing date of the analyzed financial report"],
    ) -> str:
        """
        Aggregate a company's business_overview, market_position, operating_results,
        risk assessment, competitors analysis and share performance, PE & EPS performance charts all into a PDF report.
        """
        try:
            # 2. 创建PDF并插入图像
            # 页面设置
            page_width, page_height = pagesizes.A4
            left_column_width = page_width * 2 / 3
            right_column_width = page_width - left_column_width
            margin = 4

            # 创建PDF文档路径
            pdf_path = (
                os.path.join(save_path, f"{ticker_symbol}_Equity_Research_report.pdf")
                if os.path.isdir(save_path)
                else save_path
            )
            os.makedirs(os.path.dirname(pdf_path), exist_ok=True)
            doc = SimpleDocTemplate(pdf_path, pagesize=pagesizes.A4)
        


            # 定义两个栏位的Frame
            frame_left = Frame(
                margin,
                margin,
                left_column_width - margin * 2,
                page_height - margin * 2,
                id="left",
            )
            frame_right = Frame(
                left_column_width,
                margin,
                right_column_width - margin * 2,
                page_height - margin * 2,
                id="right",
            )

            single_frame = Frame(margin, margin, page_width-margin*2, page_height-margin*2, id='single')
            single_column_layout = PageTemplate(id='OneCol', frames=[single_frame])

            left_column_width_p2 = (page_width - margin * 3) // 2
            right_column_width_p2 = left_column_width_p2
            frame_left_p2 = Frame(
                margin,
                margin,
                left_column_width_p2 - margin * 2,
                page_height - margin * 2,
                id="left",
            )
            frame_right_p2 = Frame(
                left_column_width_p2,
                margin,
                right_column_width_p2 - margin * 2,
                page_height - margin * 2,
                id="right",
            )

            #创建PageTemplate，并添加到文档
            page_template = PageTemplate(
                id="TwoColumns", frames=[frame_left, frame_right]
            )
            page_template_p2 = PageTemplate(
                id="TwoColumns_p2", frames=[frame_left_p2, frame_right_p2]
            )

             #Define single column Frame
            single_frame = Frame(
                margin,
                margin,
                page_width - 2 * margin,
                page_height - 2 * margin,
                id="single",
            )

            # Create a PageTemplate with a single column
            single_column_layout = PageTemplate(id="OneCol", frames=[single_frame])

            doc.addPageTemplates([page_template, single_column_layout, page_template_p2])

            styles = getSampleStyleSheet()

            # 自定义样式
            custom_style = ParagraphStyle(
                name="Custom",
                parent=styles["Normal"],
                fontName="Helvetica",
                fontSize=10,
                # leading=15,
                alignment=TA_JUSTIFY,
            )

            title_style = ParagraphStyle(
                name="TitleCustom",
                parent=styles["Title"],
                fontName="Helvetica-Bold",
                fontSize=16,
                leading=20,
                alignment=TA_LEFT,
                spaceAfter=10,
            )

            subtitle_style = ParagraphStyle(
                name="Subtitle",
                parent=styles["Heading2"],
                fontName="Helvetica-Bold",
                fontSize=14,
                leading=12,
                alignment=TA_LEFT,
                spaceAfter=6,
            )

            table_style2 = TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.white),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.white),
                    ("FONT", (0, 0), (-1, -1), "Helvetica", 7),
                    ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 14),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    # 所有单元格左对齐
                    ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                    # 标题栏下方添加横线
                    ("LINEBELOW", (0, 0), (-1, 0), 2, colors.black),
                    # 表格最下方添加横线
                    ("LINEBELOW", (0, -1), (-1, -1), 2, colors.black),
                ]
            )

            name = YFinanceUtils.get_stock_info(ticker_symbol)["shortName"]

            # 准备左栏和右栏内容
            content = []
            # 标题
            content.append(
                Paragraph(
                    f"Equity Research Report: {name}",
                    title_style,
                )
            )

            # 子标题
            content.append(Paragraph("Business Overview", subtitle_style))
            content.append(Paragraph(business_overview, custom_style))

            content.append(Paragraph("Market Position", subtitle_style))
            content.append(Paragraph(market_position, custom_style))
            
            content.append(Paragraph("Operating Results", subtitle_style))
            content.append(Paragraph(operating_results, custom_style))

            # content.append(Paragraph("Summarization", subtitle_style))
            df = FMPUtils.get_financial_metrics(ticker_symbol, years=5)
            df.reset_index(inplace=True)
            currency = YFinanceUtils.get_stock_info(ticker_symbol)["currency"]
            df.rename(columns={"index": f"FY ({currency} mn)"}, inplace=True)
            table_data = [["Financial Metrics"]]
            table_data += [df.columns.to_list()] + df.values.tolist()

            col_widths = [(left_column_width - margin * 4) / df.shape[1]] * df.shape[1]
            table = Table(table_data, colWidths=col_widths)
            table.setStyle(table_style2)
            content.append(table)

            content.append(FrameBreak())  # 用于从左栏跳到右栏

            table_style = TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.white),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.white),
                    ("FONT", (0, 0), (-1, -1), "Helvetica", 8),
                    ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 12),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    # 第一列左对齐
                    ("ALIGN", (0, 1), (0, -1), "LEFT"),
                    # 第二列右对齐
                    ("ALIGN", (1, 1), (1, -1), "RIGHT"),
                    # 标题栏下方添加横线
                    ("LINEBELOW", (0, 0), (-1, 0), 2, colors.black),
                ]
            )
            full_length = right_column_width - 2 * margin

            data = [
                ["FinRobot"],
                ["https://ai4finance.org/"],
                ["https://github.com/AI4Finance-Foundation/FinRobot"],
                [f"Report date: {filing_date}"],
            ]
            col_widths = [full_length]
            table = Table(data, colWidths=col_widths)
            table.setStyle(table_style)
            content.append(table)

            # content.append(Paragraph("", custom_style))
            content.append(Spacer(1, 0.15 * inch))
            key_data = ReportAnalysisUtils.get_key_data(ticker_symbol, filing_date)
            # 表格数据
            data = [["Key data", ""]]
            data += [[k, v] for k, v in key_data.items()]
            col_widths = [full_length // 3 * 2, full_length // 3]
            table = Table(data, colWidths=col_widths)
            table.setStyle(table_style)
            content.append(table)

            # 将Matplotlib图像添加到右栏

            # 历史股价
            data = [["Share Performance"]]
            col_widths = [full_length]
            table = Table(data, colWidths=col_widths)
            table.setStyle(table_style)
            content.append(table)

            plot_path = share_performance_image_path
            width = right_column_width
            height = width // 2
            content.append(Image(plot_path, width=width, height=height))

            # 历史PE和EPS
            data = [["PE & EPS"]]
            col_widths = [full_length]
            table = Table(data, colWidths=col_widths)
            table.setStyle(table_style)
            content.append(table)

            plot_path = pe_eps_performance_image_path
            width = right_column_width
            height = width // 2
            content.append(Image(plot_path, width=width, height=height))

            # # 开始新的一页
            content.append(NextPageTemplate("OneCol"))
            content.append(PageBreak())
            
            content.append(Paragraph("Risk Assessment", subtitle_style))
            content.append(Paragraph(risk_assessment, custom_style))

            content.append(Paragraph("Competitors Analysis", subtitle_style))
            content.append(Paragraph(competitors_analysis, custom_style))
            # def add_table(df, title):
            #     df = df.applymap(lambda x: "{:.2f}".format(x) if isinstance(x, float) else x)
            #     # df.columns = [col.strftime('%Y') for col in df.columns]
            #     # df.reset_index(inplace=True)
            #     # currency = ra.info['currency']
            #     df.rename(columns={"index": "segment"}, inplace=True)
            #     table_data = [[title]]
            #     table_data += [df.columns.to_list()] + df.values.tolist()

            #     table = Table(table_data)
            #     table.setStyle(table_style2)
            #     num_columns = len(df.columns)

            #     column_width = (page_width - 4 * margin) / (num_columns + 1)
            #     first_column_witdh = column_width * 2
            #     table._argW = [first_column_witdh] + [column_width] * (num_columns - 1)

            #     content.append(table)
            #     content.append(Spacer(1, 0.15 * inch))

            # if os.path.exists(f"{ra.project_dir}/outer_resource/"):
            #     Revenue10Q = pd.read_csv(
            #         f"{ra.project_dir}/outer_resource/Revenue10Q.csv",
            #     )
            #     # del Revenue10K['FY2018']
            #     # del Revenue10K['FY2019']
            #     add_table(Revenue10Q, "Revenue")

            #     Ratio10Q = pd.read_csv(
            #         f"{ra.project_dir}/outer_resource/Ratio10Q.csv",
            #     )
            #     # del Ratio10K['FY2018']
            #     # del Ratio10K['FY2019']
            #     add_table(Ratio10Q, "Ratio")

            #     Yoy10Q = pd.read_csv(
            #         f"{ra.project_dir}/outer_resource/Yoy10Q.csv",
            #     )
            #     # del Yoy10K['FY2018']
            #     # del Yoy10K['FY2019']
            #     add_table(Yoy10Q, "Yoy")

            #     plot_path = os.path.join(f"{ra.project_dir}/outer_resource/", "segment.png")
            #     width = page_width - 2 * margin
            #     height = width * 3 // 5
            #     content.append(Image(plot_path, width=width, height=height))

            # # 第二页及之后内容，使用单栏布局
            # df = ra.get_income_stmt()
            # df = df[df.columns[:3]]
            # def convert_if_money(value):
            #     if np.abs(value) >= 1000000:
            #         return value / 1000000
            #     else:
            #         return value

            # # 应用转换函数到DataFrame的每列
            # df = df.applymap(convert_if_money)

            # df.columns = [col.strftime('%Y') for col in df.columns]
            # df.reset_index(inplace=True)
            # currency = ra.info['currency']
            # df.rename(columns={'index': f'FY ({currency} mn)'}, inplace=True)  # 可选：重命名索引列为“序号”
            # table_data = [["Income Statement"]]
            # table_data += [df.columns.to_list()] + df.values.tolist()

            # table = Table(table_data)
            # table.setStyle(table_style2)
            # content.append(table)

            # content.append(FrameBreak())  # 用于从左栏跳到右栏

            # df = ra.get_cash_flow()
            # df = df[df.columns[:3]]

            # df = df.applymap(convert_if_money)

            # df.columns = [col.strftime('%Y') for col in df.columns]
            # df.reset_index(inplace=True)
            # currency = ra.info['currency']
            # df.rename(columns={'index': f'FY ({currency} mn)'}, inplace=True)  # 可选：重命名索引列为“序号”
            # table_data = [["Cash Flow Sheet"]]
            # table_data += [df.columns.to_list()] + df.values.tolist()

            # table = Table(table_data)
            # table.setStyle(table_style2)
            # content.append(table)
            # # content.append(Paragraph('This is a single column on the second page', custom_style))
            # # content.append(Spacer(1, 0.2*inch))
            # # content.append(Paragraph('More content in the single column.', custom_style))

            # 构建PDF文档
            doc.build(content)

            return "Annual report generated successfully."

        except Exception:
            return traceback.format_exc()
