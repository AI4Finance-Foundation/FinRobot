"""Numeric-audit verifiers — pure functions (ADR-0005 operator layer, zero I/O).

Each verifier takes a snapshot model and returns ``list[Finding]`` against the
numbers that would reach a report. Definitional checks only (no calibrated
thresholds) — the live-quote/divergence bands that need calibration converge with
the data-layer ``validator.py`` + the yfinance throttle roadmap, not here.
"""

from __future__ import annotations

from finrobot.engine.compute.operators.audit.currency_caliber import (
    audit_currency_caliber,
    audit_foreign_issuer_usd_tags,
)
from finrobot.engine.compute.operators.audit.ev_bridge import audit_ev_bridge
from finrobot.engine.compute.operators.audit.narrative_divergence import (
    MomentumContext,
    audit_momentum_narrative_hedge,
    compute_momentum_context,
    is_momentum_divergent,
)
from finrobot.engine.compute.operators.audit.narrative_numeric_grounding import (
    audit_narrative_numeric_grounding,
)
from finrobot.engine.compute.operators.audit.sector_sign import audit_sector_sign
from finrobot.engine.compute.operators.audit.ttm_period import audit_ttm_period
from finrobot.engine.models.financial import FinancialData
from finrobot.engine.models.numeric_claim import ArtifactAudit, Finding

__all__ = [
    "MomentumContext",
    "audit_artifact",
    "audit_company",
    "audit_currency_caliber",
    "audit_ev_bridge",
    "audit_foreign_issuer_usd_tags",
    "audit_momentum_narrative_hedge",
    "audit_narrative_numeric_grounding",
    "audit_sector_sign",
    "audit_ttm_period",
    "compute_momentum_context",
    "is_momentum_divergent",
]


def audit_company(fin: FinancialData) -> list[Finding]:
    """Run every definitional verifier over one company snapshot, in shadow mode
    (collect findings; gating/emit happens at the pipeline layer)."""
    findings: list[Finding] = []
    findings.extend(audit_sector_sign(fin))
    findings.extend(audit_currency_caliber(fin))
    findings.extend(audit_foreign_issuer_usd_tags(fin))
    findings.extend(audit_ev_bridge(fin))
    findings.extend(audit_ttm_period(fin))
    return findings


def audit_artifact(fin: FinancialData | None) -> ArtifactAudit:
    """Roll a company's findings into a report-level data-quality verdict
    (design doc §7, A):

    - any finding → ``caveated`` (the report ships with a data-quality banner; the
      directional verdict is NEVER refused — only annotated);
    - any ``blocked_field`` (category error / dimensionally-corrupt number) →
      ``withhold_valuation`` so the price TARGET is withheld — a target built on an
      untrustworthy number must not be published — while the directional verdict
      still ships from the market-implied read.

    ``unpublishable`` is NOT produced here — that is the critical-data-failure path
    (core price / identity / basic financials unresolvable), handled upstream.
    """
    findings = audit_company(fin) if fin is not None else []
    has_blocked = any(f.severity == "blocked_field" for f in findings)
    has_gating = any(f.severity in ("review", "blocked_field") for f in findings)
    return ArtifactAudit(
        findings=findings,
        artifact_status="caveated" if has_gating else "publishable",
        withhold_valuation=has_blocked,
    )
