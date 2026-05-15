"""Excel workbook generation for DCF, LBO, and Comps models.

What LLM cannot do:
- Generate binary .xlsx with formula cells, frozen panes, and conditional formatting.
- LLM can output CSV at most; openpyxl produces real Excel files.

Formatting conventions:
- USD values: "$#,##0" (millions rounded to whole dollars)
- Percentages: "0.0%"
- Multiples: "0.0x"
- Header row: bold, fill #1a365d (navy), white font
- Freeze panes at row 2 on all sheets
"""

from __future__ import annotations

import io
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.formatting.rule import CellIsRule
from openpyxl.utils import get_column_letter

from finagent.engine.models.financial import (
    CompanyFinancials,
    DCFInputs,
    DCFResult,
    LBOInputs,
    LBOResult,
)

# ---- Style constants ----
_HEADER_FILL = PatternFill("solid", fgColor="1a365d")
_HEADER_FONT = Font(bold=True, color="FFFFFF")
_BOLD = Font(bold=True)
_FMT_USD = '"$"#,##0'
_FMT_PCT = "0.0%"
_FMT_MULT = '0.0"x"'
_FMT_NUMBER = "#,##0"

_GREEN_FILL = PatternFill("solid", fgColor="C6EFCE")
_RED_FILL = PatternFill("solid", fgColor="FFC7CE")
_YELLOW_FILL = PatternFill("solid", fgColor="FFEB9C")


def generate_dcf_excel(dcf_result: DCFResult, dcf_inputs: DCFInputs) -> bytes:
    """Return raw .xlsx bytes for a 3-sheet DCF model workbook.

    Sheets: Summary | Projections | Sensitivity
    """
    wb = Workbook()

    _build_dcf_summary(wb.active, dcf_result, dcf_inputs)
    wb.active.title = "Summary"

    proj_ws = wb.create_sheet("Projections")
    _build_dcf_projections(proj_ws, dcf_result, dcf_inputs)

    sens_ws = wb.create_sheet("Sensitivity")
    _build_dcf_sensitivity(sens_ws, dcf_result)

    return _wb_to_bytes(wb)


def generate_lbo_excel(lbo_result: LBOResult, lbo_inputs: LBOInputs) -> bytes:
    """Return raw .xlsx bytes for a 3-sheet LBO model workbook.

    Sheets: Summary | Debt Schedule | Sensitivity
    """
    wb = Workbook()

    _build_lbo_summary(wb.active, lbo_result, lbo_inputs)
    wb.active.title = "Summary"

    debt_ws = wb.create_sheet("Debt Schedule")
    _build_lbo_debt_schedule(debt_ws, lbo_result)

    sens_ws = wb.create_sheet("Sensitivity")
    _build_lbo_sensitivity(sens_ws, lbo_result)

    return _wb_to_bytes(wb)


def generate_comps_excel(peers: list[CompanyFinancials]) -> bytes:
    """Return raw .xlsx bytes for a comparable companies multiples table."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Comps"
    _build_comps_table(ws, peers)
    return _wb_to_bytes(wb)


# ---------------------------------------------------------------------------
# DCF sheet builders
# ---------------------------------------------------------------------------


def _build_dcf_summary(ws: Any, result: DCFResult, inputs: DCFInputs) -> None:
    rows = [
        ("Metric", "Value"),
        ("Implied Price", result.implied_price),
        ("WACC", result.wacc),
        ("Enterprise Value ($M)", result.enterprise_value / 1e6),
        ("Equity Value ($M)", result.equity_value / 1e6),
        ("Terminal Value ($M)", result.terminal_value / 1e6),
        ("PV of FCFs ($M)", result.pv_fcf_total / 1e6),
        ("Projection Years", result.projection_years),
        ("Terminal Growth Rate", inputs.terminal_growth_rate),
        ("EBITDA Margin", inputs.ebitda_margin),
    ]
    _write_rows(ws, rows)
    _apply_header(ws, 1)
    ws.freeze_panes = "A2"

    # Format column B values
    fmt_map = {
        2: _FMT_USD,
        3: _FMT_PCT,
        4: _FMT_USD,
        5: _FMT_USD,
        6: _FMT_USD,
        7: _FMT_USD,
        9: _FMT_PCT,
        10: _FMT_PCT,
    }
    for row_idx, fmt in fmt_map.items():
        ws.cell(row=row_idx, column=2).number_format = fmt

    _auto_width(ws)


def _build_dcf_projections(ws: Any, result: DCFResult, inputs: DCFInputs) -> None:
    n = result.projection_years
    years = list(range(1, n + 1))
    header = ["Metric"] + [f"Year {y}" for y in years]
    ws.append(header)
    _apply_header(ws, 1)
    ws.freeze_panes = "B2"

    rev_row = ["Revenue ($M)"] + [r / 1e6 for r in result.projected_revenue]
    ebitda_row = ["EBITDA ($M)"] + [e / 1e6 for e in result.projected_ebitda]
    fcf_row = ["FCF ($M)"] + [f / 1e6 for f in result.projected_fcf]

    ws.append(rev_row)
    ws.append(ebitda_row)
    ws.append(fcf_row)

    margin_row: list[str | float] = ["EBITDA Margin"]
    for r, e in zip(result.projected_revenue, result.projected_ebitda):
        margin_row.append(e / r if r else 0.0)
    ws.append(margin_row)

    for row in ws.iter_rows(min_row=2, max_row=4, min_col=2):
        for cell in row:
            cell.number_format = _FMT_USD

    for cell in ws[5][1:]:
        cell.number_format = _FMT_PCT

    _auto_width(ws)


def _build_dcf_sensitivity(ws: Any, result: DCFResult) -> None:
    if not result.sensitivity_table:
        ws.append(["No sensitivity data available"])
        return

    table = result.sensitivity_table
    wacc_vals = table.get("wacc_values", table.get("wacc_range", []))
    tg_vals = table.get("tg_values", table.get("tg_range", []))
    prices = table.get("implied_prices", [])

    header = ["WACC \\ TG"] + [f"{tg:.1%}" for tg in tg_vals]
    ws.append(header)
    _apply_header(ws, 1)
    ws.freeze_panes = "B2"

    for i, (wacc, price_row) in enumerate(zip(wacc_vals, prices)):
        row_data = [f"{wacc:.1%}"] + [p for p in price_row]
        ws.append(row_data)

    # Conditional formatting on price cells
    if wacc_vals and tg_vals:
        data_range = f"B2:{get_column_letter(1 + len(tg_vals))}{1 + len(wacc_vals)}"
        ws.conditional_formatting.add(
            data_range,
            CellIsRule(operator="greaterThan", formula=["0"], fill=_GREEN_FILL),
        )

    for row in ws.iter_rows(min_row=2, min_col=2):
        for cell in row:
            cell.number_format = _FMT_USD

    _auto_width(ws)


# ---------------------------------------------------------------------------
# LBO sheet builders
# ---------------------------------------------------------------------------


def _build_lbo_summary(ws: Any, result: LBOResult, inputs: LBOInputs) -> None:
    rows = [
        ("Metric", "Value"),
        ("Entry EV ($M)", result.entry_ev / 1e6),
        ("Entry Debt ($M)", result.entry_debt / 1e6),
        ("Entry Equity ($M)", result.entry_equity / 1e6),
        ("Exit EV ($M)", result.exit_ev / 1e6),
        ("Exit Equity ($M)", result.exit_equity / 1e6),
        ("MOIC", result.moic),
        ("IRR", result.irr),
        ("Holding Period (yrs)", inputs.holding_period_years),
        ("Entry EV/EBITDA", inputs.entry_ev_ebitda),
        ("Exit EV/EBITDA", inputs.exit_ev_ebitda),
        ("Leverage Multiple", inputs.leverage_multiple),
        ("Interest Rate", inputs.interest_rate),
    ]
    _write_rows(ws, rows)
    _apply_header(ws, 1)
    ws.freeze_panes = "A2"

    fmt_map = {
        2: _FMT_USD,
        3: _FMT_USD,
        4: _FMT_USD,
        5: _FMT_USD,
        6: _FMT_USD,
        7: _FMT_MULT,
        8: _FMT_PCT,
        10: _FMT_MULT,
        11: _FMT_MULT,
        12: _FMT_MULT,
        13: _FMT_PCT,
    }
    for row_idx, fmt in fmt_map.items():
        ws.cell(row=row_idx, column=2).number_format = fmt

    _auto_width(ws)


def _build_lbo_debt_schedule(ws: Any, result: LBOResult) -> None:
    header = [
        "Year",
        "Revenue ($M)",
        "EBITDA ($M)",
        "DA ($M)",
        "EBIT ($M)",
        "Interest ($M)",
        "Net Income ($M)",
        "FCF ($M)",
        "Debt Paydown ($M)",
        "Ending Debt ($M)",
    ]
    ws.append(header)
    _apply_header(ws, 1)
    ws.freeze_panes = "A2"

    for yr in result.schedule:
        ws.append(
            [
                yr.year,
                yr.revenue / 1e6,
                yr.ebitda / 1e6,
                yr.da / 1e6,
                yr.ebit / 1e6,
                yr.interest_expense / 1e6,
                yr.net_income / 1e6,
                yr.fcf / 1e6,
                yr.total_debt_paydown / 1e6,
                yr.ending_debt / 1e6,
            ]
        )

    for row in ws.iter_rows(min_row=2, min_col=2):
        for cell in row:
            cell.number_format = _FMT_USD

    _auto_width(ws)


def _build_lbo_sensitivity(ws: Any, result: LBOResult) -> None:
    sens = result.sensitivity
    if not sens:
        ws.append(["No sensitivity data available"])
        return

    entry_multiples = sens.get("entry_multiples", [])
    exit_multiples = sens.get("exit_multiples", [])
    irr_grid = sens.get("irr_grid", [])

    header = ["Entry \\ Exit"] + [f"{e:.1f}x" for e in exit_multiples]
    ws.append(header)
    _apply_header(ws, 1)
    ws.freeze_panes = "B2"

    for i, (entry, irr_row) in enumerate(zip(entry_multiples, irr_grid)):
        row_data = [f"{entry:.1f}x"] + [(v if v is not None else "") for v in irr_row]
        ws.append(row_data)

    # Format IRR cells as percentage
    for row in ws.iter_rows(min_row=2, min_col=2):
        for cell in row:
            if isinstance(cell.value, (int, float)):
                cell.number_format = _FMT_PCT

    _auto_width(ws)


# ---------------------------------------------------------------------------
# Comps sheet builder
# ---------------------------------------------------------------------------


def _build_comps_table(ws: Any, peers: list[CompanyFinancials]) -> None:
    header = [
        "Ticker",
        "Revenue ($M)",
        "EBITDA ($M)",
        "Market Cap ($M)",
        "EV/EBITDA",
        "EV/Revenue",
        "P/E",
    ]
    ws.append(header)
    _apply_header(ws, 1)
    ws.freeze_panes = "A2"

    for p in peers:
        ws.append(
            [
                p.ticker,
                p.revenue / 1e6 if p.revenue else "",
                p.ebitda / 1e6 if p.ebitda else "",
                p.market_cap / 1e6 if p.market_cap else "",
                p.ev_ebitda,
                p.ev_revenue,
                p.pe_ratio,
            ]
        )

    for col_idx in range(2, 5):
        for cell in ws[get_column_letter(col_idx)]:
            if isinstance(cell.value, (int, float)):
                cell.number_format = _FMT_USD

    for col_idx in range(5, 8):
        for cell in ws[get_column_letter(col_idx)]:
            if isinstance(cell.value, (int, float)):
                cell.number_format = _FMT_MULT

    _auto_width(ws)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_rows(ws: Any, rows: list[tuple[str, Any]]) -> None:
    for row in rows:
        ws.append(list(row))


def _apply_header(ws: Any, row_idx: int) -> None:
    for cell in ws[row_idx]:
        cell.font = _HEADER_FONT
        cell.fill = _HEADER_FILL
        cell.alignment = Alignment(horizontal="center")


def _auto_width(ws: Any, *, min_width: int = 10, max_width: int = 40) -> None:
    """Set column widths based on the longest value in each column.

    openpyxl does not have a native auto-fit. This approximates it by
    scanning all rows and picking the widest string representation per
    column, then clamping between min_width and max_width.
    """
    for col_cells in ws.columns:
        best = min_width
        for cell in col_cells:
            if cell.value is not None:
                # Number-formatted cells are typically shorter on screen
                # than their raw repr, but the header text is a good proxy.
                length = len(str(cell.value)) + 2  # +2 for padding
                if length > best:
                    best = length
        col_letter = get_column_letter(col_cells[0].column)
        ws.column_dimensions[col_letter].width = min(best, max_width)


def _wb_to_bytes(wb: Workbook) -> bytes:
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
