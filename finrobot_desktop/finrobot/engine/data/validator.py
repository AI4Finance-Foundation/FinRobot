"""Cross-provider data validation for financials data.

Deterministic numeric comparator used by DataLayer.fetch() when more than
one provider can service a ``financials`` request. If the two providers
disagree beyond a conservative threshold, a warning is appended to the
primary DataResult and surfaced to the LLM via to_context_string().

Thresholds (conservative, chosen so TTM vs. latest-fiscal-year differences
don't trip the validator for most companies):

- revenue / ebitda / net_income / total_debt / total_cash: 15% relative
  (covers one quarter of timing drift).
- market_cap: 5% relative (real-time vs. delayed should still be close).
- gross_margin / operating_margin: 10 percentage-point absolute.

Only applies to data_type == "financials". Price and news have different
field structures and are not cross-validated here.

What this code does that raw LLM cannot: deterministic numeric agreement
checks between two APIs. An LLM would not autonomously call two APIs and
compare the numbers.
"""

from __future__ import annotations

import logging
from numbers import Real

from finrobot.engine.data.interface import DataResult

logger = logging.getLogger(__name__)

# field -> relative tolerance (as a fraction)
_RELATIVE_FIELDS: dict[str, float] = {
    "revenue": 0.15,
    "ebitda": 0.15,
    "net_income": 0.15,
    "market_cap": 0.05,
    "total_debt": 0.15,
    "total_cash": 0.15,
}

# KEY fundamentals that drive valuation (DCF numerator / comps base). An
# over-tolerance divergence on these is escalated from a prose warning to a
# STRUCTURED Provenance.degraded marker (BUG-007) so dcf_seed / comps can
# react programmatically. The primary value still flows — this only flags it.
_KEY_FIELDS: tuple[str, ...] = ("revenue", "net_income")

# field -> absolute tolerance (in percentage points, since these are fractions)
_ABSOLUTE_FIELDS: dict[str, float] = {
    "gross_margin": 0.10,
    "operating_margin": 0.10,
}


def _is_number(v: object) -> bool:
    # bool is a subclass of int; exclude it to avoid comparing True/False as numbers.
    return isinstance(v, Real) and not isinstance(v, bool)


def cross_validate(primary: DataResult, secondary: DataResult) -> list[str]:
    """Compare two financials DataResults for the same ticker.

    Returns a list of human-readable warning strings for any discrepancies.
    An empty list means the two providers agree within tolerance.

    Only fields present in BOTH results are checked. Missing fields are not
    flagged — that is the extractor's responsibility.
    """
    warnings: list[str] = []
    p, s = primary.data, secondary.data

    # D5: empty secondary data → warn instead of silently passing all checks
    if not s:
        return [
            f"Secondary provider {secondary.provider} returned empty data "
            f"— cross-validation skipped"
        ]

    for field, tolerance in _RELATIVE_FIELDS.items():
        pv, sv = p.get(field), s.get(field)
        if pv is None or sv is None:
            continue
        if not _is_number(pv) or not _is_number(sv):
            continue
        if pv == 0 and sv == 0:
            continue
        denominator = max(abs(pv), abs(sv))
        if denominator == 0:
            continue
        rel_diff = abs(pv - sv) / denominator
        if rel_diff > tolerance:
            warnings.append(
                f"Data discrepancy: {field} differs by {rel_diff:.0%} "
                f"({primary.provider}: {pv:,.0f} vs "
                f"{secondary.provider}: {sv:,.0f}). "
                f"Threshold: {tolerance:.0%}."
            )

    for field, tolerance in _ABSOLUTE_FIELDS.items():
        pv, sv = p.get(field), s.get(field)
        if pv is None or sv is None:
            continue
        if not _is_number(pv) or not _is_number(sv):
            continue
        abs_diff = abs(pv - sv)
        if abs_diff > tolerance:
            warnings.append(
                f"Data discrepancy: {field} differs by {abs_diff * 100:.1f}pp "
                f"({primary.provider}: {pv:.1%} vs "
                f"{secondary.provider}: {sv:.1%}). "
                f"Threshold: {tolerance * 100:.0f}pp."
            )

    return warnings


# --- Market-cap consistency (lineage-aware) ----------------------------------
#
# Validates the accounting identity market_cap ≈ price × shares_outstanding —
# BUT only when ``shares_outstanding`` comes from a source INDEPENDENT of
# market_cap. The trap this avoids: FMP has no raw share count, so its
# ``shares_outstanding`` is rederived as ``int(market_cap / price)``
# (fmp_provider.py:378). Checking ``market_cap ≈ price × (market_cap/price)`` is
# a tautology — it can never fail and carries zero information (a "False
# Validation"). yfinance/Finnhub report shares straight from filings, so they ARE
# independent. We detect a derived share count empirically (shares ≈ mc/price)
# rather than hardcoding provider names, and ABSTAIN (return []) when no
# independent count exists — we never emit a spurious "consistent" signal.
#
# When an independent count IS available, the implied-vs-reported RATIO is
# classified by share-structure band instead of a hardcoded GOOG/META allowlist:
# multi-class issuers (Alphabet GOOGL/GOOG, Meta A/B) legitimately carry a market
# cap spanning all classes while a single-class share count is reported. The
# output is always a WARNING, never an error — the primary value still flows.

# shares within this relative distance of mc/price is treated as rederived from
# them (i.e. NOT an independent source), so it can't validate its own parents.
_SHARES_DERIVED_EPS = 1e-3

# implied_shares / reported_shares → (low, high_inclusive, english_label).
# Gaps between bands and the open ends fall through to the anomaly branch.
_SINGLE_CLASS_LO, _SINGLE_CLASS_HI = 0.9, 1.1


def _num(v: object) -> float | None:
    """Coerce to float iff v is a real number (excluding bool); else None."""
    return float(v) if isinstance(v, Real) and not isinstance(v, bool) else None


def _coherent_mc_price(result: DataResult) -> tuple[float, float] | None:
    """Return (market_cap, price) from one result iff both are positive numbers."""
    mc = _num(result.data.get("market_cap"))
    px = _num(result.data.get("current_price")) or _num(result.data.get("price"))
    if mc is not None and px is not None and mc > 0 and px > 0:
        return mc, px
    return None


def _independent_shares(result: DataResult) -> float | None:
    """Return this result's reported share count iff it is NOT derived as mc/price.

    A count within ``_SHARES_DERIVED_EPS`` of the result's own ``mc/price`` is
    rederived (the FMP lineage trap) and returns None — it cannot independently
    validate the very fields it was computed from.
    """
    sh = _num(result.data.get("shares_outstanding"))
    if sh is None or sh <= 0:
        return None
    mc_px = _coherent_mc_price(result)
    if mc_px is not None:
        mc, px = mc_px
        if abs(sh - mc / px) / sh < _SHARES_DERIVED_EPS:
            return None  # derived from this result's own market_cap/price
    return sh


def market_cap_consistency(primary: DataResult, secondary: DataResult) -> list[str]:
    """Lineage-aware check of market_cap ≈ price × shares_outstanding.

    Computes ``implied = market_cap / price`` from any result carrying both, then
    compares it to an INDEPENDENT reported share count (one not rederived as
    mc/price). Returns a single share-structure WARNING when the ratio leaves the
    single-class band, or ``[]`` when consistent OR when no independent share
    count exists (abstain — never a false "consistent" pass).
    """
    results = (primary, secondary)

    mc_px: tuple[float, float] | None = None
    for r in results:
        mc_px = _coherent_mc_price(r)
        if mc_px is not None:
            break
    if mc_px is None:
        return []
    mc, price = mc_px
    implied = mc / price

    reported: float | None = None
    source: str = ""
    for r in results:
        ind = _independent_shares(r)
        if ind is not None:
            reported, source = ind, r.provider
            break
    if reported is None:
        # FMP-only lineage trap: every available share count is mc/price.
        logger.debug(
            "market_cap_consistency abstained for %s — no independent share count "
            "(all derived as market_cap/price)",
            primary.ticker,
        )
        return []

    ratio = implied / reported
    if _SINGLE_CLASS_LO <= ratio <= _SINGLE_CLASS_HI:
        return []  # single share class — consistent, nothing to flag

    if 1.8 <= ratio <= 2.5:
        label = "likely multi-class equity (dual-class, e.g. Alphabet GOOGL/GOOG)"
    elif 2.5 < ratio <= 4.5:
        label = "likely triple-class equity"
    elif _SINGLE_CLASS_HI < ratio < 1.8:
        label = "minor mismatch — float vs shares-outstanding, partial share class, or stale count"
    else:
        label = "anomalous — possible ADR ratio, unit mismatch, or wrong share count; verify"

    return [
        f"Market-cap consistency: implied shares (market_cap/price = {implied:,.0f}) "
        f"vs reported shares ({source}: {reported:,.0f}) → ratio {ratio:.2f}. {label}."
    ]


def key_field_divergences(primary: DataResult, secondary: DataResult) -> list[str]:
    """KEY fields (revenue / net_income) that diverge beyond tolerance between
    two financials providers.

    Companion to :func:`cross_validate` for the BUG-007 structured-degradation
    channel: ``cross_validate`` produces human-readable warnings for ALL fields,
    while this returns just the over-tolerance KEY field NAMES so the caller can
    stamp a ``provider_divergence:<field>`` marker onto ``Provenance.degraded``.
    Same tolerances, same numeric guards — it does NOT introduce a second
    threshold (CLAUDE.md: no parallel divergence definition).

    Empty list when the providers agree within tolerance on the key fields, or
    when the secondary returned empty data (no comparison possible).
    """
    diverged: list[str] = []
    p, s = primary.data, secondary.data
    if not s:
        return diverged

    for field in _KEY_FIELDS:
        tolerance = _RELATIVE_FIELDS[field]
        pv, sv = p.get(field), s.get(field)
        if pv is None or sv is None:
            continue
        if not _is_number(pv) or not _is_number(sv):
            continue
        if pv == 0 and sv == 0:
            continue
        denominator = max(abs(pv), abs(sv))
        if denominator == 0:
            continue
        if abs(pv - sv) / denominator > tolerance:
            diverged.append(field)

    return diverged
