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

from finrobot.engine.models.financial import ThesisResult
from finrobot.engine.pipelines.equity_research import _reconcile_narrative_targets


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
