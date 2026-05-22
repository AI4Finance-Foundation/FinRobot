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
    RecentResearchView,
    assemble_recent_research,
    format_age_label,
)

__all__ = [
    "HitRateBucketStats",
    "HitRateOverviewStats",
    "RecentResearchView",
    "assemble_recent_research",
    "compute_hit_rate_overview",
    "format_age_label",
]
