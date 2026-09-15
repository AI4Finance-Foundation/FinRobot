"""Cross-artifact aggregations powering the dashboard landing.

Leaf-layer rules:
- Pure functions; no I/O.
- No imports from `finrobot.engine.pipelines / agents / orchestrator`.
- No imports from `finrobot.routes.*`.
- Allowed: `finrobot.engine.compute.operators.signal` (also leaf), `finrobot.artifact.models`
  read-only.

Callers (FastAPI route handlers) own data fetching & timezone hygiene.
"""

from finrobot.engine.aggregations.hit_rate_overview import (
    HitRateBucketStats,
    HitRateOverviewStats,
    compute_hit_rate_overview,
)
from finrobot.engine.aggregations.recent_research import (
    MAX_RUNS_PER_TICKER,
    RecentTickerRun,
    RecentTickerView,
    assemble_recent_tickers,
    format_age_label,
)

__all__ = [
    "HitRateBucketStats",
    "HitRateOverviewStats",
    "MAX_RUNS_PER_TICKER",
    "RecentTickerRun",
    "RecentTickerView",
    "assemble_recent_tickers",
    "compute_hit_rate_overview",
    "format_age_label",
]
