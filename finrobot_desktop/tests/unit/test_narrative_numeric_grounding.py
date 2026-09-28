"""Tests for the numeric-grounding narrative backstop (BACKLOG A3/P1-2).

Pure, deterministic — no LLM involved. Pins:
  - _has_grounding_number's digit-detection (via the public audit function):
    a real number (currency/percent/multiple/count) counts as grounding; a bare
    calendar year or ordinal alone does NOT (that was the exact false-leniency
    the design grill flagged — a template sentence with only "in fiscal 2025"
    must still be flagged as ungrounded).
  - audit_narrative_numeric_grounding's warning-vs-silent behavior per field
    (narrative / each catalysts entry / each risks entry), never touching
    verdict / target / confidence.
"""

from __future__ import annotations

from finrobot.engine.compute.operators.audit.narrative_numeric_grounding import (
    audit_narrative_numeric_grounding,
)
from finrobot.engine.models.financial import ThesisResult


def _thesis(
    *,
    narrative: str = "Grounded narrative with a 27% margin figure.",
    catalysts: list[str] | None = None,
    risks: list[str] | None = None,
) -> ThesisResult:
    return ThesisResult(
        recommendation="BUY",
        price_target=100.0,
        price_target_basis="test basis",
        narrative=narrative,
        catalysts=catalysts or ["Cloud revenue growing 27% YoY, per the whitelisted figure."],
        risks=risks or ["Peer median EV/EBITDA of 12.4x implies limited re-rating room."],
    )


class TestAuditNarrativeNumericGrounding:
    def test_fully_grounded_thesis_is_silent(self) -> None:
        thesis = _thesis()
        assert audit_narrative_numeric_grounding(thesis) is None

    def test_verdict_only_narrative_warns(self) -> None:
        thesis = _thesis(narrative="The stock is attractively valued with a resilient moat.")
        warning = audit_narrative_numeric_grounding(thesis)
        assert warning is not None
        assert "[NARRATIVE-NUMERIC]" in warning
        assert "narrative" in warning

    def test_verdict_only_catalyst_warns_with_index(self) -> None:
        thesis = _thesis(
            catalysts=[
                "Revenue grew 12% YoY, ahead of the peer median.",
                "The company is well-positioned for continued growth.",
            ]
        )
        warning = audit_narrative_numeric_grounding(thesis)
        assert warning is not None
        assert "catalysts[1]" in warning
        assert "catalysts[0]" not in warning

    def test_verdict_only_risk_warns_with_index(self) -> None:
        thesis = _thesis(
            risks=[
                "Margin pressure from a competitive market with no clear moat.",
                "Trades at 18.2x forward earnings, a premium to the 12.4x peer median.",
            ]
        )
        warning = audit_narrative_numeric_grounding(thesis)
        assert warning is not None
        assert "risks[0]" in warning
        assert "risks[1]" not in warning

    def test_multiple_ungrounded_fields_all_listed(self) -> None:
        thesis = _thesis(
            narrative="A strong moat supports the thesis.",
            catalysts=["Well-positioned for growth."],
            risks=["Faces competitive headwinds."],
        )
        warning = audit_narrative_numeric_grounding(thesis)
        assert warning is not None
        assert "3 narrative field(s)" in warning
        assert "narrative" in warning
        assert "catalysts[0]" in warning
        assert "risks[0]" in warning

    def test_bare_year_alone_does_not_count_as_grounding(self) -> None:
        """A lone calendar-year mention ('in fiscal 2025') must NOT satisfy the
        grounding check — the whole point is to catch prose that name-drops a
        date but states no real figure."""
        thesis = _thesis(narrative="In fiscal 2025, the company remained well-positioned.")
        warning = audit_narrative_numeric_grounding(thesis)
        assert warning is not None
        assert "narrative" in warning

    def test_bare_ordinal_alone_does_not_count_as_grounding(self) -> None:
        thesis = _thesis(narrative="Growth accelerated in the 1st half, a positive signal.")
        warning = audit_narrative_numeric_grounding(thesis)
        assert warning is not None

    def test_year_plus_real_number_counts_as_grounded(self) -> None:
        """A year alongside a REAL figure must still pass — only the bare-year
        case is excluded, not any sentence that happens to mention a year."""
        thesis = _thesis(narrative="In fiscal 2025, revenue grew 14% YoY.")
        assert audit_narrative_numeric_grounding(thesis) is None

    def test_percent_sign_counts_as_grounding(self) -> None:
        thesis = _thesis(narrative="Operating margin expanded to 34.2%, well above peers.")
        assert audit_narrative_numeric_grounding(thesis) is None

    def test_multiple_notation_counts_as_grounding(self) -> None:
        thesis = _thesis(narrative="Trades at 15.2x forward earnings versus a 12.4x peer median.")
        assert audit_narrative_numeric_grounding(thesis) is None

    def test_currency_amount_counts_as_grounding(self) -> None:
        thesis = _thesis(narrative="The DCF implies a fair value of $187.40 per share.")
        assert audit_narrative_numeric_grounding(thesis) is None

    def test_empty_string_fields_are_not_flagged(self) -> None:
        """An empty/whitespace-only entry has nothing to ground — not this
        function's concern (schema min_length=1 / required-field validation
        catches emptiness elsewhere); it must not double-report as ungrounded."""
        thesis = _thesis(narrative="   ", catalysts=["   "], risks=["   "])
        assert audit_narrative_numeric_grounding(thesis) is None
