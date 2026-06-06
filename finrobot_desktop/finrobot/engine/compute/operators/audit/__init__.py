"""Numeric-audit verifiers — pure functions (ADR-0005 operator layer, zero I/O).

Each verifier takes a snapshot model and returns ``list[Finding]`` against the
numbers that would reach a report. Definitional checks only (no calibrated
thresholds) — the live-quote/divergence bands that need calibration converge with
the data-layer ``validator.py`` + the yfinance throttle roadmap, not here.
"""

from __future__ import annotations

from finrobot.engine.compute.operators.audit.currency_caliber import audit_currency_caliber
from finrobot.engine.compute.operators.audit.sector_sign import audit_sector_sign
from finrobot.engine.models.financial import FinancialData
from finrobot.engine.models.numeric_claim import ArtifactAudit, Finding

__all__ = ["audit_artifact", "audit_company", "audit_currency_caliber", "audit_sector_sign"]


def audit_company(fin: FinancialData) -> list[Finding]:
    """Run every definitional verifier over one company snapshot, in shadow mode
    (collect findings; gating/emit happens at the pipeline layer)."""
    findings: list[Finding] = []
    findings.extend(audit_sector_sign(fin))
    findings.extend(audit_currency_caliber(fin))
    return findings


def audit_artifact(fin: FinancialData | None) -> ArtifactAudit:
    """Roll a company's findings into a report-level verdict (design doc §7, A):

    - any finding → ``review_only`` (the report ships with an audit banner);
    - any ``blocked_field`` (category error / dimensionally-corrupt number) →
      ``withhold_valuation`` so the rating is forced REVIEW and the price target
      withheld — a target built on an untrustworthy number must not be published.

    ``unpublishable`` is NOT produced here — that is the critical-data-failure path
    (core price / identity / basic financials unresolvable), handled upstream.
    """
    findings = audit_company(fin) if fin is not None else []
    has_blocked = any(f.severity == "blocked_field" for f in findings)
    has_gating = any(f.severity in ("review", "blocked_field") for f in findings)
    return ArtifactAudit(
        findings=findings,
        artifact_status="review_only" if has_gating else "publishable",
        withhold_valuation=has_blocked,
    )
