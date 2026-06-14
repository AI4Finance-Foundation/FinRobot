"""Extract deterministic Evidence items from an equity_research artifact.

Agents reference numbers only by evidence_id; they never fill numeric fields
themselves (ADR-0007 core invariant).

Only three evidence types are extracted here (Task 2 scope):
  - synthesis.upside_downside
  - synthesis.weighted_price
  - method.<Name>.mid  (one per ValuationMethod)

Further evidence types will be added in subsequent tasks.
"""

from __future__ import annotations

from typing import Any, Literal, get_args

from finrobot.engine.debate.models import Evidence, EvidenceSet

_ConfidenceTier = Literal["high", "medium", "low", "very_low"]
# Mirrors ValuationSynthesis.confidence's own default: a legacy artifact that
# never persisted a tier lands on "low" — graded-down but NOT the most
# conservative "very_low", so a missing field can never silently force the
# worst path (the old `reliable`-defaults-to-False bug that KeyError'd every
# debate to REVIEW after the rename).
_DEFAULT_CONFIDENCE: _ConfidenceTier = "low"
_VALID_TIERS: frozenset[str] = frozenset(get_args(_ConfidenceTier))


def _read_confidence(synthesis: dict[str, Any]) -> _ConfidenceTier:
    """Read the synthesis confidence tier, defaulting to 'low' (NOT the most
    conservative tier) when absent/unrecognised so a missing field never forces
    the worst path."""
    raw = synthesis.get("confidence")
    if isinstance(raw, str) and raw in _VALID_TIERS:
        # str-in-frozenset(get_args(Literal)) narrows the value at runtime;
        # cast keeps mypy's Literal type without a second comparison.
        return raw  # type: ignore[return-value]
    return _DEFAULT_CONFIDENCE


def build_evidence_set(
    structured_data: dict[str, Any],
    artifact_id: str,
) -> EvidenceSet:
    """Build an EvidenceSet from a pipeline's structured_context dict.

    Parameters
    ----------
    structured_data:
        The full structured_context produced by the equity_research pipeline.
        ``valuation_synthesis`` may be a dict (serialized) or absent.
    artifact_id:
        Stable identifier for the artifact run (e.g. the run UUID).

    Returns
    -------
    EvidenceSet
        If ``valuation_synthesis`` is absent or not a dict, returns an empty
        set at the default 'low' confidence tier (no synthesis to grade, but the
        debate still runs and the judge still calls — the empty evidence simply
        leaves arguments ungrounded; uncertainty rides on conviction, not a
        refusal).
    """
    synthesis: Any = structured_data.get("valuation_synthesis")

    if not isinstance(synthesis, dict):
        return EvidenceSet(
            ticker=str(structured_data.get("ticker", "")),
            artifact_id=artifact_id,
            current_price=float(structured_data.get("current_price", 0)),
            confidence=_DEFAULT_CONFIDENCE,
            valuation_withheld=False,
            items=[],
        )

    items: list[Evidence] = []

    upside: Any = synthesis.get("upside_downside")
    if upside is not None:
        # upside_downside is a ratio (e.g. -0.1533); unit is "%", so scale to
        # the percent magnitude (-15.33) — otherwise the LLM reads "-0.15 %" and
        # the UI renders "-0.15%", both off by 100x (口径 bug caught in live smoke).
        items.append(
            Evidence(
                evidence_id="synthesis.upside_downside",
                label="加权隐含上行/下行",
                value=float(upside) * 100.0,
                unit="%",
                formula_id="valuation_synthesis",
            )
        )

    weighted: Any = synthesis.get("weighted_price")
    if weighted is not None:
        items.append(
            Evidence(
                evidence_id="synthesis.weighted_price",
                label="加权目标价",
                value=float(weighted),
                unit="$",
                formula_id="valuation_synthesis",
            )
        )

    for method in synthesis.get("methods", []):
        if not isinstance(method, dict):
            continue
        name: str = str(method.get("name", ""))
        mid: Any = method.get("mid")
        if mid is not None and name:
            # Carry the method's load-bearing assumptions so the debate cites a
            # price with its conditions, never naked. A DCF mid of $73 is an
            # answer under "WACC 16.6% · 5y fade", not a claim the stock is worth
            # $73; the bull/bear/judge agents are instructed to surface this.
            assumptions: Any = method.get("assumptions")
            provenance = {"assumptions": str(assumptions)} if assumptions else None
            items.append(
                Evidence(
                    evidence_id=f"method.{name}.mid",
                    label=f"{name} 中值估值",
                    value=float(mid),
                    unit="$",
                    formula_id=method.get("source"),
                    provenance=provenance,
                )
            )

    return EvidenceSet(
        ticker=str(synthesis.get("ticker", structured_data.get("ticker", ""))),
        artifact_id=artifact_id,
        current_price=float(synthesis.get("current_price", 0)),
        confidence=_read_confidence(synthesis),
        valuation_withheld=bool(synthesis.get("valuation_withheld", False)),
        items=items,
    )
