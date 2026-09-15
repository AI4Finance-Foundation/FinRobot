"""Tests for standalone financial analysis prompts and prompt builder.

ADR-0006 Step 6: _build_financials_table, build_analysis_prompt, and
_validate_analysis_data now accept NormalizedFinancials instead of raw dicts.
Fixtures use normalize_financials() to build canonical inputs.

Verifies prompt construction produces correctly formatted prompts with
embedded financial data, and rejects invalid analysis types.
Also tests data validation, EV/EBITDA computation, and D&A approximation warnings.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from finrobot.engine.analysis.prompts import (
    ANALYSIS_TYPES,
    build_analysis_prompt,
    _build_financials_table,
    _fetch_peer_table,
    _validate_analysis_data,
    _fmt_num,
    _fmt_pct,
)
from finrobot.engine.data.interface import DataResult
from finrobot.engine.data.normalize.financials import normalize_financials


# ------------------------------------------------------------------ #
# Fixture helpers                                                     #
# ------------------------------------------------------------------ #


def _make_fin(**overrides: object):
    """Build a NormalizedFinancials from representative raw dict fields."""
    data: dict[str, object] = {
        "revenue": 400e9,
        "ebitda": 130e9,
        "net_income": 100e9,
        "gross_margin": 0.43,
        "operating_margin": 0.30,
        "market_cap": 3e12,
        "shares_outstanding": 15e9,
        "total_debt": 100e9,
        "total_cash": 60e9,
    }
    data.update(overrides)
    raw = DataResult(
        data=data,
        provider="yfinance",
        ticker="AAPL",
        data_type="financials",
        timestamp=datetime.now(tz=timezone.utc),
    )
    return normalize_financials(raw)


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
        table = _build_financials_table(_make_fin(revenue=400e9))
        assert "$400.0B" in table
        assert "Revenue" in table

    def test_includes_margins(self) -> None:
        table = _build_financials_table(_make_fin(gross_margin=0.45, operating_margin=0.30))
        assert "45.0%" in table
        assert "30.0%" in table

    def test_no_historical_section(self) -> None:
        """NormalizedFinancials does not carry yearly_data — no historical table."""
        table = _build_financials_table(_make_fin())
        # Historical Annual Data section was only in the raw-dict path; canonical
        # model is a single snapshot — no per-year table.
        assert "Historical Annual Data" not in table


# ------------------------------------------------------------------ #
# Prompt builder                                                     #
# ------------------------------------------------------------------ #


class TestBuildAnalysisPrompt:
    def test_all_types_produce_prompts(self) -> None:
        fin = _make_fin()
        for atype in ANALYSIS_TYPES:
            prompt = build_analysis_prompt(atype, "AAPL", fin)
            assert "AAPL" in prompt
            assert len(prompt) > 100

    def test_income_prompt_has_framework(self) -> None:
        fin = _make_fin(revenue=400e9, ebitda=130e9, net_income=100e9)
        prompt = build_analysis_prompt("income", "AAPL", fin)
        assert "Revenue Analysis" in prompt
        assert "Operating Leverage" in prompt
        assert "$400.0B" in prompt

    def test_balance_prompt_has_debt_analysis(self) -> None:
        fin = _make_fin(total_debt=100e9, total_cash=60e9)
        prompt = build_analysis_prompt("balance", "MSFT", fin)
        assert "Capital Structure" in prompt
        assert "MSFT" in prompt

    def test_competitors_prompt_includes_peer_table(self) -> None:
        fin = _make_fin()
        peer_table = "| MSFT | $200B | $80B |"
        prompt = build_analysis_prompt("competitors", "AAPL", fin, peer_table=peer_table)
        assert "Peer Data" in prompt
        assert "MSFT" in prompt


def _make_peer_candidates(ticker: str = "AAPL") -> DataResult:
    """A minimal PEER_CANDIDATES payload whose deterministic screen picks TSM."""
    return DataResult(
        data={
            "profile": {"market_cap": 3e12},
            "industry_screen": ["TSM"],
            "stock_peers": [],
            "sector_screen": [],
            "quotes": {"TSM": {"market_cap": 900e9, "pe": 28.0}},
            "profiles": {},
        },
        provider="fmp",
        ticker=ticker,
        data_type="peer_candidates",
        timestamp=datetime.now(tz=timezone.utc),
    )


class TestPeerTableFxNormalization:
    """BUG-016: the `analyze competitors` peer table must run peers through the
    same FX-normalize + sanity-gate recipe as the comps pipeline — never feed
    the LLM a raw, mixed-currency provider P/E (the 0.158x-class collapse)."""

    async def test_foreign_peer_pe_is_fx_normalized_not_collapsed(self) -> None:
        # A TSM-like peer: financials in TWD, market cap quoted in USD. The raw
        # provider P/E (market_cap_USD / net_income_TWD) collapses below 1x.
        foreign = DataResult(
            data={
                "revenue": 3_000e9,  # TWD
                "ebitda": 1_500e9,  # TWD
                "net_income": 1_000e9,  # TWD  → 31.25B USD at 1/32
                "market_cap": 900e9,  # USD (quote ccy)
                "shares_outstanding": 5e9,
                "pe_ratio": 0.9,  # collapsed mixed-ccy value the OLD path fed the LLM
                "financial_currency": "TWD",
                "quote_currency": "USD",
            },
            provider="fmp",
            ticker="TSM",
            data_type="financials",
            timestamp=datetime.now(tz=timezone.utc),
        )
        foreign_fin = normalize_financials(foreign)
        # Sanity-check the fixture really is a foreign-ccy collapse case.
        assert foreign_fin.reporting_currency == "TWD"

        candidates = _make_peer_candidates()

        class _FakeDataLayer:
            async def fetch(self, data_type: object, ticker: str) -> DataResult:
                return candidates

            async def fetch_canonical(self, data_type: object, ticker: str) -> object:
                return foreign_fin

        settings = MagicMock()
        settings.create_model = MagicMock(return_value=MagicMock())
        settings.fmp_api_key = None

        async def _fake_fx(ccy: str, *, fmp_api_key: object = None) -> float:
            return 1.0 / 32.0  # TWD → USD

        with patch("finrobot.engine.data.providers.fx.fetch_fx_rate_to_usd", _fake_fx):
            table = await _fetch_peer_table(_FakeDataLayer(), settings, "AAPL")

        # net_income 1000B TWD × (1/32) = 31.25B USD; market_cap 900B USD →
        # P/E ≈ 28.8x (sane), NOT the collapsed 0.9x.
        assert "28.8x" in table, table
        assert "0.9x" not in table
        assert "Revenue (USD)" in table  # header flags the normalization


class TestPeerTableDeterministicSelection:
    """ADR-0014 contract: peers come from the deterministic PEER_CANDIDATES
    screen, never from an LLM pick, and every symbol passes validate_ticker
    before it becomes a fetch parameter."""

    async def test_invalid_screen_symbol_is_dropped_before_fetch(self) -> None:
        fetched: list[str] = []
        target_fin = _make_fin()
        candidates = _make_peer_candidates()

        class _FakeDataLayer:
            async def fetch(self, data_type: object, ticker: str) -> DataResult:
                return candidates

            async def fetch_canonical(self, data_type: object, ticker: str) -> object:
                fetched.append(ticker)
                return target_fin

        settings = MagicMock()
        settings.fmp_api_key = None

        junk_screen = SimpleNamespace(tickers=["苹果", "AAPL;DROP", "MSFT"], rationale="fake")
        with patch(
            "finrobot.engine.analysis.prompts.screen_peers_with_cyclical",
            MagicMock(return_value=junk_screen),
        ):
            table = await _fetch_peer_table(_FakeDataLayer(), settings, "AAPL")

        # Junk symbols never reach the provider fan-out; the valid one does.
        assert fetched == ["MSFT"]
        assert "MSFT" in table

    async def test_screen_degradation_returns_no_peers_not_llm_fallback(self) -> None:
        class _FakeDataLayer:
            async def fetch(self, data_type: object, ticker: str) -> DataResult:
                return DataResult(
                    data={"error": "no FMP key"},
                    provider="fmp",
                    ticker=ticker,
                    data_type="peer_candidates",
                    timestamp=datetime.now(tz=timezone.utc),
                )

            async def fetch_canonical(self, data_type: object, ticker: str) -> object:
                raise AssertionError("must not fetch peer financials without a screen")

        settings = MagicMock()
        table = await _fetch_peer_table(_FakeDataLayer(), settings, "AAPL")
        assert table == "No peers identified."


class TestBuildAnalysisPromptMore:
    def test_invalid_type_raises(self) -> None:
        fin = _make_fin()
        with pytest.raises(ValueError, match="Unknown analysis type"):
            build_analysis_prompt("invalid", "AAPL", fin)

    def test_risk_prompt_has_categories(self) -> None:
        fin = _make_fin(revenue=50e9, total_debt=20e9)
        prompt = build_analysis_prompt("risk", "TSLA", fin)
        assert "Operational Risk" in prompt
        assert "Financial Risk" in prompt
        assert "Market Risk" in prompt


# ------------------------------------------------------------------ #
# Data validation                                                    #
# ------------------------------------------------------------------ #


class TestValidateAnalysisData:
    def test_rejects_zero_revenue(self) -> None:
        fin = _make_fin(revenue=0)
        with pytest.raises(ValueError, match="Revenue is 0"):
            _validate_analysis_data(fin)

    def test_accepts_valid_data(self) -> None:
        fin = _make_fin(revenue=400e9)
        _validate_analysis_data(fin)  # should not raise

    def test_error_message_includes_ticker_and_provider(self) -> None:
        raw = DataResult(
            data={"revenue": 0, "market_cap": 3e12, "shares_outstanding": 15e9},
            provider="fmp",
            ticker="MSFT",
            data_type="financials",
            timestamp=datetime.now(tz=timezone.utc),
        )
        fin = normalize_financials(raw)
        with pytest.raises(ValueError, match="MSFT"):
            _validate_analysis_data(fin)


# ------------------------------------------------------------------ #
# EV/EBITDA computation                                              #
# ------------------------------------------------------------------ #


class TestEVEBITDAComputation:
    def test_ev_computed_when_all_components_present(self) -> None:
        fin = _make_fin(market_cap=3e12, ebitda=130e9, total_debt=100e9, total_cash=60e9)
        table = _build_financials_table(fin)
        # EV = 3T + 100B - 60B = 3.04T
        assert "Enterprise Value" in table
        assert "$3.0T" in table
        # EV/EBITDA = 3.04T / 130B ≈ 23.4x
        assert "EV/EBITDA" in table
        assert "23.4x" in table

    def test_ev_skipped_when_debt_missing(self) -> None:
        fin = _make_fin(market_cap=3e12, ebitda=130e9, total_debt=None, total_cash=60e9)
        table = _build_financials_table(fin)
        assert "| Enterprise Value | N/A |" in table
        assert "EV unavailable" in table
        assert "total_debt" in table

    def test_ev_skipped_when_cash_missing(self) -> None:
        fin = _make_fin(market_cap=3e12, ebitda=130e9, total_debt=100e9, total_cash=None)
        table = _build_financials_table(fin)
        assert "| Enterprise Value | N/A |" in table
        assert "EV unavailable" in table
        assert "total_cash" in table

    def test_ev_ebitda_na_when_ebitda_zero(self) -> None:
        """N16: EV/EBITDA explains why it's N/A when EBITDA <= 0."""
        fin = _make_fin(ebitda=0, market_cap=3e12, total_debt=100e9, total_cash=60e9)
        table = _build_financials_table(fin)
        assert "negative EBITDA" in table
        # EV itself should still be computed
        assert "$" in table.split("Enterprise Value")[1].split("\n")[0]

    def test_ev_ebitda_na_when_ebitda_negative(self) -> None:
        """N16: Negative EBITDA explicitly noted."""
        fin = _make_fin(ebitda=-5e9, market_cap=3e12, total_debt=100e9, total_cash=60e9)
        table = _build_financials_table(fin)
        assert "negative EBITDA" in table

    def test_ev_ebitda_na_reason_when_ev_unavailable(self) -> None:
        """N16: When EV itself is N/A, EV/EBITDA says 'EV unavailable'."""
        fin = _make_fin(market_cap=3e12, total_debt=None, total_cash=60e9)
        table = _build_financials_table(fin)
        assert "EV unavailable" in table

    def test_no_default_zero_for_missing_debt_and_cash(self) -> None:
        """Ensure missing debt+cash is NOT defaulted to 0 to produce a fake EV."""
        fin = _make_fin(total_debt=None, total_cash=None)
        table = _build_financials_table(fin)
        assert "EV unavailable" in table
        assert "total_debt" in table
        assert "total_cash" in table


# ------------------------------------------------------------------ #
# D&A approximation warning                                          #
# ------------------------------------------------------------------ #


class TestCashflowFcfInjection:
    """BUG-005: FCF must be a compute-layer number injected into the table, not
    something the LLM hand-computes from a prompt formula (red-line 3)."""

    def test_table_shows_computed_fcf_when_components_present(self) -> None:
        # AAPL TTM proxy: OCF 140.2B − CapEx 11.0B = FCF 129.2B; yield = 129.2/3000.
        fin = _make_fin(market_cap=3e12, operating_cash_flow=140.2e9, capital_expenditure=11.0e9)
        table = _build_financials_table(fin)
        assert "| Free Cash Flow (TTM) | $129.2B |" in table
        assert "| Operating Cash Flow (TTM) | $140.2B |" in table
        assert "| CapEx (TTM) | $11.0B |" in table
        assert "| FCF Yield | 4.3% |" in table  # 129.2 / 3000
        assert "Free Cash Flow unavailable" not in table

    def test_table_withholds_fcf_when_components_missing(self) -> None:
        fin = _make_fin(revenue=400e9)  # no OCF / CapEx
        table = _build_financials_table(fin)
        assert "| Free Cash Flow (TTM) | N/A |" in table
        assert "Free Cash Flow unavailable" in table
        assert "Do NOT estimate FCF" in table

    def test_cashflow_prompt_does_not_instruct_llm_to_compute_fcf(self) -> None:
        """The prompt must NOT carry a formula for the LLM to compute FCF — the
        whole BUG-005 fix is that FCF is pre-computed and only interpreted."""
        fin = _make_fin(operating_cash_flow=140e9, capital_expenditure=11e9)
        prompt = build_analysis_prompt("cashflow", "AAPL", fin)
        assert "EBIT(1-T)" not in prompt
        assert "EBITDA(1-T)" not in prompt
        assert "EBITDA × (1-T)" not in prompt
        assert "Do NOT recompute FCF" in prompt
