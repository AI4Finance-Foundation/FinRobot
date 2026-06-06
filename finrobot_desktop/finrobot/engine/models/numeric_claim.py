"""Report numeric-audit ledger — leaf model (ADR-0005 leaf layer, importable by
compute / pipeline / artifact alike).

A :class:`Finding` is one audit verdict on one number, produced by the pure
verifiers in ``engine/compute/operators/audit/``. A :class:`NumericClaim` is the
ledger entry for one number that reaches a report: its value + caliber
(currency/period) + provenance + the findings against it. ``field_key`` references
the static caliber registry (``artifact/field_registry.py``); this model does NOT
duplicate that table — it carries the runtime value/findings the static table
must never hold (design doc §4, ADR-0010 layering).

The gate verdict is a rollup: the worst finding severity wins. ``info`` is
advisory and never gates; ``review`` forces a REVIEW-only artifact; a single
``blocked_field`` withholds that number (and any price-target derived from it).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Severity = Literal["info", "review", "blocked_field"]
FieldStatus = Literal["pass", "review", "blocked_field"]
# Report-level verdict (design doc §7, two-axis status). PUBLISHABLE: render as-is.
# REVIEW_ONLY: report ships but rating forced REVIEW / price target may be withheld.
# UNPUBLISHABLE: core price / identity / basic financials unresolvable — reserved
# for the critical-data-failure path, not produced by the definitional verifiers.
ArtifactStatus = Literal["publishable", "review_only", "unpublishable"]

# Severity precedence for the rollup. Higher = stronger gate.
_SEVERITY_RANK: dict[Severity, int] = {"info": 0, "review": 1, "blocked_field": 2}


class Finding(BaseModel):
    """One audit verdict on one number. Immutable — a verifier emits it, nobody
    edits it downstream."""

    model_config = ConfigDict(frozen=True)

    field_key: str
    """Which number, e.g. ``"ev_ebitda"`` / ``"pe_ratio"`` (references FieldCaliber)."""
    check: str
    """Stable rule id, e.g. ``"financial_sector_ev_meaningless"``."""
    severity: Severity
    evidence: str
    """Human-readable reason carrying the actual numbers — for the audit banner."""


def rollup_status(findings: list[Finding]) -> FieldStatus:
    """Reduce findings to one field status: worst severity wins.

    No findings (or info-only) → ``pass`` (info is advisory, never gates).
    Any ``review`` → ``review``. Any ``blocked_field`` → ``blocked_field``.
    """
    worst = max((_SEVERITY_RANK[f.severity] for f in findings), default=0)
    if worst >= _SEVERITY_RANK["blocked_field"]:
        return "blocked_field"
    if worst >= _SEVERITY_RANK["review"]:
        return "review"
    return "pass"


class NumericClaim(BaseModel):
    """Ledger entry for one report number. Assembled at the pipeline/artifact layer
    (joins a verifier's findings with ``field_registry`` caliber); ``field_key``
    references the static registry rather than duplicating it."""

    model_config = ConfigDict(frozen=False)

    field_key: str
    value: float | None = None
    currency: str | None = None
    period: str | None = None  # TTM / NTM / FY
    source: str | None = None
    as_of: str | None = None
    findings: list[Finding] = Field(default_factory=list)

    @property
    def field_status(self) -> FieldStatus:
        return rollup_status(self.findings)


class ArtifactAudit(BaseModel):
    """Report-level numeric-audit verdict: the findings against a report's numbers
    plus the rolled-up artifact status and whether the valuation (rating / price
    target) must be withheld. Behavior A (design doc §7): a ``blocked_field`` (a
    number that is a category error or dimensionally corrupt) withholds the target;
    a ``review`` finding flags the report REVIEW_ONLY but leaves the target."""

    model_config = ConfigDict(frozen=True)

    findings: list[Finding] = Field(default_factory=list)
    artifact_status: ArtifactStatus = "publishable"
    withhold_valuation: bool = False
