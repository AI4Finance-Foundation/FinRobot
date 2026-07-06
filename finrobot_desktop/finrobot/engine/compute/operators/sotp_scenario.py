"""Forward SOTP scenario band — STREET-anchored bull/base/bear (pure operator).

Batch 3B v2. The forward companion to the reverse-SOTP decomposition
(``sotp.compute_sotp_breakdown``). For an option-value name a single point target
would require fabricating a robotaxi-success probability, so this presents a
SCENARIO BAND instead — and anchors it to the one distribution that is fully
sourceable and reproducible: the 12-month analyst price-target distribution
(street low / consensus / high, from FMP ``/price-target-consensus``).

🔴 SEMANTIC GUARDRAIL (load-bearing — team-lead 2026-07-06):
Street price targets are a 12-MONTH TARGET distribution, NOT a "robotaxi-success
scenario valuation". ``range_position`` = where the live price sits within that
street range = an implied optimism VS THE SELL-SIDE RANGE. It MUST NEVER be
surfaced as a "robotaxi / optionality success probability" — that ceiling is
un-sourceable, which is exactly why the reverse-SOTP ``option_ev_if_success`` is
kept None (see equity_research / valuation-synthesis-recall 2026-07-06). The band
legs are FORWARD (12-month) values; the reverse-SOTP cash-flow floor is a PRESENT
value — a consumer must label the two axes distinctly.

ZERO I/O: the price-target fetch lives in the coordinator (``segment_extractor``);
this module is arithmetic only.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

from finrobot.engine.models.financial import SOTPScenarioBand

# Below this recent-year analyst count the target range likely understates true
# uncertainty → confidence downgraded to "very_low" + disclosed (never fabricate a
# wider band; disclose that the sourced band is thin).
_THIN_COVERAGE_N = 5


def _finite_positive(x: float | None) -> bool:
    return x is not None and math.isfinite(x) and x > 0


def compute_scenario_band(
    *,
    bear: float | None,
    base: float | None,
    bull: float | None,
    median: float | None,
    current_price: float,
    analyst_count: int | None,
    source: str,
    cash_flow_floor: float | None = None,
    as_of: datetime | None = None,
    warnings: list[str] | None = None,
) -> SOTPScenarioBand | None:
    """Assemble the street-anchored forward scenario band, or None.

    Returns None (the caller drops the band; the reverse-SOTP floor still ships)
    when a REQUIRED bound is missing or degenerate — a band needs a real, ordered
    street range and we never fabricate a bound:

      · ``bear`` / ``bull`` non-finite / non-positive / ``bull <= bear``, or
      · no central leg (``base`` consensus AND ``median`` both absent), or
      · ``current_price`` non-finite / non-positive.

    The central leg is the consensus when present, else the median (both are
    sourced central tendencies). Thin analyst coverage (< ``_THIN_COVERAGE_N`` or
    unknown) downgrades confidence to "very_low" and discloses — the sourced band
    is NOT numerically widened (that would fabricate bounds).
    """
    warn = list(warnings or [])
    if not _finite_positive(current_price):
        return None
    if not (_finite_positive(bear) and _finite_positive(bull)):
        return None
    assert bear is not None and bull is not None  # narrowed by _finite_positive
    if bull <= bear:
        # Inverted / degenerate range — cannot position a price within it.
        return None
    central = base if _finite_positive(base) else (median if _finite_positive(median) else None)
    if central is None:
        return None

    range_position = (current_price - bear) / (bull - bear)  # NOT clamped (legal <0/>1)

    confidence = "low"
    if analyst_count is None or analyst_count < _THIN_COVERAGE_N:
        confidence = "very_low"
        warn.append(
            "thin analyst coverage"
            + (f" (n={analyst_count})" if analyst_count is not None else " (count unknown)")
            + " — the sourced target range may understate true uncertainty; "
            "confidence downgraded (band NOT numerically widened — no fabricated bounds)"
        )
    if range_position < 0:
        warn.append(
            "live price is below the most bearish 12-month street target "
            "(market more bearish than the analyst low)"
        )
    elif range_position > 1:
        warn.append(
            "live price is above the most bullish 12-month street target "
            "(market more bullish than the analyst high)"
        )

    # floor_coverage = floor / price — the ONLY floor-vs-price relation allowed
    # (both PRESENT values, same caliber; C hard rule). A floor→street ratio would
    # mix present with 12-month forward and is forbidden — never computed here.
    floor = cash_flow_floor if _finite_positive(cash_flow_floor) else None
    floor_coverage = (floor / current_price) if floor is not None else None

    return SOTPScenarioBand(
        cash_flow_floor=floor,
        floor_coverage=floor_coverage,
        bear=bear,
        base=float(central),
        bull=bull,
        median=median if _finite_positive(median) else None,
        current_price=current_price,
        range_position=range_position,
        analyst_count=analyst_count,
        confidence=confidence,
        source=source,
        as_of=as_of or datetime.now(tz=timezone.utc),
        warnings=warn,
    )
