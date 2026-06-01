"""Semantic version-diff engine tests.

Attribution is tested against REAL DCF arithmetic: we run ``calculate_dcf`` to
produce self-consistent DCFResult dumps, embed them in artifacts, and assert the
re-priced single-factor contributions reconcile to the actual fair-value move
(residual ≈ 0 when only one assumption changed). No mocked expected values —
the expected numbers come from the same deterministic compute the report uses.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from finrobot.artifact.models import (
    Artifact,
    ArtifactAssumptions,
    ArtifactComputeVersion,
    ArtifactInputs,
    ArtifactMeta,
    ArtifactOutputs,
)
from finrobot.artifact.semantic_diff import build_semantic_delta
from finrobot.engine.compute.dcf import calculate_dcf
from finrobot.engine.models.financial import DCFInputs

UTC = timezone.utc


def _inputs(beta: float = 1.1) -> DCFInputs:
    return DCFInputs(
        revenue_base=394_000_000_000,
        revenue_growth_rates=[0.06, 0.05, 0.04, 0.03, 0.02],
        ebitda_margin=0.32,
        capex_pct_revenue=0.03,
        nwc_pct_revenue=0.02,
        da_pct_revenue=0.04,
        tax_rate=0.21,
        risk_free_rate=0.042,
        beta=beta,
        equity_risk_premium=0.05,
        cost_of_debt=0.045,
        debt_ratio=0.12,
        terminal_growth_rate=0.025,
        shares_outstanding=15_500_000_000,
        net_debt=-50_000_000_000,
    )


def _equity_artifact(
    art_id: str,
    inputs: DCFInputs,
    *,
    recommendation: str,
    current_price: float,
    formula_id: str = "equity_research_dcf_standard_with_da_v2",
    data_source: str = "yfinance",
    fetched_at: datetime | None = None,
) -> Artifact:
    """Build an equity_research artifact whose DCFResult is computed for real."""
    dcf = calculate_dcf(inputs)
    dcf_dump: dict[str, Any] = dcf.model_dump(mode="json")
    ts = fetched_at or datetime(2026, 5, 13, 10, 0, tzinfo=UTC)
    return Artifact(
        id=art_id,
        ticker="AAPL",
        type="equity_research",
        inputs=ArtifactInputs(
            data_source=data_source,
            data_fetched_at=ts,
            raw_data={"market": {"current_price": current_price}},
        ),
        assumptions=ArtifactAssumptions(parameters=inputs.model_dump(mode="json")),
        compute_version=ArtifactComputeVersion(version="0.1.0", formula_id=formula_id),
        outputs=ArtifactOutputs(
            structured={
                "financial_modeling": dcf_dump,
                "thesis": {
                    "price_target": dcf.implied_price,
                    "recommendation": recommendation,
                },
            },
            llm_narrative={"recommendation": recommendation},
        ),
        meta=ArtifactMeta(created_at=ts, source="pipeline:equity_research"),
    )


class TestConclusion:
    def test_rating_downgrade_is_negative(self) -> None:
        a = _equity_artifact("art_v1", _inputs(beta=1.1), recommendation="BUY", current_price=170.0)
        b = _equity_artifact(
            "art_v2", _inputs(beta=1.4), recommendation="HOLD", current_price=170.0
        )
        delta = build_semantic_delta(a, b)
        rating = next(it for it in delta.conclusion if it.key == "recommendation")
        assert rating.formatted_old == "BUY"
        assert rating.formatted_new == "HOLD"
        assert rating.direction == "down"
        assert rating.sentiment == "negative"

    def test_target_price_row_present_and_formatted(self) -> None:
        a = _equity_artifact("art_v1", _inputs(), recommendation="BUY", current_price=170.0)
        b = _equity_artifact("art_v2", _inputs(beta=1.4), recommendation="BUY", current_price=170.0)
        delta = build_semantic_delta(a, b)
        tp = next(it for it in delta.conclusion if it.key == "target_price")
        assert tp.formatted_new.startswith("$")  # USD assumed
        assert tp.old_value is not None and tp.new_value is not None


class TestAttribution:
    def test_single_factor_wacc_reconciles_with_small_residual(self) -> None:
        # Only beta (→ WACC) changes between versions, so the WACC contribution
        # should account for ~all of the fair-value move; residual ≈ 0.
        a = _equity_artifact("art_v1", _inputs(beta=1.1), recommendation="BUY", current_price=170.0)
        b = _equity_artifact("art_v2", _inputs(beta=1.5), recommendation="BUY", current_price=170.0)
        delta = build_semantic_delta(a, b)
        attr = delta.attribution
        assert attr.available is True
        wacc_items = [it for it in attr.items if it.driver_key == "wacc"]
        assert len(wacc_items) == 1
        # Higher beta → higher WACC → lower fair value → negative contribution.
        assert wacc_items[0].contribution < 0
        assert attr.total_change < 0
        # Residual is tiny relative to the move (only one factor changed).
        assert abs(attr.residual) < max(1.0, abs(attr.total_change) * 0.05)

    def test_contributions_plus_residual_equals_total(self) -> None:
        a = _equity_artifact("art_v1", _inputs(beta=1.1), recommendation="BUY", current_price=170.0)
        b = _equity_artifact("art_v2", _inputs(beta=1.5), recommendation="BUY", current_price=170.0)
        attr = build_semantic_delta(a, b).attribution
        summed = sum(it.contribution for it in attr.items) + attr.residual
        assert abs(summed - attr.total_change) < 1e-6

    def test_formula_change_disables_attribution(self) -> None:
        a = _equity_artifact("art_v1", _inputs(beta=1.1), recommendation="BUY", current_price=170.0)
        b = _equity_artifact(
            "art_v2",
            _inputs(beta=1.5),
            recommendation="BUY",
            current_price=170.0,
            formula_id="equity_research_dcf_simplified_v3",  # different formula
        )
        delta = build_semantic_delta(a, b)
        assert delta.attribution.available is False
        assert delta.attribution.disabled_reason is not None
        assert any(f.kind == "formula" and f.blocks_attribution for f in delta.comparability)
        # Total still shown (the move is real), just not attributed.
        assert delta.attribution.formatted_total != ""


class TestComparabilityGate:
    def test_data_source_change_flagged(self) -> None:
        a = _equity_artifact(
            "art_v1", _inputs(), recommendation="BUY", current_price=170.0, data_source="yfinance"
        )
        b = _equity_artifact(
            "art_v2",
            _inputs(beta=1.3),
            recommendation="BUY",
            current_price=170.0,
            data_source="FMP",
        )
        delta = build_semantic_delta(a, b)
        assert any(f.kind == "data_source" for f in delta.comparability)

    def test_period_drift_flagged_and_abs_fundamentals_not_comparable(self) -> None:
        t0 = datetime(2026, 1, 1, tzinfo=UTC)
        a = _equity_artifact(
            "art_v1", _inputs(), recommendation="BUY", current_price=170.0, fetched_at=t0
        )
        b = _equity_artifact(
            "art_v2",
            _inputs(beta=1.3),
            recommendation="BUY",
            current_price=170.0,
            fetched_at=t0 + timedelta(days=120),
        )
        delta = build_semantic_delta(a, b)
        assert any(f.kind == "period" for f in delta.comparability)
        # Absolute-currency drivers (equity_value / EV) must drop their delta.
        ev_items = [it for it in delta.drivers if it.key == "enterprise_value"]
        if ev_items:
            assert ev_items[0].comparable is False
            assert ev_items[0].pct_change is None


class TestDataFootnote:
    def test_currency_assumed_when_artifact_carries_no_tag(self) -> None:
        a = _equity_artifact("art_v1", _inputs(), recommendation="BUY", current_price=170.0)
        b = _equity_artifact("art_v2", _inputs(beta=1.3), recommendation="BUY", current_price=170.0)
        fn = build_semantic_delta(a, b).data_footnote
        assert fn.currency == "USD"
        assert fn.currency_assumed is True


class TestIdentical:
    def test_identical_versions_flagged(self) -> None:
        a = _equity_artifact("art_v1", _inputs(), recommendation="BUY", current_price=170.0)
        b = _equity_artifact("art_v2", _inputs(), recommendation="BUY", current_price=170.0)
        delta = build_semantic_delta(a, b)
        assert delta.identical is True
