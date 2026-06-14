"""Typed contracts for the IC debate pipeline (ADR-0007).

Core invariant: Argument carries zero numeric fields.
Numbers are only accessible via evidence_id → EvidenceSet lookup.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class Evidence(BaseModel):
    """One deterministic data point that agents may reference by id.

    The value is computed by engine/compute, never filled by an LLM.
    """

    evidence_id: str
    label: str
    value: float
    unit: str  # "%" | "x" | "$" | "ratio"
    formula_id: str | None = None
    provenance: dict[str, Any] | None = None
    period_basis: str | None = None


class EvidenceSet(BaseModel):
    """The full set of deterministic evidence extracted from one artifact run."""

    ticker: str
    artifact_id: str
    current_price: float
    # Analytical confidence tier carried from ValuationSynthesis.confidence.
    # The deleted `reliable: bool` was a binary data-health gate that forced the
    # debate to REVIEW; the redesign expresses uncertainty as a tier that caps
    # the judge's conviction (lower confidence → lower conviction), NEVER as a
    # refusal to issue a directional call (绝不 REVIEW).
    confidence: Literal["high", "medium", "low", "very_low"]
    # True when the synthesis honestly withheld its POINT target (corrupt input /
    # method wildly off-market / no anchor). Orthogonal to confidence: the
    # directional VERDICT still ships; only the numeric target is absent. Carried
    # through so callers/UI can disclose it — it never gates the verdict.
    valuation_withheld: bool = False
    items: list[Evidence]

    def by_id(self) -> dict[str, Evidence]:
        """Return a mapping from evidence_id to Evidence for O(1) lookup."""
        return {e.evidence_id: e for e in self.items}


class Argument(BaseModel):
    """One bull or bear argument.

    Red line: no numeric fields. Agents can only reference numbers by
    citing evidence_ids that exist in the EvidenceSet. The render layer
    resolves values at display time.
    """

    claim: str
    evidence_ids: list[str] = Field(default_factory=list)


class SideCase(BaseModel):
    """The full set of arguments for one side of the debate."""

    side: Literal["bull", "bear"]
    arguments: list[Argument]


class VerifiedArgument(BaseModel):
    """An Argument after verifier claim-entailment check."""

    side: Literal["bull", "bear"]
    claim: str
    evidence_ids: list[str]
    verified: bool
    reason: str


class DivergencePoint(BaseModel):
    """A single assumption where bull and bear disagree, with recomputed prices."""

    assumption: str  # e.g. "wacc" / "terminal_growth"
    bull_value: float
    bear_value: float
    bull_implied_price: float | None = None
    bear_implied_price: float | None = None


class Verdict(BaseModel):
    """Judge's final call after weighing both sides.

    Always directional — the REVIEW state is deleted. Uncertainty is expressed
    as a lower ``conviction`` (capped by the synthesis confidence tier in
    service.py) plus an honest caveat in ``change_my_mind``, never a refusal to
    call (mirrors the equity-research verdict dial; CLAUDE.md 核心契约②).
    """

    call: Literal["BUY", "HOLD", "SELL"]
    conviction: float | None = Field(default=None, ge=0, le=1)
    swing_factor: str
    change_my_mind: str


class DebateResult(BaseModel):
    """Complete output of one debate run."""

    ticker: str
    artifact_id: str
    # Confidence tier carried from the synthesis (replaces the binary
    # `reliable`). The verdict is always directional; this tier explains how
    # firmly, and caps verdict.conviction.
    confidence: Literal["high", "medium", "low", "very_low"]
    valuation_withheld: bool = False
    bull: list[VerifiedArgument]
    bear: list[VerifiedArgument]
    divergences: list[DivergencePoint]
    verdict: Verdict
