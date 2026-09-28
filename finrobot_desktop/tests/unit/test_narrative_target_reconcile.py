"""BUG-016 guard: free-text narrative $-amounts must reconcile with the
canonical (deterministic) price target.

After the override block forces `price_target` to the confidence-weighted
canonical value, the headline-bearing prose fields from the SAME LLM call can
still print a contradicting $ amount (table says $276.43, prose says "约 $280").
`_reconcile_narrative_targets` is the code-only post-run guard that neutralizes
the drifting token to the canonical value — no second LLM call.
"""

from __future__ import annotations

import logging

from finrobot.engine.compute.operators.valuation_synthesis import CanonicalThesis
from finrobot.engine.models.financial import (
    ThesisResult,
    ValuationMethod,
    ValuationSynthesis,
)
from finrobot.engine.pipelines.equity_research import (
    _reconcile_narrative_targets,
    apply_canonical_override,
)


def _thesis(**overrides: object) -> ThesisResult:
    base: dict[str, object] = {
        "recommendation": "HOLD",
        "price_target": 276.43,
        "price_target_basis": "Confidence-weighted synthesis.",
        "catalysts": ["iPhone refresh cycle"],
        "risks": ["China demand softness"],
        "narrative": "Apple remains a quality compounder.",
    }
    base.update(overrides)
    return ThesisResult(**base)  # type: ignore[arg-type]


def test_drifting_prose_amount_is_neutralized_to_canonical(
    caplog: object,
) -> None:
    thesis = _thesis(
        valuation_overview=(
            "Weighting DCF and comps, we arrive at a fair value of roughly $280, "
            "implying modest upside from current levels."
        ),
    )

    with caplog.at_level(logging.WARNING):  # type: ignore[attr-defined]
        out, drift = _reconcile_narrative_targets(
            thesis, canonical_target=276.43, allowed_mids=[260.0, 295.0]
        )

    assert drift is True
    assert out.valuation_overview is not None
    assert "$280" not in out.valuation_overview
    assert "$276.43" in out.valuation_overview
    # Sentence structure preserved (least-invasive token swap).
    assert "implying modest upside" in out.valuation_overview
    # A drift warning was logged.
    assert any(  # type: ignore[attr-defined]
        "narrative target drift" in rec.message or "narrative target drift" in rec.getMessage()
        for rec in caplog.records  # type: ignore[attr-defined]
    )


def test_magnitude_suffixed_amounts_are_never_rewritten() -> None:
    """$3.41T / $391.0B / $3.4 billion are market-cap/EV-scale facts, not
    per-share targets. The reconciler used to match only the numeric body
    ("$3.41"), fail the whitelist, and rewrite it to the canonical target —
    shipping "$276.43T". Suffixed amounts are out of scope entirely (the
    report-level drift scanner owns them)."""
    thesis = _thesis(
        competitor_analysis=(
            "Versus megacap peers (market_cap=$3.41T) and an EV of $391.0B, "
            "the segment generates $3.4 billion in services revenue and "
            "carries $150B of net cash; smaller rival sits at $920.5M."
        ),
    )

    out, drift = _reconcile_narrative_targets(
        thesis, canonical_target=276.43, allowed_mids=[260.0, 295.0]
    )

    assert drift is False
    assert out.competitor_analysis == thesis.competitor_analysis


def test_minus_prefixed_amounts_are_never_rewritten() -> None:
    """-$1.20 (loss-quarter EPS / negative FCF per share) is categorically not a
    restatement of the positive canonical target. The reconciler used to match
    only the "$1.20" span, fail the whitelist, and rewrite it — shipping the
    sign-corrupted "-$276.43". Minus-prefixed amounts are out of scope (the
    report-level drift scanner validates them sign-aware against all leaves)."""
    thesis = _thesis(
        valuation_overview=("FY1 EPS of -$1.20 and FCF/share of −$0.85 keep the DCF inapplicable."),
    )

    out, drift = _reconcile_narrative_targets(
        thesis, canonical_target=276.43, allowed_mids=[260.0, 295.0]
    )

    assert drift is False
    assert out.valuation_overview == thesis.valuation_overview


def test_plain_drift_amount_followed_by_word_still_rewritten() -> None:
    """The optional-suffix group must not swallow ordinary words: "$280 Buyback"
    is still a plain drifting per-share amount (B is followed by word chars, so
    the \\b suffix boundary fails) and must be neutralized."""
    thesis = _thesis(
        valuation_overview="Fair value near $280 Buyback support adds a floor.",
    )

    out, drift = _reconcile_narrative_targets(thesis, canonical_target=276.43, allowed_mids=[])

    assert drift is True
    assert out.valuation_overview is not None
    assert "$276.43 Buyback" in out.valuation_overview


def test_happy_path_matching_amount_is_untouched() -> None:
    overview = "Our weighted target of $276.43 reflects a balanced DCF/comps blend."
    thesis = _thesis(valuation_overview=overview)

    out, drift = _reconcile_narrative_targets(
        thesis, canonical_target=276.43, allowed_mids=[260.0, 295.0]
    )

    assert drift is False
    assert out.valuation_overview == overview


def test_within_tolerance_amount_is_untouched() -> None:
    # $277 is within 2% of $276.43 — not drift.
    overview = "We see fair value near $277, broadly in line with our weighted target."
    thesis = _thesis(valuation_overview=overview)

    out, drift = _reconcile_narrative_targets(thesis, canonical_target=276.43, allowed_mids=[])

    assert drift is False
    assert out.valuation_overview == overview


def test_per_method_mid_is_whitelisted_not_drift() -> None:
    # Quoting a per-method mid ("DCF $260, comps $295, they disagree") is the
    # honest narrative — must NOT be neutralized even though it != target.
    overview = "DCF implies $260 while comps imply $295; the blend lands at $276.43."
    thesis = _thesis(valuation_overview=overview)

    out, drift = _reconcile_narrative_targets(
        thesis, canonical_target=276.43, allowed_mids=[260.0, 295.0]
    )

    assert drift is False
    assert out.valuation_overview == overview


def test_drift_scanned_across_tagline_and_takeaways() -> None:
    thesis = _thesis(
        tagline="AAPL · fair value ~$280, room to run",
        key_takeaways=[
            "Services margin expansion intact",
            "Our $280 target implies single-digit upside",
        ],
    )

    out, drift = _reconcile_narrative_targets(thesis, canonical_target=276.43, allowed_mids=[])

    assert drift is True
    assert out.tagline is not None and "$280" not in out.tagline
    assert "$276.43" in out.tagline
    assert out.key_takeaways is not None
    assert all("$280" not in tk for tk in out.key_takeaways)
    assert any("$276.43" in tk for tk in out.key_takeaways)


def test_four_digit_target_amount_not_truncated_and_doubled() -> None:
    """BUG (MU 2026-06-07): ``_DOLLAR_RE`` truncated a bare 4+ digit $-amount to
    its first 3 digits — ``$2172.06`` matched only ``$217`` — so the reconciler
    saw ``217 != 2172.06`` = drift and rewrote ``$217`` → ``$2172.06``, leaving
    the orphan ``2.06`` tail → ``$2172.062.06`` (the exact garbage in the shipped
    basis string). A $-amount equal to the canonical target must round-trip
    untouched regardless of magnitude — no comma, four+ digits, and all.
    """
    overview = "Our comps target of $2172.06 reflects peer forward multiples."
    thesis = _thesis(price_target=2172.06, valuation_overview=overview)

    out, drift = _reconcile_narrative_targets(
        thesis, canonical_target=2172.06, allowed_mids=[2172.06], current_price=864.01
    )

    assert drift is False
    assert out.valuation_overview == overview
    assert "$2172.062.06" not in (out.valuation_overview or "")


def test_four_digit_drift_amount_neutralized_to_full_token() -> None:
    """A contradicting bare 4-digit prose amount is rewritten to the WHOLE
    canonical token, never a truncated fragment: ``$5000`` → ``$2172.06`` (and
    never ``$2172.060`` from a partial ``$500`` match)."""
    overview = "We peg fair value near $5000, well above current levels."
    thesis = _thesis(price_target=2172.06, valuation_overview=overview)

    out, drift = _reconcile_narrative_targets(thesis, canonical_target=2172.06, allowed_mids=[])

    assert drift is True
    assert "$5000" not in (out.valuation_overview or "")
    assert "$2172.06" in (out.valuation_overview or "")
    # No orphaned digit tail from a truncated match.
    assert "$2172.060" not in (out.valuation_overview or "")


def test_comma_grouped_thousands_amount_still_matches() -> None:
    """The fix (require ≥1 comma group in the separated alternative) must NOT
    regress the comma path: ``$2,172.06`` stays whitelisted as the canonical
    target and is left untouched."""
    overview = "The weighted target of $2,172.06 anchors our view."
    thesis = _thesis(price_target=2172.06, valuation_overview=overview)

    out, drift = _reconcile_narrative_targets(thesis, canonical_target=2172.06, allowed_mids=[])

    assert drift is False
    assert out.valuation_overview == overview


def test_drift_scanned_across_all_narrative_fields() -> None:
    # BUG-087 ③: the guard previously only scanned valuation_overview / tagline /
    # key_takeaways — an injected fake $ in company_overview / competitor_analysis
    # / news_summary / narrative survived into the artifact. Now all are scanned.
    thesis = _thesis(
        narrative="Bottom line, we peg fair value at $280.",
        company_overview="Apple's segments support a $280 valuation.",
        competitor_analysis="Versus peers, AAPL warrants $280.",
        news_summary="Headlines hint the Street sees $280.",
    )

    out, drift = _reconcile_narrative_targets(thesis, canonical_target=276.43, allowed_mids=[])

    assert drift is True
    for field in ("narrative", "company_overview", "competitor_analysis", "news_summary"):
        value = getattr(out, field)
        assert value is not None
        assert "$280" not in value, f"{field} still contains the injected $280"
        assert "$276.43" in value, f"{field} was not neutralized to canonical"


def test_published_value_band_bounds_survive_withheld_path_scrub() -> None:
    """撤点≠撤区间: the published value-band bounds (target_low/high — e.g. a bank's
    residual-income band [RI@trailing, RI@forward]) appear in the DETERMINISTIC
    canonical basis but are NOT per-method mids. On the withheld path the narrative
    scrubber must NOT erase them to "[target withheld]" — they are published values
    the basis is meant to show.

    Regression for the JPM bug: a withheld-point bank report shipped
    ``price_target_basis`` reading "... value band [[target withheld], [target
    withheld]]" while structured ``valuation_synthesis`` still carried the real
    [$263.24, $356.15] band, because ``allowed_mids`` was built from method mids
    only and the scrubber ate the band the basis publishes.
    """
    methods = [
        ValuationMethod(
            name="comps_pb", low=250, mid=266.96, high=285, confidence=0.6, source="PB"
        ),
        ValuationMethod(
            name="comps_pe", low=255, mid=269.79, high=288, confidence=0.8, source="PE"
        ),
        ValuationMethod(
            name="residual_income", low=263.24, mid=300.04, high=356.15, confidence=0.7, source="RI"
        ),
    ]
    vs = ValuationSynthesis(
        methods=methods,
        weighted_price=None,
        current_price=334.14,
        upside_downside=None,
        confidence="high",
        target_low=263.24,
        target_high=356.15,
        anchor_method="residual_income",
        valuation_withheld=True,
    )
    # The deterministic canonical basis the bank RI-band path emits (the bounds are
    # NOT method mids: $263.24 is 1.4% off comps_pb $266.96, $356.15 is 18.7% off
    # the nearest mid $300.04 — both fail the per-mid whitelist before the fix).
    basis = (
        "FAIRLY VALUED: price $334.14 sits within the residual-income fair-value band "
        "[$263.24, $356.15] (RI at trailing ROE → at FY1 consensus ROE), so there is no "
        "margin of safety either way — verdict HOLD. Methods: comps_pb=$266.96, "
        "comps_pe=$269.79, residual_income=$300.04."
    )
    canonical = CanonicalThesis(
        target=None,
        verdict="HOLD",
        basis=basis,
        upside=None,
        valuation_withheld=True,
        confidence="high",
    )
    thesis = _thesis(recommendation="HOLD", price_target=None, price_target_basis="(LLM draft)")

    out = apply_canonical_override(thesis, canonical, vs)

    assert out.price_target_basis is not None
    assert "[target withheld]" not in out.price_target_basis, (
        "published value-band bounds were washed to the withheld marker — 撤点≠撤区间 reverted"
    )
    assert "$263.24" in out.price_target_basis
    assert "$356.15" in out.price_target_basis
