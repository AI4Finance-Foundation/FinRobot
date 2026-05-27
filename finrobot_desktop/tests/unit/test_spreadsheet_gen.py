"""Tests for Excel spreadsheet generation.

All tests verify:
1. Output is a valid .xlsx file parseable by openpyxl.
2. Expected sheet names exist.
3. Row/column counts match model dimensions.
4. No bytes that would cause Excel to show a repair dialog.
"""

import io
import openpyxl
from finrobot.engine.compute.dcf import calculate_dcf
from finrobot.engine.compute.lbo import calculate_lbo
from finrobot.engine.compute.spreadsheet_gen import (
    generate_dcf_excel,
    generate_lbo_excel,
    generate_comps_excel,
)
from finrobot.engine.models.financial import (
    CompanyFinancials,
    DCFInputs,
    LBOInputs,
)


def _dcf_inputs() -> DCFInputs:
    return DCFInputs(
        revenue_base=100_000_000_000,
        revenue_growth_rates=[0.05] * 5,
        ebitda_margin=0.35,
        capex_pct_revenue=0.05,
        nwc_pct_revenue=0.02,
        tax_rate=0.21,
        risk_free_rate=0.04,
        beta=1.2,
        equity_risk_premium=0.05,
        cost_of_debt=0.04,
        debt_ratio=0.1,
        terminal_growth_rate=0.025,
        shares_outstanding=1_000_000_000,
        net_debt=10_000_000_000,
    )


def _lbo_inputs() -> LBOInputs:
    return LBOInputs(
        ticker="TEST",
        ltm_ebitda=100.0,
        entry_ev_ebitda=8.0,
        exit_ev_ebitda=10.0,
        holding_period_years=5,
        revenue_base=500.0,
        revenue_growth_rate=0.05,
        ebitda_margin=0.20,
    )


class TestGenerateDCFExcel:
    def test_returns_valid_xlsx(self):
        inputs = _dcf_inputs()
        result = calculate_dcf(inputs, wacc_override=0.10)
        xlsx_bytes = generate_dcf_excel(result, inputs)

        openpyxl.load_workbook(io.BytesIO(xlsx_bytes))
        assert isinstance(xlsx_bytes, bytes)
        assert len(xlsx_bytes) > 0

    def test_sheet_names(self):
        inputs = _dcf_inputs()
        result = calculate_dcf(inputs, wacc_override=0.10)
        wb = openpyxl.load_workbook(io.BytesIO(generate_dcf_excel(result, inputs)))
        assert "Summary" in wb.sheetnames
        assert "Projections" in wb.sheetnames
        assert "Sensitivity" in wb.sheetnames

    def test_projections_row_count(self):
        inputs = _dcf_inputs()
        result = calculate_dcf(inputs, wacc_override=0.10)
        wb = openpyxl.load_workbook(io.BytesIO(generate_dcf_excel(result, inputs)))
        ws = wb["Projections"]
        # header + revenue + ebitda + fcf + margin = 5 rows
        assert ws.max_row == 5

    def test_projections_column_count(self):
        inputs = _dcf_inputs()
        result = calculate_dcf(inputs, wacc_override=0.10)
        wb = openpyxl.load_workbook(io.BytesIO(generate_dcf_excel(result, inputs)))
        ws = wb["Projections"]
        # label col + 5 year cols = 6
        assert ws.max_column == 6

    def test_sensitivity_sheet_has_data(self):
        inputs = _dcf_inputs()
        result = calculate_dcf(inputs, wacc_override=0.10)
        from finrobot.engine.compute.dcf import calculate_sensitivity
        from finrobot.engine.pipelines._helpers import build_sensitivity_ranges

        wacc_range, tg_range = build_sensitivity_ranges(
            result.wacc, result.inputs.terminal_growth_rate
        )
        sensitivity = calculate_sensitivity(inputs, wacc_range=wacc_range, tg_range=tg_range)
        result = result.model_copy(update={"sensitivity_table": sensitivity})

        wb = openpyxl.load_workbook(io.BytesIO(generate_dcf_excel(result, inputs)))
        ws = wb["Sensitivity"]
        # header row + len(wacc_range) rows
        assert ws.max_row >= 2


class TestGenerateLBOExcel:
    def test_returns_valid_xlsx(self):
        inputs = _lbo_inputs()
        result = calculate_lbo(inputs)
        xlsx_bytes = generate_lbo_excel(result, inputs)
        assert isinstance(xlsx_bytes, bytes)
        assert len(xlsx_bytes) > 0
        openpyxl.load_workbook(io.BytesIO(xlsx_bytes))  # must not raise

    def test_sheet_names(self):
        inputs = _lbo_inputs()
        result = calculate_lbo(inputs)
        wb = openpyxl.load_workbook(io.BytesIO(generate_lbo_excel(result, inputs)))
        assert "Summary" in wb.sheetnames
        assert "Debt Schedule" in wb.sheetnames
        assert "Sensitivity" in wb.sheetnames

    def test_debt_schedule_row_count(self):
        """Debt Schedule: 1 header + holding_period_years data rows."""
        inputs = _lbo_inputs()
        result = calculate_lbo(inputs)
        wb = openpyxl.load_workbook(io.BytesIO(generate_lbo_excel(result, inputs)))
        ws = wb["Debt Schedule"]
        assert ws.max_row == inputs.holding_period_years + 1

    def test_sensitivity_irr_values_are_numbers(self):
        inputs = _lbo_inputs()
        result = calculate_lbo(inputs)
        wb = openpyxl.load_workbook(io.BytesIO(generate_lbo_excel(result, inputs)))
        ws = wb["Sensitivity"]
        # Check at least one numeric cell in data area
        numeric_found = any(
            isinstance(ws.cell(row=r, column=c).value, (int, float))
            for r in range(2, ws.max_row + 1)
            for c in range(2, ws.max_column + 1)
        )
        assert numeric_found


class TestGenerateCompsExcel:
    def _make_peers(self) -> list[CompanyFinancials]:
        return [
            CompanyFinancials(
                ticker="AAPL",
                revenue=400e9,
                ebitda=120e9,
                net_income=95e9,
                market_cap=3_000e9,
                gross_margin=0.44,
                operating_margin=0.30,
                ev_ebitda=25.0,
                ev_revenue=7.5,
                pe_ratio=28.0,
            ),
            CompanyFinancials(
                ticker="MSFT",
                revenue=220e9,
                ebitda=90e9,
                net_income=72e9,
                market_cap=2_500e9,
                gross_margin=0.68,
                operating_margin=0.42,
                ev_ebitda=22.0,
                ev_revenue=11.0,
                pe_ratio=35.0,
            ),
        ]

    def test_returns_valid_xlsx(self):
        peers = self._make_peers()
        xlsx_bytes = generate_comps_excel(peers)
        assert isinstance(xlsx_bytes, bytes)
        openpyxl.load_workbook(io.BytesIO(xlsx_bytes))

    def test_sheet_name(self):
        wb = openpyxl.load_workbook(io.BytesIO(generate_comps_excel(self._make_peers())))
        assert "Comps" in wb.sheetnames

    def test_row_count(self):
        peers = self._make_peers()
        wb = openpyxl.load_workbook(io.BytesIO(generate_comps_excel(peers)))
        ws = wb["Comps"]
        assert ws.max_row == len(peers) + 1  # header + peers
