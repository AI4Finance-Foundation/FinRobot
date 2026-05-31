"""Audit invariants for pipeline valuation synthesis (Football Field source).

Pins three contracts broken by Bug A + Bug B:

1. DCF always appears in methods when DCFResult is in structured_context.
2. len(methods) >= 2 when both DCF + Comps are available.
3. weighted_price is None when only 1 method resolves (no cross-check).
"""

from __future__ import annotations

from finrobot.engine.compute.valuation_aggregator import aggregate_valuation
from finrobot.engine.compute.valuation_synthesis import synthesize_valuations
from finrobot.engine.models.financial import (
    CompanyFinancials,
    DCFInputs,
    DCFResult,
    PeerComps,
    ValuationMethod,
)
from finrobot.engine.pipelines._helpers import build_valuation_synthesis


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _dcf(implied_price: float = 150.0) -> DCFResult:
    return DCFResult(
        cost_of_equity=0.09,
        wacc=0.082,
        projection_years=5,
        projected_revenue=[100e9, 110e9, 121e9],
        projected_ebitda=[25e9, 27e9, 30e9],
        projected_fcf=[18e9, 20e9, 22e9],
        terminal_value=800e9,
        pv_terminal=600e9,
        pv_fcf_total=80e9,
        enterprise_value=680e9,
        equity_value=640e9,
        implied_price=implied_price,
        sensitivity_table=None,
        inputs=DCFInputs(
            revenue_base=100e9,
            revenue_growth_rates=[0.10, 0.08, 0.06],
            ebitda_margin=0.25,
            capex_pct_revenue=0.04,
            nwc_pct_revenue=0.02,
            da_pct_revenue=0.04,
            tax_rate=0.21,
            risk_free_rate=0.04,
            beta=1.2,
            equity_risk_premium=0.05,
            cost_of_debt=0.05,
            debt_ratio=0.2,
            terminal_growth_rate=0.025,
            shares_outstanding=15.4e9,
            net_debt=40e9,
        ),
    )


def _peer_comps() -> PeerComps:
    target = CompanyFinancials(
        ticker="AAPL",
        name="Apple Inc.",
        revenue=390e9,
        ebitda=120e9,
        net_income=95e9,
        market_cap=2.8e12,
        total_debt=110e9,
        total_cash=62e9,
        gross_margin=0.44,
        operating_margin=0.30,
        pe_ratio=29.0,
        ev_ebitda=22.0,
    )
    peer = target.model_copy(
        update={"ticker": "MSFT", "pe_ratio": 35.0, "ev_ebitda": 26.0, "market_cap": 3.1e12}
    )
    return PeerComps(
        target=target,
        peers=[peer],
        median_pe=32.0,
        median_ev_ebitda=24.0,
    )


# ---------------------------------------------------------------------------
# Contract 1: DCF appears in methods when DCFResult is in context
# ---------------------------------------------------------------------------


class TestDCFAlwaysPresent:
    def test_dcf_in_methods_when_dcf_result_in_context(self) -> None:
        """Bug A: DCF was silently dropped because context was read before write."""
        structured_context: dict[str, object] = {
            "financial_modeling": _dcf(150.0),
            "peer_analysis": _peer_comps(),
        }
        vs = build_valuation_synthesis(structured_context, current_price=170.0, ticker="AAPL")
        assert vs is not None, "Should produce ValuationSynthesis when DCF + Comps available"
        method_names = {m.name for m in vs.methods}
        assert "dcf" in method_names, (
            f"DCF method missing from synthesis — Bug A regression. Got: {method_names}"
        )

    def test_dcf_in_aggregate_valuation_directly(self) -> None:
        """aggregate_valuation emits a dcf row when DCFResult is provided."""
        agg = aggregate_valuation(
            ticker="AAPL",
            current_price=170.0,
            dcf=_dcf(150.0),
            peer_comps=_peer_comps(),
            shares_outstanding=15.4e9,
        )
        method_names = {m.method for m in agg.methods}
        assert "dcf" in method_names, f"DCF missing from aggregate_valuation. Got: {method_names}"


# ---------------------------------------------------------------------------
# Contract 2: ≥2 methods when both DCF + Comps are available
# ---------------------------------------------------------------------------


class TestMinMethodCount:
    def test_two_or_more_methods_with_dcf_and_comps(self) -> None:
        """Bug B: old build_valuation_synthesis only wired 2 branches,
        but DCF branch silently failed → len == 1."""
        structured_context: dict[str, object] = {
            "financial_modeling": _dcf(150.0),
            "peer_analysis": _peer_comps(),
        }
        vs = build_valuation_synthesis(structured_context, current_price=170.0, ticker="AAPL")
        assert vs is not None
        assert len(vs.methods) >= 2, (
            f"Expected ≥2 methods with DCF + Comps, got {len(vs.methods)}: "
            f"{[m.name for m in vs.methods]}"
        )

    def test_weighted_price_not_none_with_two_methods(self) -> None:
        structured_context: dict[str, object] = {
            "financial_modeling": _dcf(150.0),
            "peer_analysis": _peer_comps(),
        }
        vs = build_valuation_synthesis(structured_context, current_price=170.0, ticker="AAPL")
        assert vs is not None
        assert vs.weighted_price is not None, (
            "weighted_price must be a float when ≥2 methods are present"
        )
        assert vs.weighted_price > 0


# ---------------------------------------------------------------------------
# Contract 3: single-method → weighted_price is None
# ---------------------------------------------------------------------------


class TestSingleMethodWeightedPriceNone:
    def test_weighted_price_none_when_only_one_method(self) -> None:
        """When only 1 method resolves, we must not surface a fake weighted average."""
        methods = [
            ValuationMethod(
                name="DCF", low=120.0, mid=150.0, high=180.0, confidence=0.85, source="dcf"
            )
        ]
        vs = synthesize_valuations(methods, current_price=170.0)
        assert vs.weighted_price is None, (
            "Single-method synthesis must have weighted_price=None (no cross-check)"
        )
        assert vs.upside_downside is None

    def test_weighted_price_none_propagates_from_build_synthesis(self) -> None:
        """build_valuation_synthesis with only DCF (no comps) → weighted_price None."""
        structured_context: dict[str, object] = {
            "financial_modeling": _dcf(150.0),
            # No peer_analysis → only DCF method resolves
        }
        vs = build_valuation_synthesis(structured_context, current_price=170.0, ticker="AAPL")
        assert vs is not None, "Should still return a ValuationSynthesis with 1 method"
        assert len(vs.methods) == 1
        assert vs.weighted_price is None

    def test_isinstance_check_on_result_not_prompt(self) -> None:
        """DCF field is present via isinstance on the result object, not a prompt string."""
        structured_context: dict[str, object] = {
            "financial_modeling": _dcf(150.0),
            "peer_analysis": _peer_comps(),
        }
        vs = build_valuation_synthesis(structured_context, current_price=170.0, ticker="AAPL")
        assert vs is not None
        # Confirm the DCF method came from an actual DCFResult, not a magic string
        dcf_method = next((m for m in vs.methods if m.name == "dcf"), None)
        assert dcf_method is not None
        # The mid must equal the DCFResult.implied_price (±20% band, mid is implied_price)
        assert dcf_method.mid == 150.0, (
            f"DCF mid {dcf_method.mid} should equal implied_price 150.0"
        )
