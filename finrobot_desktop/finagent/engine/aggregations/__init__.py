"""Cross-artifact aggregations powering the dashboard landing.

Leaf-layer rules:
- Pure functions; no I/O.
- No imports from `finagent.engine.pipelines / agents / orchestrator`.
- No imports from `finagent.routes.*`.
- Allowed: `finagent.engine.compute.signal` (also leaf), `finagent.artifact.models`
  read-only.

Callers (FastAPI route handlers) own data fetching & timezone hygiene.
"""

from finagent.engine.aggregations.hit_rate_overview import (
    HitRateBucketStats,
    HitRateOverviewStats,
    compute_hit_rate_overview,
)
from finagent.engine.aggregations.recent_research import (
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
