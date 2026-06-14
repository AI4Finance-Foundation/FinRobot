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
advisory and never gates; ``review`` flags the artifact ``caveated`` (a banner +
disclosure, but the directional verdict still ships); a single ``blocked_field``
withholds that number (and any price-target derived from it) — never the verdict.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Severity = Literal["info", "review", "blocked_field"]
FieldStatus = Literal["pass", "review", "blocked_field"]
# Report-level data-quality status (design doc §7, two-axis status). PUBLISHABLE:
# render as-is. CAVEATED: report ships with a data-quality banner; the directional
# verdict ALWAYS ships, but a price target may be withheld (valuation_withheld)
# when an underlying number is corrupt — the report is not refused, only annotated.
# UNPUBLISHABLE: core price / identity / basic financials unresolvable — reserved
# for the critical-data-failure path, not produced by the definitional verifiers.
# NB: this is the DATA-QUALITY axis, orthogonal to the directional verdict — there
# is no "refuse to rate" state (the deleted REVIEW verdict). Renamed from
# ``review_only`` so no "review" verdict substring is ever emitted.
ArtifactStatus = Literal["publishable", "caveated", "unpublishable"]

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
    plus the rolled-up artifact status and whether the valuation PRICE TARGET must
    be withheld. Behavior A (design doc §7): a ``blocked_field`` (a number that is a
    category error or dimensionally corrupt) withholds the TARGET (the directional
    verdict still ships); a ``review`` finding flags the report ``caveated`` but
    leaves the target. Neither ever refuses the directional rating."""

    model_config = ConfigDict(frozen=True)

    findings: list[Finding] = Field(default_factory=list)
    artifact_status: ArtifactStatus = "publishable"
    withhold_valuation: bool = False
