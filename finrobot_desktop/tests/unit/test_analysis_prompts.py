"""Tests for standalone financial analysis prompts and prompt builder.

Verifies prompt construction produces correctly formatted prompts with
embedded financial data, and rejects invalid analysis types.
Also tests data validation (Fix 3.1), EV/EBITDA computation (Fix 3.2),
and D&A approximation warnings (Fix 3.3).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from finagent.engine.analysis.prompts import (
    ANALYSIS_TYPES,
    build_analysis_prompt,
    _build_financials_table,
    _validate_analysis_data,
    _fmt_num,
    _fmt_pct,
)
from finagent.engine.data.interface import DataResult


# ------------------------------------------------------------------ #
# Formatting helpers                                                 #
# ------------------------------------------------------------------ #


class TestFmtNum:
    def test_billions(self) -> None:
        assert _fmt_num(3.5e9) == "$3.5B"

    def test_millions(self) -> None:
        assert _fmt_num(125e6) == "$125.0M"

    def test_trillions(self) -> None:
        assert _fmt_num(2.1e12) == "$2.1T"

    def test_thousands(self) -> None:
        assert _fmt_num(45_000) == "$45.0K"

    def test_negative(self) -> None:
        assert _fmt_num(-500e6) == "-$500.0M"

    def test_none(self) -> None:
        assert _fmt_num(None) == "N/A"


class TestFmtPct:
    def test_percentage(self) -> None:
        assert _fmt_pct(0.253) == "25.3%"

    def test_none(self) -> None:
        assert _fmt_pct(None) == "N/A"


# ------------------------------------------------------------------ #
# Financials table builder                                           #
# ------------------------------------------------------------------ #


class TestBuildFinancialsTable:
    def test_includes_revenue(self) -> None:
        table = _build_financials_table({"revenue": 400e9})
        assert "$400.0B" in table
        assert "Revenue" in table

    def test_includes_margins(self) -> None:
        table = _build_financials_table(
            {
                "gross_margin": 0.45,
                "operating_margin": 0.30,
            }
        )
        assert "45.0%" in table
        assert "30.0%" in table

    def test_historical_data(self) -> None:
        data = {
            "revenue": 400e9,
            "yearly_data": [
                {"fiscal_year": 2023, "revenue": 380e9, "net_income": 90e9},
                {"fiscal_year": 2024, "revenue": 400e9, "net_income": 100e9},
            ],
        }
        table = _build_financials_table(data)
        assert "2023" in table
        assert "2024" in table
        assert "Historical Annual Data" in table


# ------------------------------------------------------------------ #
# Prompt builder                                                     #
# ------------------------------------------------------------------ #


class TestBuildAnalysisPrompt:
    def test_all_types_produce_prompts(self) -> None:
        data = {"revenue": 100e9, "ebitda": 30e9, "gross_margin": 0.4}
        for atype in ANALYSIS_TYPES:
            prompt = build_analysis_prompt(atype, "AAPL", data)
            assert "AAPL" in prompt
            assert len(prompt) > 100

    def test_income_prompt_has_framework(self) -> None:
        data = {"revenue": 400e9, "ebitda": 130e9, "net_income": 100e9}
        prompt = build_analysis_prompt("income", "AAPL", data)
        assert "Revenue Analysis" in prompt
        assert "Operating Leverage" in prompt
        assert "$400.0B" in prompt

    def test_balance_prompt_has_debt_analysis(self) -> None:
        data = {"total_debt": 100e9, "total_cash": 60e9}
        prompt = build_analysis_prompt("balance", "MSFT", data)
        assert "Capital Structure" in prompt
        assert "MSFT" in prompt

    def test_competitors_prompt_includes_peer_table(self) -> None:
        data = {"revenue": 400e9}
        peer_table = "| MSFT | $200B | $80B |"
        prompt = build_analysis_prompt("competitors", "AAPL", data, peer_table=peer_table)
        assert "Peer Data" in prompt
        assert "MSFT" in prompt

    def test_invalid_type_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown analysis type"):
            build_analysis_prompt("invalid", "AAPL", {})

    def test_risk_prompt_has_categories(self) -> None:
        data = {"revenue": 50e9, "total_debt": 20e9}
        prompt = build_analysis_prompt("risk", "TSLA", data)
        assert "Operational Risk" in prompt
        assert "Financial Risk" in prompt
        assert "Market Risk" in prompt


# ------------------------------------------------------------------ #
# Fix 3.1: Data validation                                          #
# ------------------------------------------------------------------ #


def _make_result(data: dict, ticker: str = "AAPL", provider: str = "yfinance") -> DataResult:
    """Helper to build a DataResult for validation tests."""
    return DataResult(
        data=data,
        provider=provider,
        ticker=ticker,
        data_type="financials",
        timestamp=datetime.now(tz=timezone.utc),
    )


class TestValidateAnalysisData:
    def test_rejects_error_payload(self) -> None:
        result = _make_result({"error": "API rate limit exceeded"})
        with pytest.raises(ValueError, match="Data fetch failed.*API rate limit"):
            _validate_analysis_data(result)

    def test_rejects_empty_data(self) -> None:
        result = _make_result({})
        with pytest.raises(ValueError, match="No financial data returned"):
            _validate_analysis_data(result)

    def test_rejects_missing_revenue(self) -> None:
        result = _make_result({"ebitda": 30e9, "market_cap": 2e12})
        with pytest.raises(ValueError, match="missing.*revenue"):
            _validate_analysis_data(result)

    def test_rejects_zero_revenue(self) -> None:
        result = _make_result({"revenue": 0, "market_cap": 2e12})
        with pytest.raises(ValueError, match="Revenue is 0"):
            _validate_analysis_data(result)

    def test_rejects_none_revenue(self) -> None:
        result = _make_result({"revenue": None, "market_cap": 2e12})
        with pytest.raises(ValueError, match="Revenue is None"):
            _validate_analysis_data(result)

    def test_accepts_valid_data(self) -> None:
        result = _make_result({"revenue": 400e9, "ebitda": 130e9, "market_cap": 3e12})
        _validate_analysis_data(result)  # should not raise

    def test_error_message_includes_ticker_and_provider(self) -> None:
        result = _make_result(
            {"error": "timeout"},
            ticker="MSFT",
            provider="fmp",
        )
        with pytest.raises(ValueError, match="MSFT.*fmp.*timeout"):
            _validate_analysis_data(result)


# ------------------------------------------------------------------ #
# Fix 3.2: EV/EBITDA in financials table                            #
# ------------------------------------------------------------------ #


class TestEVEBITDAComputation:
    def test_ev_computed_when_all_components_present(self) -> None:
        data = {
            "revenue": 400e9,
            "ebitda": 130e9,
            "market_cap": 3e12,
            "total_debt": 100e9,
            "total_cash": 60e9,
        }
        table = _build_financials_table(data)
        # EV = 3T + 100B - 60B = 3.04T
        assert "Enterprise Value" in table
        assert "$3.0T" in table
        # EV/EBITDA = 3.04T / 130B ≈ 23.4x
        assert "EV/EBITDA" in table
        assert "23.4x" in table

    def test_ev_skipped_when_debt_missing(self) -> None:
        data = {
            "revenue": 400e9,
            "ebitda": 130e9,
            "market_cap": 3e12,
            "total_cash": 60e9,
            # total_debt missing
        }
        table = _build_financials_table(data)
        assert "| Enterprise Value | N/A |" in table
        assert "EV unavailable" in table
        assert "total_debt" in table

    def test_ev_skipped_when_cash_missing(self) -> None:
        data = {
            "revenue": 400e9,
            "ebitda": 130e9,
            "market_cap": 3e12,
            "total_debt": 100e9,
            # total_cash missing
        }
        table = _build_financials_table(data)
        assert "| Enterprise Value | N/A |" in table
        assert "EV unavailable" in table
        assert "total_cash" in table

    def test_ev_ebitda_na_when_ebitda_zero(self) -> None:
        """N16: EV/EBITDA explains why it's N/A when EBITDA <= 0."""
        data = {
            "revenue": 400e9,
            "ebitda": 0,
            "market_cap": 3e12,
            "total_debt": 100e9,
            "total_cash": 60e9,
        }
        table = _build_financials_table(data)
        assert "negative EBITDA" in table
        # EV itself should still be computed
        assert "$" in table.split("Enterprise Value")[1].split("\n")[0]

    def test_ev_ebitda_na_when_ebitda_negative(self) -> None:
        """N16: Negative EBITDA explicitly noted."""
        data = {
            "revenue": 400e9,
            "ebitda": -5e9,
            "market_cap": 3e12,
            "total_debt": 100e9,
            "total_cash": 60e9,
        }
        table = _build_financials_table(data)
        assert "negative EBITDA" in table

    def test_ev_ebitda_na_reason_when_ev_unavailable(self) -> None:
        """N16: When EV itself is N/A, EV/EBITDA says 'EV unavailable'."""
        data = {
            "revenue": 400e9,
            "ebitda": 130e9,
            "market_cap": 3e12,
            # total_debt missing
            "total_cash": 60e9,
        }
        table = _build_financials_table(data)
        assert "EV unavailable" in table

    def test_no_default_zero_for_missing_debt(self) -> None:
        """Ensure missing debt is NOT defaulted to 0 to produce a fake EV."""
        data = {
            "revenue": 400e9,
            "ebitda": 130e9,
            "market_cap": 3e12,
            # total_debt and total_cash both missing
        }
        table = _build_financials_table(data)
        assert "EV unavailable" in table
        assert "total_debt" in table
        assert "total_cash" in table


# ------------------------------------------------------------------ #
# Fix 3.3: D&A approximation warning                                #
# ------------------------------------------------------------------ #


class TestDAAproximationWarning:
    def test_warning_in_table_when_da_missing(self) -> None:
        data = {"revenue": 400e9, "ebitda": 130e9}
        table = _build_financials_table(data)
        assert "Data Quality Notes" in table
        assert "D&A data unavailable" in table
        assert "simplified formula" in table
        assert "10-20%" in table

    def test_no_warning_when_da_present(self) -> None:
        data = {"revenue": 400e9, "ebitda": 130e9, "depreciation_amortization": 20e9}
        table = _build_financials_table(data)
        assert "D&A data unavailable" not in table

    def test_cashflow_prompt_instructs_warning(self) -> None:
        data = {"revenue": 400e9, "ebitda": 130e9}
        prompt = build_analysis_prompt("cashflow", "AAPL", data)
        assert "Data Limitation" in prompt
        assert "simplified formula" in prompt

    def test_cashflow_prompt_mentions_standard_formula(self) -> None:
        data = {"revenue": 400e9, "depreciation_amortization": 20e9}
        prompt = build_analysis_prompt("cashflow", "AAPL", data)
        assert "EBIT(1-T) + D&A" in prompt
