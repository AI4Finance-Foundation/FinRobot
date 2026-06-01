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
    reliable: bool
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
    """Judge's final call after weighing both sides."""

    call: Literal["BUY", "HOLD", "SELL", "REVIEW"]
    conviction: float | None = Field(default=None, ge=0, le=1)
    swing_factor: str
    change_my_mind: str


class DebateResult(BaseModel):
    """Complete output of one debate run."""

    ticker: str
    artifact_id: str
    reliable: bool
    bull: list[VerifiedArgument]
    bear: list[VerifiedArgument]
    divergences: list[DivergencePoint]
    verdict: Verdict
