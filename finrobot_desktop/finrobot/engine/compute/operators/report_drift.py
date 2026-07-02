"""Report narrative drift detector — pure (ADR-0005 operator layer, zero I/O).

The report step is a pure LLM assembly: its mandate is to arrange numbers that
were already computed (and frozen into the artifact snapshot) into chapters, so
every monetary amount it prints should trace to SOME numeric leaf of that
snapshot. Three bands, by relative distance to the NEAREST leaf:

  · ≤ ``NARRATIVE_DRIFT_TOLERANCE`` (1%)      — verified; untouched.
  · ≤ ``NARRATIVE_APPROXIMATION_BAND`` (10%)  — an LLM approximation of a real
    computed value ("roughly $400B" vs a $391B leaf, 2.3%); kept in prose,
    surfaced for review. Redacting these mutilated legitimate narrative.
  · beyond the band — near NOTHING the artifact computed; a fabrication or a
    materially wrong figure (calibration corpus: "$1.58 trillion" 15% off,
    "$-31892M" 102% off). These ORPHANS are the only tokens a builder may
    redact.

At 1% an approximation and a fabrication are mechanically indistinguishable;
distance-to-nearest-leaf is what separates them — an approximation is NEAR
something, a fabrication is near nothing (band calibrated on the stored-artifact
corpus, see ``reconcile_tolerances``). The guard still NEVER REWRITES a value:
with hundreds of legitimate leaves there is no safe substitution target — a
false-positive rewrite corrupts a legitimate $391B revenue into a price target
(the thesis-side ``_reconcile_narrative_targets`` may rewrite only because it
has a single canonical target to compare against). Removal-on-orphan carries no
such risk: it never puts a number in the analyst's hands.

Same "same number" rule as the thesis reconcile and output-contract C3:
``NARRATIVE_DRIFT_TOLERANCE`` from the shared leaf constant.
"""

from __future__ import annotations

import math
import re
from typing import Any, Iterable

from pydantic import BaseModel, Field

from finrobot.engine.models.reconcile_tolerances import (
    NARRATIVE_APPROXIMATION_BAND,
    NARRATIVE_DRIFT_TOLERANCE,
)

# $-amounts and ISO-code amounts ("USD 391B") with optional comma grouping and
# an optional magnitude suffix. The number-discipline contract makes agents
# write "USD 150B" rather than a bare "$150B", so both spellings must count.
# Suffix is captured so the parsed value scales to absolute before matching.
#
# Negative shapes are first-class (negative leaves are legitimate: negative FCF,
# loss-quarter net income, net-cash net debt):
#   -$5.00B / −$5.00B   leading minus, ASCII or U+2212 (LLMs emit both)
#   $-5.00B             minus after the symbol — the shape live narratives
#                       actually printed ("implies $-1512.42 per share", BUG-074)
#   ($5.00B)            accounting-parentheses negative
# Without these the sign was silently dropped: "-$5.00B" parsed as +5.00B,
# matched nothing (the leaf is -5.00B) and a LEGITIMATE citation flagged as
# drift on every loss-making report.
_CURRENCY_CODES = "USD|EUR|JPY|GBP|CNY|HKD|TWD|KRW|INR|CHF|CAD|AUD|SEK|NOK|DKK|BRL|MXN|ILS|SGD|ZAR"
_AMOUNT_RE = re.compile(
    rf"(?P<paren>\()?"
    rf"(?P<neg_pre>[-−]\s?)?"  # whitespace tied INTO the minus group, else an
    # absent minus lets a bare \s? swallow the preceding space into group(0)
    rf"(?:\$\s?|(?:{_CURRENCY_CODES})\s)"
    r"(?P<neg_post>[-−])?"
    r"(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    # Magnitude as a single letter (K/M/B/T) OR a spelled-out word — the
    # deterministic ``format_summary`` narrative prints WORDS ("$451.442 Billion
    # USD", "$4.041 Trillion"), and LLM prose mixes "$391b" / "USD 391 billion" /
    # "$96,995 mn". Without the word forms, "$451.442 Billion" parsed as a bare
    # 451.442 and matched nothing vs the absolute 451.442e9 leaf → every
    # spelled-out figure false-flagged (the 49/50-artifact flood, DDM/DCF ~80%).
    # Words listed before single letters so the longest alternative wins; the
    # group is case-insensitive in isolation (no IGNORECASE on the currency codes).
    r"\s?(?P<suffix>(?i:trillion|billion|million|thousand|bn|mn|tn|[kmbt]))?\b"
    r"(?P<close>\))?"
)

# Keyed lowercase (the suffix group is case-insensitive). "thousand" must NOT
# fall through to a first-letter heuristic — "t" alone is trillion, so each form
# is mapped explicitly.
_SUFFIX_SCALE = {
    "k": 1e3,
    "thousand": 1e3,
    "m": 1e6,
    "mn": 1e6,
    "million": 1e6,
    "b": 1e9,
    "bn": 1e9,
    "billion": 1e9,
    "t": 1e12,
    "tn": 1e12,
    "trillion": 1e12,
}

# Leaves below this magnitude are index-like (years-in-model, counts, ratios
# stored as 0.135) and would spuriously match small per-share amounts only by
# coincidence — they still participate; no filtering. Kept as a named constant
# only for the absolute-epsilon floor of the comparison.
_ABS_EPSILON = 0.005  # cents-level slack for sub-dollar leaves


class ReportDriftFinding(BaseModel):
    """One monetary token in the report that matched no computed value."""

    token: str = Field(description="Literal matched text, e.g. '$280.00' / 'USD 400B'.")
    value: float = Field(
        description="Parsed value, unit-suffix scaled; negative when an explicit "
        "minus was written (accounting parens keep the positive face value — the "
        "token shows the parens)."
    )
    nearest_gap: float | None = Field(
        default=None,
        description="Relative distance to the NEAREST numeric leaf (None when the "
        "leaf registry was empty). ≤ the approximation band ⇒ approximation; "
        "beyond ⇒ orphan.",
    )


class ReportDrift(BaseModel):
    """Detector verdict for one report text. Classifies — never rewrites a value."""

    total_dollar_amounts: int
    unmatched: list[ReportDriftFinding] = Field(
        default_factory=list,
        description="First N unmatched amounts (see unmatched_count for the truth).",
    )
    unmatched_count: int = 0
    approximate_count: int = Field(
        default=0,
        description="Unmatched amounts within the approximation band of some leaf "
        "— legitimate LLM roundings, kept in prose.",
    )
    orphan_count: int = 0
    orphan_tokens: list[str] = Field(
        default_factory=list,
        description="EVERY distinct orphan token (not capped like ``unmatched``) — "
        "the complete redaction set for builders. A capped list here once let "
        "unmatched tokens past the 10-finding window ship unredacted.",
    )


def collect_numeric_leaves(payload: Any) -> set[float]:
    """Recursively collect every finite numeric leaf of a JSON-shaped payload.

    bools are excluded (``True == 1`` would whitelist '$1'); NaN/Inf are dropped
    (nothing legitimately printable matches them).
    """
    leaves: set[float] = set()
    stack: list[Any] = [payload]
    while stack:
        node = stack.pop()
        if isinstance(node, bool):
            continue
        if isinstance(node, (int, float)):
            value = float(node)
            if math.isfinite(value):
                leaves.add(value)
        elif isinstance(node, dict):
            stack.extend(node.values())
        elif isinstance(node, (list, tuple)):
            stack.extend(node)
    return leaves


def detect_report_drift(
    report_text: str,
    canonical_leaves: Iterable[float],
    *,
    tolerance: float = NARRATIVE_DRIFT_TOLERANCE,
    approximation_band: float = NARRATIVE_APPROXIMATION_BAND,
    max_findings: int = 10,
) -> ReportDrift:
    """Scan a report's monetary amounts against the computed-value registry.

    An amount matches when it is within ``tolerance`` (relative, vs the leaf) of
    ANY leaf — display roundings ("$276" vs 276.43) pass. Unmatched amounts are
    classified by distance to the NEAREST leaf: within ``approximation_band`` ⇒
    approximation (kept), beyond ⇒ orphan (the builder's redaction set). With an
    empty registry every amount is an orphan: a builder that failed to hand over
    the snapshot must read as loud drift, not silent green.
    """
    leaves = [leaf for leaf in canonical_leaves if math.isfinite(leaf)]

    def _nearest_gap(candidates: tuple[float, ...]) -> float | None:
        """Smallest relative distance from any sign-candidate to any leaf."""
        if not leaves:
            return None
        return min(
            abs(value - leaf) / max(abs(leaf), _ABS_EPSILON)
            for value in candidates
            for leaf in leaves
        )

    total = 0
    findings: list[ReportDriftFinding] = []
    unmatched_count = 0
    approximate_count = 0
    orphan_occurrences = 0
    orphan_tokens: dict[str, None] = {}  # ordered dedup (redaction set)
    for match in _AMOUNT_RE.finditer(report_text):
        try:
            value = float(match.group("num").replace(",", ""))
        except ValueError:
            continue
        suffix = match.group("suffix")
        if suffix:
            value *= _SUFFIX_SCALE[suffix.lower()]
        # An explicit minus is unambiguous → the signed value only. Accounting
        # parentheses are ambiguous in prose (a parenthetical aside also wraps
        # amounts: "(see $5.00B above)" never closes adjacent, but "revenue
        # ($5.00B)" does), so a paren-wrapped amount matches a leaf of EITHER
        # sign — the sign false-accept costs nothing, a false flag on every
        # parenthetical aside costs a triage glance each.
        if match.group("neg_pre") or match.group("neg_post"):
            candidates: tuple[float, ...] = (-value,)
        elif match.group("paren") and match.group("close"):
            candidates = (value, -value)
        else:
            candidates = (value,)
        total += 1
        gap = _nearest_gap(candidates)
        if gap is not None and gap <= tolerance:
            continue
        unmatched_count += 1
        if gap is not None and gap <= approximation_band:
            approximate_count += 1
        else:
            orphan_occurrences += 1
            orphan_tokens[match.group(0).rstrip()] = None
        if len(findings) < max_findings:
            findings.append(
                ReportDriftFinding(
                    token=match.group(0).rstrip(),
                    value=candidates[0],
                    nearest_gap=gap,
                )
            )

    return ReportDrift(
        total_dollar_amounts=total,
        unmatched=findings,
        unmatched_count=unmatched_count,
        approximate_count=approximate_count,
        orphan_count=orphan_occurrences,
        orphan_tokens=list(orphan_tokens),
    )
