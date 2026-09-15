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
from finrobot.engine.compute.operators.dcf import calculate_dcf
from finrobot.engine.models.financial import DCFInputs

UTC = timezone.utc


def _inputs(
    beta: float = 1.1,
    tax_rate: float = 0.21,
    currency: str = "USD",
    revenue_base: float = 394_000_000_000,
) -> DCFInputs:
    return DCFInputs(
        revenue_base=revenue_base,
        revenue_growth_rates=[0.06, 0.05, 0.04, 0.03, 0.02],
        ebitda_margin=0.32,
        capex_pct_revenue=0.03,
        nwc_pct_revenue=0.02,
        da_pct_revenue=0.04,
        tax_rate=tax_rate,
        risk_free_rate=0.042,
        beta=beta,
        equity_risk_premium=0.05,
        cost_of_debt=0.045,
        debt_ratio=0.12,
        terminal_growth_rate=0.025,
        shares_outstanding=15_500_000_000,
        net_debt=-50_000_000_000,
        currency=currency,
    )


def _equity_artifact(
    art_id: str,
    inputs: DCFInputs,
    *,
    recommendation: str,
    current_price: float,
    peer_tickers: list[str] | None = None,
    comps_pe_mid: float | None = None,
    method_mids: dict[str, float] | None = None,
    formula_id: str = "equity_research_dcf_standard_with_da_v2",
    data_source: str = "yfinance",
    fetched_at: datetime | None = None,
    market_implied: dict[str, Any] | None = None,
) -> Artifact:
    """Build an equity_research artifact whose DCFResult is computed for real."""
    dcf = calculate_dcf(inputs)
    dcf_dump: dict[str, Any] = dcf.model_dump(mode="json")
    if market_implied is not None:
        # calculate_dcf has no current_price arg, so it never reverse-solves the
        # market-implied growth; the pipeline fills DCFResult.market_implied via a
        # separate market_implied_check pass. Inject a frozen payload here to mirror
        # the REVIEW-state artifacts the diff renders.
        dcf_dump["market_implied"] = market_implied
    ts = fetched_at or datetime(2026, 5, 13, 10, 0, tzinfo=UTC)
    structured: dict[str, Any] = {
        "financial_modeling": dcf_dump,
        "thesis": {
            "price_target": dcf.implied_price,
            "recommendation": recommendation,
        },
    }
    if peer_tickers is not None:
        structured["peer_analysis"] = {"peers": [{"ticker": t} for t in peer_tickers]}
    mids: dict[str, float] = dict(method_mids or {})
    if comps_pe_mid is not None:
        mids.setdefault("comps_pe", comps_pe_mid)
    if mids:
        structured["valuation_synthesis"] = {
            "methods": [
                {
                    "name": name,
                    "low": mid * 0.9,
                    "mid": mid,
                    "high": mid * 1.1,
                    "confidence": 0.55,
                    "source": "test comps",
                }
                for name, mid in mids.items()
            ],
            "weighted_price": dcf.implied_price,
            "current_price": current_price,
            "upside_downside": None,
        }
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
            structured=structured, llm_narrative={"recommendation": recommendation}
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
        # Backend owns the pct-badge string too — signed, one decimal, "%" suffix.
        assert tp.pct_change is not None
        assert tp.formatted_pct_change is not None
        assert tp.formatted_pct_change[0] in "+-"
        assert tp.formatted_pct_change.endswith("%")
        assert tp.formatted_pct_change == f"{tp.pct_change * 100:+.1f}%"

    def test_flat_row_has_no_pct_badge(self) -> None:
        # Identical inputs → every conclusion row is flat and must carry no
        # "+0.0%" badge next to two identical values.
        a = _equity_artifact("art_v1", _inputs(), recommendation="BUY", current_price=170.0)
        b = _equity_artifact("art_v2", _inputs(), recommendation="BUY", current_price=170.0)
        delta = build_semantic_delta(a, b)
        for it in delta.conclusion:
            if it.direction == "flat":
                assert it.pct_change is None, it.key
                assert it.formatted_pct_change is None, it.key

    def test_incomparable_row_has_no_pct_badge(self) -> None:
        # When a row is not like-for-like, both the numeric pct and its formatted
        # badge must be suppressed together (no half-state).
        a = _equity_artifact("art_v1", _inputs(), recommendation="BUY", current_price=170.0)
        b = _equity_artifact("art_v2", _inputs(beta=1.4), recommendation="BUY", current_price=170.0)
        b.inputs.data_fetched_at = a.inputs.data_fetched_at + timedelta(days=120)
        delta = build_semantic_delta(a, b)
        for it in delta.conclusion + delta.drivers:
            if not it.comparable:
                assert it.pct_change is None
                assert it.formatted_pct_change is None


class TestMarketImpliedGrowth:
    """Reverse-DCF market-implied-growth row — the attributable conclusion line
    for REVIEW reports where the DCF fair value (implied_price) is withheld.

    Frozen payloads mirror two real TSLA REVIEW artifacts:
      • reachable: implied_growth 0.4402 over a 10y horizon (e96c34)
      • unreachable: growth_unreachable=True, ceiling $301.96 at 50% (6cd0ef)
    """

    _REACHABLE_A = {
        "horizon_years": 10,
        "implied_growth": 0.44998,
        "implied_wacc": None,
        "growth_unreachable": False,
        "growth_ceiling": None,
        "ceiling_price": None,
    }
    _REACHABLE_B = {
        "horizon_years": 10,
        "implied_growth": 0.44016,
        "implied_wacc": None,
        "growth_unreachable": False,
        "growth_ceiling": None,
        "ceiling_price": None,
    }
    _UNREACHABLE = {
        "horizon_years": 10,
        "implied_growth": None,
        "implied_wacc": None,
        "growth_unreachable": True,
        "growth_ceiling": 0.5,
        "ceiling_price": 301.96,
    }

    def test_reachable_both_sides_is_percent_delta(self) -> None:
        a = _equity_artifact(
            "art_v1",
            _inputs(),
            recommendation="REVIEW",
            current_price=391.0,
            market_implied=self._REACHABLE_A,
        )
        b = _equity_artifact(
            "art_v2",
            _inputs(),
            recommendation="REVIEW",
            current_price=391.99,
            market_implied=self._REACHABLE_B,
        )
        delta = build_semantic_delta(a, b)
        mi = next(it for it in delta.conclusion if it.key == "implied_growth")
        assert mi.formatted_old == "45.0%"
        assert mi.formatted_new == "44.0%"
        assert mi.direction == "down"
        # horizon carried in the note, not mis-rendered as a value
        assert mi.caliber_note is not None and "10y" in mi.caliber_note
        # percent row is comparable / attributable, carries a pct badge
        assert mi.comparable is True
        assert mi.formatted_pct_change is not None

    def test_unreachable_shows_regime_not_percent(self) -> None:
        # A $ ceiling must NEVER be formatted through the percent caliber.
        a = _equity_artifact(
            "art_v1",
            _inputs(),
            recommendation="REVIEW",
            current_price=391.0,
            market_implied=self._UNREACHABLE,
        )
        b = _equity_artifact(
            "art_v2",
            _inputs(),
            recommendation="REVIEW",
            current_price=391.0,
            market_implied=self._UNREACHABLE,
        )
        delta = build_semantic_delta(a, b)
        mi = next(it for it in delta.conclusion if it.key == "implied_growth")
        assert mi.formatted_old == "Unreachable"
        assert mi.formatted_new == "Unreachable"
        # ceiling carried as $ context in the note, never as a "30196.0%" value
        assert mi.caliber_note is not None and "$301.96" in mi.caliber_note
        assert "%" not in mi.caliber_note
        assert mi.comparable is False

    def test_regime_shift_reachable_to_unreachable(self) -> None:
        a = _equity_artifact(
            "art_v1",
            _inputs(),
            recommendation="REVIEW",
            current_price=391.0,
            market_implied=self._REACHABLE_B,
        )
        b = _equity_artifact(
            "art_v2",
            _inputs(),
            recommendation="REVIEW",
            current_price=420.0,
            market_implied=self._UNREACHABLE,
        )
        delta = build_semantic_delta(a, b)
        mi = next(it for it in delta.conclusion if it.key == "implied_growth")
        assert mi.formatted_old == "44.0%"
        assert mi.formatted_new == "Unreachable"

    def test_absent_market_implied_emits_no_row(self) -> None:
        # Plain (non-REVIEW) artifacts without market_implied get no extra row.
        a = _equity_artifact("art_v1", _inputs(), recommendation="BUY", current_price=170.0)
        b = _equity_artifact("art_v2", _inputs(), recommendation="BUY", current_price=170.0)
        delta = build_semantic_delta(a, b)
        assert not any(it.key == "implied_growth" for it in delta.conclusion)


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

    def test_no_zero_dollar_contribution_and_no_phantom_arrows(self) -> None:
        # A tiny tax_rate move propagates a sub-cent WACC change whose price
        # impact rounds to $0.00. That must NOT surface as a "$0.00" attribution
        # item / 主因 (the bug a live NVDA diff exposed) — it belongs in the named
        # residual. And a driver whose DISPLAYED value didn't change must render
        # flat (no arrow on "16.6% → 16.6%").
        a = _equity_artifact(
            "art_v1", _inputs(tax_rate=0.210), recommendation="BUY", current_price=170.0
        )
        b = _equity_artifact(
            "art_v2", _inputs(tax_rate=0.215), recommendation="BUY", current_price=170.0
        )
        delta = build_semantic_delta(a, b)
        attr = delta.attribution
        assert attr.available is True
        # Invariant: no attributed item may render as a zero-dollar contribution.
        assert all(it.formatted_contribution != "$0.00" for it in attr.items)
        # Summary is honest: never claims "assumptions unchanged" when one moved,
        # never names a $0.00 driver.
        assert "$0.00" not in attr.summary_zh
        if not attr.items:
            assert "暂不支持" in attr.summary_zh or "基本未变" in attr.summary_zh
        # No phantom arrow: any driver whose displayed value is unchanged is flat.
        for d in delta.drivers:
            if d.formatted_old == d.formatted_new:
                assert d.direction == "flat", d.key

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

    def test_peer_set_change_flagged_when_comps_pe_moves_materially(self) -> None:
        a = _equity_artifact(
            "art_v1",
            _inputs(),
            recommendation="BUY",
            current_price=170.0,
            peer_tickers=["AMD", "INTC", "QCOM", "AVGO", "TXN", "MRVL"],
            comps_pe_mid=391.95,
        )
        b = _equity_artifact(
            "art_v2",
            _inputs(),
            recommendation="HOLD",
            current_price=170.0,
            peer_tickers=["AMD", "INTC", "QCOM", "AVGO", "TXN", "TSM"],
            comps_pe_mid=276.19,
        )

        delta = build_semantic_delta(a, b)

        flags = [f for f in delta.comparability if f.kind == "peer_set"]
        assert len(flags) == 1
        assert "MRVL→TSM" in flags[0].message_zh
        assert "-29.5%" in flags[0].message_zh
        peer_driver = next(d for d in delta.drivers if d.key == "peer_set")
        assert peer_driver.formatted_old.endswith("MRVL")
        assert peer_driver.formatted_new.endswith("TSM")
        assert peer_driver.caliber_note == "MRVL→TSM"


class TestMixedTzFetchedAt:
    """Regression: BUG-079 — a JSON-round-tripped artifact may carry a naive
    ``data_fetched_at`` while its sibling carries a tz-aware one. The period-gap
    subtraction must normalise both so it never raises
    ``TypeError: can't subtract offset-naive and offset-aware``."""

    def test_naive_vs_aware_fetched_at_does_not_raise(self) -> None:
        naive = datetime(2026, 1, 1, 10, 0)  # tz-naive (no offset in JSON)
        aware = datetime(2026, 1, 1, 10, 0, tzinfo=UTC) + timedelta(days=120)
        a = _equity_artifact(
            "art_v1", _inputs(), recommendation="BUY", current_price=170.0, fetched_at=naive
        )
        b = _equity_artifact(
            "art_v2", _inputs(beta=1.3), recommendation="BUY", current_price=170.0, fetched_at=aware
        )
        assert a.inputs.data_fetched_at.tzinfo is None
        assert b.inputs.data_fetched_at.tzinfo is not None

        delta = build_semantic_delta(a, b)  # must not raise TypeError

        # 120-day gap exceeds the period-drift threshold → flagged, sign-agnostic
        # regardless of which side was naive.
        assert any(f.kind == "period" for f in delta.comparability)

    def test_aware_vs_naive_order_also_safe(self) -> None:
        # Same pairing, opposite argument order — gap stays a sane positive day count.
        aware = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
        naive = datetime(2026, 1, 5, 10, 0)  # 4 days later, naive
        a = _equity_artifact(
            "art_v1", _inputs(), recommendation="BUY", current_price=170.0, fetched_at=aware
        )
        b = _equity_artifact(
            "art_v2", _inputs(), recommendation="BUY", current_price=170.0, fetched_at=naive
        )
        delta = build_semantic_delta(a, b)  # must not raise TypeError
        # 4-day gap is below the 80-day drift threshold → no period flag.
        assert not any(f.kind == "period" for f in delta.comparability)


class TestDataFootnote:
    def test_usd_tag_is_real_not_assumed(self) -> None:
        # DCFInputs now carries a threaded ``currency`` (← FinancialData.
        # quote_currency, default USD), so a normally-built artifact has a REAL
        # tag — the footnote reports the genuine currency, not a disclosed
        # assumption.
        a = _equity_artifact("art_v1", _inputs(), recommendation="BUY", current_price=170.0)
        b = _equity_artifact("art_v2", _inputs(beta=1.3), recommendation="BUY", current_price=170.0)
        fn = build_semantic_delta(a, b).data_footnote
        assert fn.currency == "USD"
        assert fn.currency_assumed is False

    def test_non_usd_currency_threads_into_footnote(self) -> None:
        # A foreign issuer's quote currency (e.g. TWD for a TSM-style ADR) is
        # threaded seed→inputs→result→artifact, so the diff formatter stamps the
        # real currency instead of assuming USD.
        a = _equity_artifact(
            "art_v1", _inputs(currency="TWD"), recommendation="BUY", current_price=170.0
        )
        b = _equity_artifact(
            "art_v2",
            _inputs(beta=1.3, currency="TWD"),
            recommendation="BUY",
            current_price=170.0,
        )
        fn = build_semantic_delta(a, b).data_footnote
        assert fn.currency == "TWD"
        assert fn.currency_assumed is False

    def test_legacy_artifact_without_tag_falls_back_to_disclosed_usd(self) -> None:
        # A pre-field (legacy) artifact whose parameters dump lacks ``currency``
        # still falls back to USD with ``assumed=True`` — a disclosed assumption
        # the UI surfaces, never a silently-stamped "$".
        a = _equity_artifact("art_v1", _inputs(), recommendation="BUY", current_price=170.0)
        b = _equity_artifact("art_v2", _inputs(beta=1.3), recommendation="BUY", current_price=170.0)
        for art in (a, b):
            assert isinstance(art.assumptions.parameters, dict)
            art.assumptions.parameters.pop("currency", None)
        fn = build_semantic_delta(a, b).data_footnote
        assert fn.currency == "USD"
        assert fn.currency_assumed is True


class TestIdentical:
    def test_identical_versions_flagged(self) -> None:
        a = _equity_artifact("art_v1", _inputs(), recommendation="BUY", current_price=170.0)
        b = _equity_artifact("art_v2", _inputs(), recommendation="BUY", current_price=170.0)
        delta = build_semantic_delta(a, b)
        assert delta.identical is True


class TestResidualDominatedAttribution:
    """A move dominated by data re-basing must NOT be framed as 'driven by' a
    minor driver. (AAPL 06-11→06-16: WACC -$0.01 of a -$0.49 move = 2%, yet the
    old summary led with '主因 WACC'.)"""

    def test_residual_dominated_move_does_not_lead_with_minor_driver(self) -> None:
        # Big revenue re-basing (not re-priceable → residual) + a small WACC move.
        a = _equity_artifact(
            "art_v1",
            _inputs(beta=1.10, revenue_base=394e9),
            recommendation="BUY",
            current_price=170.0,
        )
        b = _equity_artifact(
            "art_v2",
            _inputs(beta=1.16, revenue_base=520e9),
            recommendation="BUY",
            current_price=170.0,
        )
        attr = build_semantic_delta(a, b).attribution
        assert attr.available is True
        # The named drivers explain a small minority of the total → reframe fires.
        attributed = sum(it.contribution for it in attr.items)
        assert abs(attributed) < abs(attr.total_change) * 0.5
        # Honest framing: leads with data re-basing, never "driven by X".
        assert "mostly interaction terms and data re-basing" in attr.summary_en
        assert "driven by" not in attr.summary_en
        assert "主要来自交互项与数据重估" in attr.summary_zh
        assert "主因" not in attr.summary_zh

    def test_genuine_single_driver_still_leads_with_it(self) -> None:
        # Only beta (→ WACC) moves → WACC explains ~all of it → keep "driven by".
        a = _equity_artifact(
            "art_v1", _inputs(beta=1.10), recommendation="BUY", current_price=170.0
        )
        b = _equity_artifact(
            "art_v2", _inputs(beta=1.50), recommendation="BUY", current_price=170.0
        )
        attr = build_semantic_delta(a, b).attribution
        assert "driven by" in attr.summary_en
        assert "主因" in attr.summary_zh


class TestMethodSetChange:
    """A valuation method entering/leaving the blend moves the target with no DCF
    assumption changing — the DCF-anchored attribution is blind to it, so a
    method_set comparability flag must explain it. (AAPL: ev_ebitda entered →
    target +11% while every DCF driver stayed flat.)"""

    def test_added_method_flagged(self) -> None:
        a = _equity_artifact(
            "art_v1",
            _inputs(),
            recommendation="SELL",
            current_price=296.0,
            method_mids={"dcf": 190.0, "comps_pe": 200.0},
        )
        b = _equity_artifact(
            "art_v2",
            _inputs(),
            recommendation="SELL",
            current_price=296.0,
            method_mids={"dcf": 190.0, "comps_pe": 202.0, "ev_ebitda": 265.0},
        )
        delta = build_semantic_delta(a, b)
        flags = [f for f in delta.comparability if f.kind == "method_set"]
        assert len(flags) == 1
        assert "EV/EBITDA" in flags[0].message_en
        assert "added" in flags[0].message_en
        assert delta.material_change is True

    def test_same_method_set_no_flag(self) -> None:
        a = _equity_artifact(
            "art_v1",
            _inputs(),
            recommendation="SELL",
            current_price=296.0,
            method_mids={"dcf": 190.0, "comps_pe": 200.0},
        )
        b = _equity_artifact(
            "art_v2",
            _inputs(),
            recommendation="SELL",
            current_price=296.0,
            method_mids={"dcf": 190.0, "comps_pe": 200.0},
        )
        delta = build_semantic_delta(a, b)
        assert not any(f.kind == "method_set" for f in delta.comparability)


class TestMaterialChange:
    """material_change collapses a re-run that only re-based live data."""

    def test_drift_only_is_not_material(self) -> None:
        # Sub-3% target drift (1% revenue re-basing) + a live current_price tick.
        a = _equity_artifact(
            "art_v1", _inputs(revenue_base=394e9), recommendation="SELL", current_price=170.00
        )
        b = _equity_artifact(
            "art_v2", _inputs(revenue_base=398e9), recommendation="SELL", current_price=170.55
        )
        delta = build_semantic_delta(a, b)
        tgt = next(it for it in delta.conclusion if it.key == "target_price")
        assert tgt.pct_change is not None and abs(tgt.pct_change) < 0.03
        assert delta.material_change is False

    def test_rating_flip_is_material(self) -> None:
        a = _equity_artifact("art_v1", _inputs(beta=1.1), recommendation="BUY", current_price=170.0)
        b = _equity_artifact(
            "art_v2", _inputs(beta=1.1), recommendation="SELL", current_price=170.0
        )
        assert build_semantic_delta(a, b).material_change is True
