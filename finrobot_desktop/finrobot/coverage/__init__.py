"""Coverage Desk — the user's research coverage universe (groups + members).

Persistence (:class:`CoverageStore`) is decoupled from orchestration
(:func:`build_overview` in :mod:`coverage.service`): the store knows only
groups/members; the service assembles the Coverage Table from existing sources
(DataLayer canonical, artifact store) above the store in the dependency graph.
See ADR-0012.
"""

from __future__ import annotations

from finrobot.coverage.models import (
    CoverageGroup,
    CoverageGroupDetail,
    CoverageGroupSummary,
    CoverageMember,
    CoverageOverview,
    CoverageRow,
    NeedsRefreshReason,
)
from finrobot.coverage.sqlite_store import CoverageStore

__all__ = [
    "CoverageGroup",
    "CoverageGroupDetail",
    "CoverageGroupSummary",
    "CoverageMember",
    "CoverageOverview",
    "CoverageRow",
    "CoverageStore",
    "NeedsRefreshReason",
]
