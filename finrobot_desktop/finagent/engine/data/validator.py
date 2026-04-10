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

from numbers import Real

from finagent.engine.data.interface import DataResult

# field -> relative tolerance (as a fraction)
_RELATIVE_FIELDS: dict[str, float] = {
    "revenue": 0.15,
    "ebitda": 0.15,
    "net_income": 0.15,
    "market_cap": 0.05,
    "total_debt": 0.15,
    "total_cash": 0.15,
}

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
