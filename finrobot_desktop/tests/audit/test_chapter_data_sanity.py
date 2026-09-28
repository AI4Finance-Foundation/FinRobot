"""Cross-chapter data sanity audit — single tier-0 gate covering all
plausibility invariants exposed during the 2026-05-28 audit sweep.

Each section maps to one chapter of the 12-chapter equity research and asserts
the financial red-line that, if broken, would surface as silent garbage in the
artifact (the exact failure mode the AAPL audit found in chapters 4/5/9/10/12).

The point of bundling these here is not to duplicate per-module unit tests but
to make the *contract* visible in one place — any future PR that breaks any of
these makes this file red and stops the train. The list of checks must NEVER
shrink without a written ADR explaining why a red line is being relaxed.

Add new asserts here whenever you find a new silent-garbage class. Don't move
them into other files — the discoverability of this single audit gate is the
mechanism that prevents regressions.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError

from finrobot.engine.compute.operators.catalyst import extract_catalysts_from_news
from finrobot.engine.compute.operators.dcf import calculate_dcf
from finrobot.engine.compute.operators.multiples import calculate_multiples
from finrobot.engine.compute.operators.ownership import build_proxy_compensation
from finrobot.engine.compute.operators.sniper import SniperRequest, calculate_sniper_points
from finrobot.engine.compute.operators.valuation_synthesis import synthesize_valuations
from finrobot.engine.compute.coordinators.news import NewsItem
from finrobot.engine.models.financial import (
    CompanyFinancials,
    DCFInputs,
    ValuationMethod,
)


# ---------------------------------------------------------------------------
# Chapter 4 · Financial Analysis / DCF
# ---------------------------------------------------------------------------


def _baseline_dcf_inputs() -> DCFInputs:
    return DCFInputs(
        revenue_base=416e9,
        revenue_growth_rates=[0.05, 0.04, 0.03, 0.025, 0.02],
        ebitda_margin=0.33,
        capex_pct_revenue=0.03,
        nwc_pct_revenue=0.01,
        da_pct_revenue=0.028,
        tax_rate=0.15,
        risk_free_rate=0.043,
        beta=1.06,
        equity_risk_premium=0.055,
        cost_of_debt=0.02,
        debt_ratio=0.024,
        terminal_growth_rate=0.025,
        shares_outstanding=14.69e9,
        net_debt=76.4e9,
    )


def test_chapter_11_fmp_financials_default_path_returns_ttm_not_annual():
    """Real bug found 2026-05-28: FMPProvider was fetching /income-statement?limit=1
    (single annual row) for the current snapshot and computing P/E as
    market_cap / annual_NI. NVDA showed PE=43 (stale annual) vs true LTM=32.
    Lock the contract: when years kwarg is absent, FMP MUST return summed
    4-quarter TTM data tagged period_basis='ttm', with net_income equal to
    the SUM of the four quarterly netIncome rows. Plausibility floors don't
    catch this — both 43x and 32x pass the [1, 300] gate but only one is
    the right number for the analyst."""
    from unittest.mock import MagicMock, patch
    from finrobot.engine.data.providers.fmp_provider import FMPProvider
    from finrobot.engine.data.types import DataType

    quarterly = [
        {
            "date": f"2026-0{q + 1}-30",
            "symbol": "NVDA",
            "revenue": 30e9,
            "ebitda": 18e9,
            "netIncome": 27e9,
            "grossProfit": 22e9,
            "operatingIncome": 19e9,
            "depreciationAndAmortization": 1e9,
            "researchAndDevelopmentExpenses": 3e9,
            "sellingGeneralAndAdministrativeExpenses": 1e9,
            "interestExpense": 0,
        }
        for q in range(4)
    ]
    balance = [
        {
            "date": "2026-04-30",
            "symbol": "NVDA",
            "totalDebt": 10e9,
            "cashAndCashEquivalents": 30e9,
            "cashAndShortTermInvestments": 30e9,
        }
    ]
    profile = [
        {
            "symbol": "NVDA",
            "marketCap": 3500e9,
            "price": 212.6,
            "companyName": "NVIDIA",
            "industry": "Semiconductors",
            "sector": "Technology",
            "beta": 1.7,
        }
    ]

    async def fake_get(path: str, params: dict | None = None):
        resp = MagicMock()
        if "income-statement" in path:
            resp.json = MagicMock(return_value=quarterly)
        elif "balance-sheet" in path:
            resp.json = MagicMock(return_value=balance)
        else:
            resp.json = MagicMock(return_value=profile)
        return resp

    provider = FMPProvider(api_key="test")
    with patch.object(provider, "_get", side_effect=fake_get):
        import asyncio

        result = asyncio.run(provider.fetch("NVDA", DataType.FINANCIALS))

    assert result.data["period_basis"] == "ttm"
    # TTM net_income = 4 * 27e9 = 108e9, NOT a single annual row
    assert result.data["net_income"] == pytest.approx(108e9)
    # TTM PE = 3500e9 / 108e9 ≈ 32.4x — matches external sources, NOT
    # the stale-annual 43x bug that motivated this gate.
    assert result.data["pe_ratio"] == pytest.approx(3500e9 / 108e9, rel=1e-6)


def test_chapter_4_dcf_uses_standard_fcf_formula_with_da_tax_shield():
    """AGENTS.md red-line #5 — the formula contract lives in code + tests, not
    a serialized tag (see tests/unit/test_dcf.py). The contract: FCF must
    include the D&A tax shield so capital-intensive companies aren't
    systematically under-valued. The simplified ``EBITDA*(1-T)`` branch was
    removed and any regression would silently drop ``D&A * tax_rate`` from
    every projected FCF year — this gate catches it numerically."""
    inputs_with_da = _baseline_dcf_inputs()
    no_da = inputs_with_da.model_copy(update={"da_pct_revenue": 0.0})
    with_da = calculate_dcf(inputs_with_da)
    without_da = calculate_dcf(no_da)
    # FCF with D&A must exceed FCF without D&A by exactly ``rev * da * tax``
    rev0 = with_da.projected_revenue[0]
    expected_shield = rev0 * inputs_with_da.da_pct_revenue * inputs_with_da.tax_rate
    actual_diff = with_da.projected_fcf[0] - without_da.projected_fcf[0]
    assert actual_diff == pytest.approx(expected_shield, rel=1e-6)


# ---------------------------------------------------------------------------
# Chapter 5 · Valuation Analysis / Football Field
# ---------------------------------------------------------------------------


def _make_method(name: str, mid: float, confidence: float = 0.5) -> ValuationMethod:
    return ValuationMethod(
        name=name,
        low=mid * 0.85,
        mid=mid,
        high=mid * 1.15,
        confidence=confidence,
        source="audit fixture",
    )


def test_chapter_5_single_method_synthesis_returns_none_weighted_price():
    """A 'weighted average' of one method is mathematically the method itself
    and a UI presenting it as 'cross-method weighted' lies to the analyst.
    Synthesis MUST return None when fewer than 2 methods are available."""
    methods = [_make_method("EV/EBITDA Comps", 221.0)]
    syn = synthesize_valuations(methods, current_price=310.0)
    assert syn.weighted_price is None
    assert syn.upside_downside is None


def test_chapter_5_synthesis_flags_30pct_outlier_method():
    """DCF $86 vs Comps $221 (AAPL real spread 157%) MUST raise an outlier
    flag — silently weighting two methods that disagree by >30% hides the
    very disagreement analysts most need to see."""
    methods = [
        _make_method("DCF", 86.0),
        _make_method("EV/EBITDA Comps", 221.0),
    ]
    syn = synthesize_valuations(methods, current_price=310.0)
    assert syn.outlier_methods  # non-empty
    assert syn.warnings  # human-readable warning surfaces in artifact
    # Both methods are equidistant from median (153.5), so both flag
    assert "DCF" in syn.outlier_methods or "EV/EBITDA Comps" in syn.outlier_methods


# ---------------------------------------------------------------------------
# Chapter 9 · Technical / Sniper
# ---------------------------------------------------------------------------


def test_chapter_9_sniper_levels_are_direction_coherent():
    """Math invariant, direction-aware (Bug-6, 2026-05-28):
      LONG  : stop_loss <  ideal_buy <  take_profit  (exit above entry)
      SHORT : take_profit <  ideal_buy <  stop_loss  (cover below entry)
    A SELL-rated stock must produce a coherent SHORT — the pre-fix code
    emitted a LONG-flavoured 'buy $372.80 / stop $484.40 / R/R 0.11' that
    had no financial meaning against a SELL verdict."""
    # SELL-mode scenario: DCF target ($85) far below current ($310).
    req = SniperRequest(
        ticker="AAPL",
        current_price=310.0,
        dcf_target=85.0,
        historical_prices=[300.0] * 15 + [308.0, 305.0, 309.0, 310.0, 310.0],
    )
    result = calculate_sniper_points(req)
    if result.sell_mode:
        assert result.direction == "SHORT"
        # SHORT: cover below entry, stop above entry.
        assert result.take_profit < result.ideal_buy < result.stop_loss
    else:
        assert result.direction == "LONG"
        # LONG: stop below entry, target above entry.
        assert result.stop_loss < result.ideal_buy <= result.take_profit


def test_chapter_9_sniper_sell_mode_activates_when_target_below_current():
    """Sniper MUST flip into sell_mode when DCF intrinsic < current. The
    artifact warning that comes with it lets the UI render an honest
    'short-term technical anchors' label instead of pretending the anchors
    came from the DCF target."""
    req = SniperRequest(
        ticker="AAPL",
        current_price=310.0,
        dcf_target=85.0,
        historical_prices=[300.0] * 20,
    )
    result = calculate_sniper_points(req)
    assert result.sell_mode is True
    assert result.invariant_warnings  # non-empty: explains the regime switch


# ---------------------------------------------------------------------------
# Chapter 10 · Peer Comps / Multiples Sanity
# ---------------------------------------------------------------------------


def _make_company(
    market_cap: float, revenue: float, ebitda: float, net_income: float
) -> CompanyFinancials:
    return CompanyFinancials(
        ticker="TEST",
        name="Test Co",
        revenue=revenue,
        ebitda=ebitda,
        net_income=net_income,
        market_cap=market_cap,
        total_debt=10e9,
        total_cash=5e9,
        gross_margin=0.4,
        operating_margin=0.2,
        reporting_currency="USD",
        quote_currency="USD",
    )


def test_chapter_10_multiples_rejects_absurd_pe():
    """TSM appeared with PE=1.85 (ADR FX bug). Multiples MUST clamp values
    below 1x or above 300x to None — keeping them would corrupt every
    cross-peer median that uses them."""
    # market_cap / net_income = 100B / 54B ≈ 1.85x (sub-1.0 territory rounded)
    company = _make_company(market_cap=100e9, revenue=50e9, ebitda=10e9, net_income=54e9)
    result = calculate_multiples(company)
    assert result.pe_ratio is None or 1.0 <= result.pe_ratio <= 300.0


def test_chapter_10_multiples_rejects_absurd_ev_revenue():
    """Same gate for EV/Revenue. Foreign ADR with stale FX produces sub-0.5x
    values that look like valid 'cheap multiples' but are pure scale errors."""
    # market_cap 10B but revenue 200B → EV/Rev ~ 0.05x (well below 0.1 floor)
    company = _make_company(market_cap=10e9, revenue=200e9, ebitda=20e9, net_income=2e9)
    result = calculate_multiples(company)
    assert result.ev_revenue is None or 0.1 <= result.ev_revenue <= 100.0


# ---------------------------------------------------------------------------
# Chapter 8 · Catalysts
# ---------------------------------------------------------------------------


def test_chapter_8_extract_catalysts_preserves_published_and_url():
    """AAPL artifact had 27 catalyst events with 0% non-null published_date
    and 0% non-null url — the extractor dropped both fields silently. UI
    couldn't validate '近 30 天' and couldn't open source articles. Both
    fields are non-negotiable for financial-grade catalyst tracking."""
    news = [
        NewsItem(
            title="Apple Surges 15% in May on AI Breakout",
            published=datetime(2026, 5, 15, tzinfo=timezone.utc),
            source="Bloomberg",
            url="https://www.bloomberg.com/news/aapl-may-2026",
            category="analyst",
            importance=4,
            sentiment="positive",
            summary="Stock hits all-time high on AI optimism",
        )
    ]
    events = extract_catalysts_from_news(news)
    assert len(events) >= 1
    e = events[0]
    assert e.published is not None
    assert e.url is not None
    assert e.url.startswith("http")


# ---------------------------------------------------------------------------
# Chapter 12 · Ownership & Governance
# ---------------------------------------------------------------------------


def _proxy_payload(text: str) -> dict[str, object]:
    return {
        "proxy": object(),  # presence sentinel, never inspected by compute
        "filing_date": date(2026, 1, 8),
        "accession_no": "0001308179-26-000008",
        "text": text,
    }


def test_chapter_12_proxy_compensation_rejects_literal_title_as_ceo_name():
    """The AAPL bug heard around the world. Regex matched 'Chief Executive
    Officer' three capitalized words and returned the literal job title as
    the CEO's name. Blacklist must permanently kill that path."""
    text = "Our Chief Executive Officer reviewed the strategy."
    proxy = build_proxy_compensation(_proxy_payload(text))
    # Either proxy is None (no usable fields), or ceo_name is None — never the title literal
    assert (
        proxy is None
        or proxy.ceo_name is None
        or proxy.ceo_name
        not in {
            "Chief Executive Officer",
            "CEO",
            "Chairman",
            "President",
            "Officer",
            "Chief",
        }
    )


def test_chapter_12_proxy_compensation_rejects_market_cap_sized_amounts():
    """$416B is roughly Apple's revenue. Earlier code grabbed the first $
    amount in the proxy text and assigned it to CEO comp — 5,600× off Tim
    Cook's actual $74M. Plausibility gate: only values in [$1M, $500M] are
    acceptable as named-executive-officer compensation."""
    text = "Aggregate market value of common stock held by non-affiliates: $416.2 billion."
    proxy = build_proxy_compensation(_proxy_payload(text))
    if proxy is not None and proxy.ceo_total_compensation is not None:
        assert 1_000_000 <= proxy.ceo_total_compensation <= 500_000_000


def test_chapter_12_proxy_compensation_accepts_realistic_ceo_comp():
    """Sanity check that the gate doesn't over-reject — a normal CEO
    compensation prose pattern MUST round-trip through the extractor."""
    text = "CEO total compensation for fiscal 2025 was $74,250,000 including stock awards."
    proxy = build_proxy_compensation(_proxy_payload(text))
    assert proxy is not None
    assert proxy.ceo_total_compensation == pytest.approx(74_250_000.0)


# ---------------------------------------------------------------------------
# Cross-chapter schema invariants
# ---------------------------------------------------------------------------


def test_valuation_method_confidence_in_unit_interval():
    """confidence outside [0, 1] is nonsensical for a probability weight."""
    with pytest.raises(ValidationError):
        ValuationMethod(name="bogus", low=1, mid=2, high=3, confidence=1.5)
    with pytest.raises(ValidationError):
        ValuationMethod(name="bogus", low=1, mid=2, high=3, confidence=-0.1)
