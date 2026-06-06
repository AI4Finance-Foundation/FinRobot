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
from finrobot.engine.models.numeric_claim import Finding

__all__ = ["audit_company", "audit_currency_caliber", "audit_sector_sign"]


def audit_company(fin: FinancialData) -> list[Finding]:
    """Run every definitional verifier over one company snapshot, in shadow mode
    (collect findings; gating/emit happens at the pipeline layer)."""
    findings: list[Finding] = []
    findings.extend(audit_sector_sign(fin))
    findings.extend(audit_currency_caliber(fin))
    return findings
