"""Coverage Desk schemas — the user's research coverage universe.

Two layers of model live here:

* **Persistence** (:class:`CoverageGroup`, :class:`CoverageMember`) — what the
  SQLite store reads and writes. A coverage group is a named set of tickers the
  analyst actively tracks ("Mag7", "AI Infra", …); members carry per-ticker
  annotation.
* **Overview** (:class:`CoverageRow`, :class:`CoverageOverview`,
  :class:`NeedsRefreshReason`) — the assembled payload the Coverage Table
  renders. These are pure projections built by ``coverage.service`` from
  existing sources (DataLayer canonical, artifact store); the store never
  produces them.

Caliber note (Coverage plan H2): :attr:`CoverageRow.upside_to_target_live` is
``(target_price - current_price) / current_price`` with a **live** price
denominator. It is a different metric from the artifact's entry-based
``upside`` (denominator = the entry price recorded at report time); they are
deliberately named apart so the table number is never mistaken for the
report's figure.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


# ── Persistence ────────────────────────────────────────────────────────────


class CoverageMember(BaseModel):
    """One ticker inside a coverage group."""

    ticker: str
    added_at: datetime
    note: str | None = None
    priority: int = 0
    """User-defined ordering hint; higher sorts first. 0 = unset."""


class CoverageGroup(BaseModel):
    """A named set of tickers the analyst tracks as one research universe."""

    id: str
    name: str
    description: str | None = None
    is_system: bool = False
    """True only for the auto-seeded ``Studied Tickers`` onboarding group
    (Coverage plan State D). Once created it behaves like any other group —
    the user can rename it, drop tickers, or delete it; the flag just records
    that it was machine-seeded from the artifact store, not hand-built."""
    created_at: datetime
    updated_at: datetime


class CoverageGroupDetail(CoverageGroup):
    """A group with its members materialised — returned by single-group reads."""

    members: list[CoverageMember] = Field(default_factory=list)


class CoverageGroupSummary(CoverageGroup):
    """A group with just its member count — returned by the list endpoint."""

    member_count: int = 0


# ── Overview (Coverage Table payload) ────────────────────────────────────────


class NeedsRefreshReason(BaseModel):
    """One actionable reason a covered ticker's research is out of date.

    Every reason points back at a concrete source so the UI can deep-link
    (Coverage plan: "每条 reason 必须能点到对应来源").
    """

    kind: str
    """``never_run`` | ``price_drift`` | ``degraded`` (Phase 1). ``stale_catalyst``
    and ``run_failed`` arrive with catalyst data / batch runs (Phase 2)."""
    detail: str
    artifact_id: str | None = None


class CoverageRow(BaseModel):
    """One ticker row in the Coverage Table.

    Financial fields are reused verbatim from ``FinancialData`` (the same
    assembly behind ``/api/data/{ticker}/financials``) — the overview does not
    re-derive any caliber. ``None`` everywhere means "not available", never a
    fabricated zero; per-ticker fetch failures surface in :attr:`warnings`
    rather than dropping the row.
    """

    ticker: str
    company: str | None = None

    # Market — from canonical PRICE / FinancialData.market
    price: float | None = None
    change_pct_1d: float | None = None
    price_as_of: datetime | None = None
    market_cap: float | None = None

    # Fundamentals / valuation — from FinancialData (TTM caliber)
    revenue_ttm: float | None = None
    ev_ebitda: float | None = None
    pe: float | None = None
    currency: str | None = None
    """Quote currency of the price/valuation figures (not assumed USD)."""

    # Research — from artifact store
    latest_verdict: str | None = None
    target_price: float | None = None
    entry_price: float | None = None
    upside_to_target_live: float | None = None
    signal: str | None = None
    run_count: int = 0
    latest_artifact_id: str | None = None
    latest_type: str | None = None
    latest_at: datetime | None = None

    needs_refresh: list[NeedsRefreshReason] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class CoverageOverview(BaseModel):
    """Assembled Coverage Table for one group."""

    group_id: str
    group_name: str
    rows: list[CoverageRow]
    generated_at: datetime
    partial: bool = False
    """True when at least one ticker's market/fundamental fetch degraded — the
    table still renders, the affected rows carry warnings."""
