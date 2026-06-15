"""Historical EV/EBITDA + P/FCF band computation (v5 §6.6).

Pure leaf-layer: route adapter feeds in already-fetched financials + price
history, this module emits a deterministic band + timeline. No providers,
no LLM, no upper-layer imports.

Algorithm (single function, no per-metric duplication):
  1. The yearly financials list is sorted by ascending fiscal-year date.
  2. For each price point we attach the most recent fiscal year on or before
     that price's date — that's the "current at the time" denominator.
  3. We compute the multiple per sample, drop non-finite / non-positive
     samples, and reduce to (current, P25, median, P75, P90) plus a sampled
     timeline (≤120 points so the UI line stays readable).

Why deterministic + audit-pinned: spec §6.6 lets the front end say "现在贵 /
合理 / 便宜" verbatim by comparing `current` to `p75` / `p90`. That
classification has to be reproducible — same inputs, same answer, no LLM.
"""

from __future__ import annotations

import bisect
import math
import statistics
from dataclasses import dataclass
from datetime import date
from typing import Literal

HistoricalMetricName = Literal["ev_ebitda", "p_fcf"]
"""Two metrics supported in v5 (spec §6.6)."""

_MAX_TIMELINE_POINTS = 120
"""Front-end chart caps at ~3y * monthly = 36 points; 120 is a safe ceiling
that keeps the JSON payload small while preserving variation when callers
ask for higher-resolution windows."""


@dataclass(frozen=True)
class YearlyFinancials:
    """Single fiscal-year snapshot needed for one band metric.

    The route layer parses raw yfinance / FMP rows into this shape so the
    compute function stays agnostic to provider keys.
    """

    fiscal_date: date
    """The fiscal-year-end date — used to align with price history."""

    ebitda: float | None
    """Annual EBITDA in absolute dollars. None means EBITDA not reported."""

    free_cash_flow: float | None
    """Annual FCF (OperatingCF - CapEx). None means data unavailable."""

    net_debt: float | None
    """Total debt minus cash & equivalents; can be negative (net cash).
    None means a balance leg was missing for the year (None ≠ 0 — filling 0
    fabricated a debt-free EV for levered issuers); the EV/EBITDA sample for
    that year is skipped."""


@dataclass(frozen=True)
class PricePoint:
    """A single (date, close-price) row from the historical price stream."""

    sample_date: date
    close: float


@dataclass(frozen=True)
class HistoricalBand:
    """v5 §6.6 response payload for one ticker/metric."""

    metric: HistoricalMetricName
    current: float | None
    median: float | None
    p25: float | None
    p75: float | None
    p90: float | None
    timeline: list[tuple[date, float]]
    sample_count: int
    warnings: list[str]


def compute_historical_band(
    *,
    metric: HistoricalMetricName,
    yearly: list[YearlyFinancials],
    prices: list[PricePoint],
    shares_outstanding: float,
    current_override: float | None = None,
) -> HistoricalBand:
    """Build the band + timeline + quantiles for a single metric.

    Inputs are typed dataclasses so callers can't accidentally pass raw
    provider dicts; alignment between fiscal years and price dates is
    handled here (most recent fiscal year ≤ price date), and degenerate
    rows are dropped rather than raising — the UI shows what's available.

    ``current_override``: when given, replaces the band's *current* multiple
    with a caller-supplied value (B2). The historical samples here use the
    trailing **annual** EBITDA at each price date (the only series available
    without quarterly data), but the report's comps chapter reports the
    **current** EV/EBITDA on **TTM** EBITDA. Passing the canonical TTM
    multiple as ``current_override`` keeps the headline "current EV/EBITDA"
    identical across chapters instead of showing two口径. The historical
    quantiles/timeline stay annual-based, so we record a warning disclosing
    the mixed basis rather than silently masking it.
    """
    warnings: list[str] = []

    if shares_outstanding <= 0:
        return _empty(
            metric, ["shares_outstanding unavailable — historical bands cannot be computed"]
        )
    if not prices:
        return _empty(metric, ["price history is empty — historical bands cannot be computed"])
    if not yearly:
        return _empty(metric, ["financials history is empty — historical bands cannot be computed"])

    fiscal_dates, fiscals = _sort_yearly(yearly)

    samples: list[tuple[date, float]] = []
    skipped_no_financial = 0
    for point in prices:
        fy = _financial_for_date(point.sample_date, fiscal_dates, fiscals)
        if fy is None:
            skipped_no_financial += 1
            continue
        multiple = _compute_multiple(metric, point, fy, shares_outstanding)
        # math.isfinite: a single NaN close (halted session / bad provider row)
        # passes both `is None` and `<= 0` (NaN comparisons are False) and
        # poisons every quantile of the band — same family as the peer-median
        # NaN fix in operators/multiples.
        if multiple is None or not math.isfinite(multiple) or multiple <= 0:
            continue
        samples.append((point.sample_date, multiple))

    if not samples:
        return _empty(
            metric, ["no sample could compute a multiple — check whether EBITDA / FCF is disclosed"]
        )

    if skipped_no_financial:
        warnings.append(
            f"{skipped_no_financial} price point(s) predate the earliest fiscal year — skipped"
        )

    values = [v for _, v in samples]
    timeline = _downsample(samples, _MAX_TIMELINE_POINTS)
    if current_override is not None and current_override > 0:
        # B2: use the caller's canonical TTM multiple as the headline current
        # point (matches the comps chapter). Historical *quantiles* stay on the
        # trailing-annual basis (``values`` untouched) — disclose the mixed基差
        # rather than hide it. The timeline's last point is shifted to the same
        # TTM value so the rendered "current" dot sits on the line end instead of
        # floating off it; the historical shape is otherwise preserved.
        current = current_override
        if timeline:
            timeline = [*timeline[:-1], (timeline[-1][0], current_override)]
        warnings.append(
            "current point uses TTM EBITDA (consistent with the comps caliber); historical quantiles use each annual-report year's EBITDA, "
            "so the two carry a caliber basis difference (no quarterly data, so a rolling TTM cannot be reconstructed point by point)."
        )
    else:
        current = samples[-1][1]  # last sample is the most recent price multiple
        # W1-C2: no canonical TTM multiple was supplied, so the current point is
        # the most recent price × the trailing-ANNUAL EBITDA — a different口径
        # than the report's comps/technical chapters (which use TTM). Disclose it
        # so a consumer (the standalone /historical-bands route) can't silently
        # classify a ticker 贵/合理/便宜 on an annual basis while the report calls
        # the same ticker the opposite on TTM (the signal flip).
        warnings.append(
            "current point is based on the [annual-report year] EBITDA matching the most recent price (no canonical TTM multiple passed in) — "
            "this carries a basis difference vs the TTM caliber of the report's comps / technical chapters; the expensive/fair/cheap classification is on an annual-report basis, "
            "so do not compare it directly with the TTM caliber."
        )

    return HistoricalBand(
        metric=metric,
        current=current,
        median=statistics.median(values),
        p25=_quantile(values, 0.25),
        p75=_quantile(values, 0.75),
        p90=_quantile(values, 0.90),
        timeline=timeline,
        sample_count=len(values),
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _empty(metric: HistoricalMetricName, warnings: list[str]) -> HistoricalBand:
    return HistoricalBand(
        metric=metric,
        current=None,
        median=None,
        p25=None,
        p75=None,
        p90=None,
        timeline=[],
        sample_count=0,
        warnings=warnings,
    )


def _sort_yearly(
    yearly: list[YearlyFinancials],
) -> tuple[list[date], list[YearlyFinancials]]:
    items = sorted(yearly, key=lambda y: y.fiscal_date)
    return [y.fiscal_date for y in items], items


def _financial_for_date(
    sample_date: date,
    fiscal_dates: list[date],
    fiscals: list[YearlyFinancials],
) -> YearlyFinancials | None:
    """Return the most recent fiscal year on or before sample_date, or None."""
    idx = bisect.bisect_right(fiscal_dates, sample_date) - 1
    if idx < 0:
        return None
    return fiscals[idx]


def _compute_multiple(
    metric: HistoricalMetricName,
    price: PricePoint,
    fy: YearlyFinancials,
    shares: float,
) -> float | None:
    market_cap = price.close * shares
    if market_cap <= 0:
        return None
    if metric == "ev_ebitda":
        if fy.ebitda is None or fy.ebitda <= 0 or fy.net_debt is None:
            return None
        return (market_cap + fy.net_debt) / fy.ebitda
    # metric == "p_fcf" — the Literal alias has no other variants.
    if fy.free_cash_flow is None or fy.free_cash_flow <= 0:
        return None
    return market_cap / fy.free_cash_flow


def _quantile(values: list[float], q: float) -> float:
    """Inclusive linear-interpolation quantile (matches numpy default)."""
    if not values:
        raise ValueError("quantile on empty values")
    if len(values) == 1:
        return values[0]
    s = sorted(values)
    pos = q * (len(s) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(s) - 1)
    frac = pos - lo
    return s[lo] + frac * (s[hi] - s[lo])


def _downsample(
    samples: list[tuple[date, float]],
    max_points: int,
) -> list[tuple[date, float]]:
    """Uniform downsample to at most max_points keeping the first + last samples."""
    if len(samples) <= max_points:
        return samples
    # Leave 2 slots for the explicit first / last indices to stay under the cap.
    interior = max(0, max_points - 2)
    step = (len(samples) - 1) / (interior + 1)
    indices = {0, len(samples) - 1}
    for i in range(1, interior + 1):
        indices.add(int(i * step))
    ordered = sorted(indices)[:max_points]
    return [samples[i] for i in ordered]


# Re-export the runtime sentinel for type checkers — kept for parity with the
# rest of compute/* which expose Literal aliases at module scope.
__all__ = [
    "HistoricalBand",
    "HistoricalMetricName",
    "PricePoint",
    "YearlyFinancials",
    "compute_historical_band",
]
