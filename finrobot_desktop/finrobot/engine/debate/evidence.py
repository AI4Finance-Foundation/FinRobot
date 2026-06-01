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

from typing import Any

from finrobot.engine.debate.models import Evidence, EvidenceSet


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
        set with ``reliable=False``.
    """
    synthesis: Any = structured_data.get("valuation_synthesis")

    if not isinstance(synthesis, dict):
        return EvidenceSet(
            ticker=str(structured_data.get("ticker", "")),
            artifact_id=artifact_id,
            current_price=float(structured_data.get("current_price", 0)),
            reliable=False,
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
        reliable=bool(synthesis.get("reliable", False)),
        items=items,
    )
