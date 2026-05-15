"""Earnings surprise analysis compute module.

Beat/miss/inline classification threshold: ±2% EPS surprise.
Reference: Livnat & Mendenhall (2006) — ≥2% surprise is statistically significant.

All calculations are deterministic; no LLM involvement.
"""

from finagent.engine.models.financial import EarningsResult, EarningsSurprise

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
        eps_actual = float(row.get("eps_actual", 0))
        eps_est = float(row.get("eps_estimated", 0))
        rev_actual = float(row.get("revenue_actual", 0))
        rev_est = float(row.get("revenue_estimated", 0))

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

    n = len(surprises)
    beat_rate = sum(1 for s in surprises if s.eps_direction == "beat") / n
    avg_eps = sum(s.eps_surprise_pct for s in surprises) / n
    avg_rev = sum(s.revenue_surprise_pct for s in surprises) / n
    consecutive = _count_consecutive_beats(surprises)

    return EarningsResult(
        ticker=ticker,
        surprises=surprises,
        beat_rate=beat_rate,
        avg_eps_surprise_pct=avg_eps,
        avg_revenue_surprise_pct=avg_rev,
        consecutive_beats=consecutive,
    )


def _surprise_pct(actual: float, estimated: float) -> float:
    """Compute surprise as (actual - estimated) / |estimated| × 100.

    Returns 0.0 if estimated is zero to avoid division by zero.
    """
    if estimated == 0:
        return 0.0
    return (actual - estimated) / abs(estimated) * 100.0


def _classify_surprise(pct: float) -> str:
    """Classify a surprise percentage into beat/miss/inline.

    Thresholds: ≥ +2% → beat, ≤ -2% → miss, else → inline.
    """
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
