"""Tests for standalone financial analysis prompts and prompt builder.

Verifies prompt construction produces correctly formatted prompts with
embedded financial data, and rejects invalid analysis types.
"""

from __future__ import annotations

import pytest

from finagent.engine.analysis.prompts import (
    ANALYSIS_TYPES,
    build_analysis_prompt,
    _build_financials_table,
    _fmt_num,
    _fmt_pct,
)


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
        table = _build_financials_table({
            "gross_margin": 0.45,
            "operating_margin": 0.30,
        })
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
