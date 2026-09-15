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

from finrobot.engine.data.normalize.session import SessionState
from finrobot.engine.models.financial import MarketImpliedNature


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


class NumberSource(BaseModel):
    """Provenance for one numeric cell — mirrors the UI's ``NumberSource``.

    Lets the Coverage Table render every amount/multiple/percent through
    ``SourcedNumber``: who served it (:attr:`provider`), as of which reporting
    period/bar (:attr:`as_of`), when we pulled it (:attr:`fetched_at`), by what
    formula (:attr:`formula_id`), with what口径 caveat (:attr:`formula_warning`),
    and which report it traces to (:attr:`artifact_id`). All optional — an
    absent field simply doesn't render in the popover.

    ``as_of`` ≠ ``fetched_at`` on purpose: ``as_of`` is the data's semantic time
    (fiscal period end / latest bar date), ``fetched_at`` is wall-clock fetch.
    Conflating them is exactly the kind of口径 error that looks right and isn't.
    """

    provider: str | None = None
    as_of: datetime | None = None
    fetched_at: datetime | None = None
    formula_id: str | None = None
    formula_warning: str | None = None
    artifact_id: str | None = None


class CoverageRowSources(BaseModel):
    """Per-cell provenance for a :class:`CoverageRow`'s numeric columns.

    Parallel to the flat numeric fields (kept typed rather than a
    ``dict[str, NumberSource]`` so a column and its source can't drift apart).
    A cell with no provenance (e.g. degraded fetch) just leaves its slot
    ``None`` and ``SourcedNumber`` renders the bare value.
    """

    price: NumberSource | None = None
    change_pct_1d: NumberSource | None = None
    market_cap: NumberSource | None = None
    revenue_ttm: NumberSource | None = None
    ev_ebitda: NumberSource | None = None
    pe: NumberSource | None = None
    upside_to_target_live: NumberSource | None = None
    market_implied: NumberSource | None = None


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
    session_state: SessionState | None = None
    """The price's session phase — one of ``live`` / ``pre_market`` /
    ``post_market`` / ``closed`` / ``halted`` / ``unknown`` (see
    ``engine.data.normalize.session.SessionState``). Recomputed server-side at
    read time: primary signal is the provider's per-exchange ``marketState``,
    with the exchange clock as fallback (NOT cached — session phase is
    time-varying). Drives the card's freshness affordance: a closed-market close
    renders statically (never a "refreshing"/live pulse over a number that won't
    move), while a live/pre/post quote can show its phase honestly."""
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
    target_date: datetime | None = None
    entry_price: float | None = None
    upside_to_target_live: float | None = None
    signal: str | None = None
    artifact_count: int = 0
    """Total artifacts of ANY type for this ticker (dcf / lbo / comps / earnings /
    equity_research …) — reflects total research activity."""
    research_count: int = 0
    """Thesis-bearing research artifacts only (``verdict is not None`` —
    equity_research / ic_memo). The "N 份研报" the UI counts; distinct from
    :attr:`artifact_count`, which includes standalone models that carry no
    verdict."""
    latest_artifact_id: str | None = None
    latest_type: str | None = None
    latest_at: datetime | None = None

    # Reverse-DCF valuation nature — what the LIVE price implies, re-solved from
    # the name's latest stored DCF inputs. A per-name classification
    # (fundamental / option_value / near_ceiling), NOT a cross-name implied-growth
    # ranking (see MarketImpliedNature for why that was rejected). None when the
    # ticker has no DCF artifact, no live price, or on the instant cache-only
    # first paint (it needs the artifact body; the network revalidate fills it).
    market_implied: MarketImpliedNature | None = None

    # Live run state for this ticker (latest run in the run store), distinct
    # from the research artifacts above: a batch run may be in flight or have
    # failed without producing an artifact.
    run_status: str | None = None
    """created | running | completed | failed — latest run, or None if never run."""
    run_error: str | None = None

    market_stale: bool = False
    """The market cells (price/mcap/rev/pe/upside) were served from a cache
    snapshot past its freshness TTL — a background revalidate is advisable. The
    values are real last-known numbers (rendered with their ``price_as_of`` age),
    NOT pending/missing: the client shows them with a "refreshing" affordance
    rather than a blank shimmer. ``False`` means either fresh-from-cache or a
    cold row whose market is genuinely absent (None → shimmer)."""

    market_refresh_noop: bool = Field(default=False, exclude=True)
    """Internal (not serialized): on a network refresh, the price was served from
    cache WITHOUT a provider call because the market is closed and the snapshot is
    already the latest settled close (``has_newer_session_since`` proved no newer
    session exists). Aggregated into :attr:`CoverageOverview.refresh_noop` so the
    client can say "已是最新收盘" instead of implying it fetched live."""

    needs_refresh: list[NeedsRefreshReason] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    # Per-cell provenance for the numeric columns above (price/mcap/EV-EBITDA/…).
    # Additive: the flat numbers stay the source of truth for sorting/signal/
    # compare; this rides alongside so the table can render each through
    # SourcedNumber without changing any existing consumer's contract.
    sources: CoverageRowSources = Field(default_factory=CoverageRowSources)


class CoverageOverview(BaseModel):
    """Assembled Coverage Table for one group."""

    group_id: str
    group_name: str
    rows: list[CoverageRow]
    generated_at: datetime
    partial: bool = False
    """True when at least one ticker's market/fundamental fetch degraded — the
    table still renders, the affected rows carry warnings."""
    cache_only: bool = False
    """True when this overview was assembled from the canonical cache WITHOUT any
    network fetch (the instant first-paint, ~ms at any N). Market cells are
    last-known snapshots; per-row :attr:`CoverageRow.market_stale` flags the ones
    past their TTL. The client revalidates in the background via a
    ``refresh=true`` (network) pass. ``False`` = a fresh network-backed table."""
    refresh_noop: bool = False
    """True when a network refresh (``cache_only=False``) made ZERO provider calls
    for prices because every row's market is closed and already at its latest
    settled close (the calendar no-op — see ``has_newer_session_since``). The
    client shows "已是最新收盘" rather than implying it pulled live quotes. Always
    ``False`` on the instant cache-only paint and whenever any row was fetched
    (cold, live, or a newer session had settled)."""
