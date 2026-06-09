"""Earnings surprise analysis compute module.

Beat/miss/inline classification threshold: ±2% EPS surprise.
Reference: Livnat & Mendenhall (2006) — ≥2% surprise is statistically significant.

All calculations are deterministic; no LLM involvement.
"""

import math

from finrobot.engine.models.financial import EarningsResult, EarningsSurprise

_BEAT_THRESHOLD = 2.0  # pct
_MISS_THRESHOLD = -2.0  # pct


def calculate_earnings_surprises(
    ticker: str, earnings_history: list[dict[str, float | str]]
) -> EarningsResult:
    """Compute beat/miss/inline classification for each quarter.

    Args:
        ticker: Company ticker symbol.
        earnings_history: List of dicts (most recent first) with keys:
            date, eps_actual, eps_estimated, revenue_actual, revenue_estimated.

    Returns:
        EarningsResult with per-quarter surprises and aggregate statistics.
    """
    if not earnings_history:
        return EarningsResult(
            ticker=ticker,
            surprises=[],
            beat_rate=0.0,
            avg_eps_surprise_pct=0.0,
            avg_revenue_surprise_pct=0.0,
            consecutive_beats=0,
        )

    surprises: list[EarningsSurprise] = []
    for row in earnings_history:
        # None ≠ 0: a missing actual/estimate must stay None, never default to 0.
        # dict.get(key, 0) does NOT help here — the provider always sets the key
        # (to None when FMP omits the value), so the default never fires and
        # float(None) would raise TypeError. A fabricated $0 actual against a real
        # estimate would also print a false -100% surprise (砸招牌).
        eps_actual = _opt_float(row.get("eps_actual"))
        eps_est = _opt_float(row.get("eps_estimated"))
        rev_actual = _opt_float(row.get("revenue_actual"))
        rev_est = _opt_float(row.get("revenue_estimated"))

        eps_pct = _surprise_pct(eps_actual, eps_est)
        rev_pct = _surprise_pct(rev_actual, rev_est)

        surprises.append(
            EarningsSurprise(
                date=str(row.get("date", "")),
                eps_actual=eps_actual,
                eps_estimated=eps_est,
                eps_surprise_pct=eps_pct,
                eps_direction=_classify_surprise(eps_pct),
                revenue_actual=rev_actual,
                revenue_estimated=rev_est,
                revenue_surprise_pct=rev_pct,
                revenue_direction=_classify_surprise(rev_pct),
            )
        )

    # Quarters whose surprise is undefined (estimate == 0, see _surprise_pct)
    # carry None / direction "n/a". They must be excluded from rates and
    # averages rather than counted as 0% inline — otherwise a real beat/miss
    # against a zero consensus is silently washed out (BUG-026). For normal data
    # (no zero estimates) the denominators are unchanged.
    eps_defined = [s.eps_surprise_pct for s in surprises if s.eps_surprise_pct is not None]
    rev_defined = [s.revenue_surprise_pct for s in surprises if s.revenue_surprise_pct is not None]
    beats = sum(1 for s in surprises if s.eps_direction == "beat")
    beat_rate = beats / len(eps_defined) if eps_defined else 0.0
    avg_eps = sum(eps_defined) / len(eps_defined) if eps_defined else 0.0
    avg_rev = sum(rev_defined) / len(rev_defined) if rev_defined else 0.0
    consecutive = _count_consecutive_beats(surprises)

    return EarningsResult(
        ticker=ticker,
        surprises=surprises,
        beat_rate=beat_rate,
        avg_eps_surprise_pct=avg_eps,
        avg_revenue_surprise_pct=avg_rev,
        consecutive_beats=consecutive,
    )


def _opt_float(value: object) -> float | None:
    """Coerce a provider value to float, preserving None (None ≠ 0).

    A missing actual/estimate arrives as None (provider sets the key explicitly);
    it must stay None so the surprise is reported as "n/a" rather than fabricated
    as a $0 value or crashing float(None).
    """
    return float(value) if value is not None else None  # type: ignore[arg-type]


def _surprise_pct(actual: float | None, estimated: float | None) -> float | None:
    """Compute surprise as (actual - estimated) / |estimated| × 100.

    Returns None when either side is missing (None) or when ``estimated`` is zero:
    the surprise is then mathematically undefined (division by zero / unknown
    input), and a beat/miss against a zero consensus (e.g. expected breakeven,
    actual +$0.10) is a genuine earnings event — not a 0% "inline". Returning 0.0
    here masked it and polluted beat_rate / averages (BUG-026). Callers treat None
    as "n/a" and exclude it from aggregates.
    """
    if actual is None or estimated is None or estimated == 0:
        return None
    # A non-finite actual/estimated (corrupt provider row) would yield an Inf/NaN
    # surprise that pollutes beat_rate and the avg_* aggregates — withhold it.
    if not math.isfinite(actual) or not math.isfinite(estimated):
        return None
    return (actual - estimated) / abs(estimated) * 100.0


def _classify_surprise(pct: float | None) -> str:
    """Classify a surprise percentage into beat/miss/inline.

    Thresholds: ≥ +2% → beat, ≤ -2% → miss, else → inline. An undefined
    surprise (``pct is None``, zero estimate) is "n/a" — neither beat, miss,
    nor inline — so it is not miscounted as inline.
    """
    if pct is None:
        return "n/a"
    if pct >= _BEAT_THRESHOLD:
        return "beat"
    if pct <= _MISS_THRESHOLD:
        return "miss"
    return "inline"


def _count_consecutive_beats(surprises: list[EarningsSurprise]) -> int:
    """Count current consecutive beat streak from most recent quarter.

    Assumes surprises are ordered most-recent-first.
    """
    streak = 0
    for s in surprises:
        if s.eps_direction == "beat":
            streak += 1
        else:
            break
    return streak
