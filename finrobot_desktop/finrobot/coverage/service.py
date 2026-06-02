"""Coverage Desk orchestration — assembles the Coverage Table.

This is the **consumer / orchestration** layer (ADR-0012): it sits above
``CoverageStore`` and reaches down into existing sources — the DataLayer
canonical PRICE/FINANCIALS, the same ``extract_financial_data`` assembly behind
``/api/data/{ticker}/financials``, the artifact store, and ``compute_signal``.
It re-derives no financial caliber of its own; every number traces to a source
that already owns its口径.

Two responsibilities:

* :func:`build_overview` — fan out across a group's tickers (concurrently) and
  assemble one :class:`CoverageRow` each. Per-ticker fetch failures degrade
  that row (warnings + null fields) rather than 500-ing the group.
* :func:`ensure_system_group` — the State-D onboarding seed: an old user with
  artifacts but no coverage groups gets a one-time ``Studied Tickers`` group
  projected from the artifact store (then freely editable).
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from datetime import datetime, timezone

from finrobot.artifact.models import ArtifactSummary
from finrobot.artifact.store import ArtifactStore
from finrobot.coverage.models import (
    CoverageGroup,
    CoverageGroupDetail,
    CoverageOverview,
    CoverageRow,
    NeedsRefreshReason,
)
from finrobot.coverage.sqlite_store import CoverageStore
from finrobot.engine.compute.extractor import extract_financial_data
from finrobot.engine.compute.signal import Signal, compute_signal
from finrobot.engine.data.interface import ProviderError
from finrobot.engine.data.layer import DataLayer
from finrobot.engine.data.types import DataType

logger = logging.getLogger(__name__)

# A single ticker's market/fundamental fetch must never blank the whole group.
# Same concrete failure modes the landing endpoints degrade on (dashboard.py
# _QUOTE_BATCH_DEGRADABLE) plus the canonical-fetch ValueError/ProviderError.
_MARKET_DEGRADABLE = (
    ProviderError,
    sqlite3.Error,
    RuntimeError,
    OSError,
    ValueError,
    TypeError,
    KeyError,
    ImportError,
    AttributeError,
)

_SYSTEM_GROUP_NAME = "Studied Tickers"


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


# ── Overview ─────────────────────────────────────────────────────────────────


async def build_overview(
    group: CoverageGroupDetail,
    *,
    artifact_store: ArtifactStore,
    data_layer: DataLayer,
    now: datetime | None = None,
) -> CoverageOverview:
    """Assemble the Coverage Table for one group.

    Rows are built concurrently — each ticker's chain (artifacts + canonical
    PRICE/FINANCIALS + signal) is independent, so wall-clock is one ticker's
    latency, not N×. Cache stampede guard + per-provider rate lock in the
    DataLayer bound the actual outbound calls.
    """
    now = now or _now()
    tickers = [m.ticker for m in group.members]
    if not tickers:
        return CoverageOverview(
            group_id=group.id,
            group_name=group.name,
            rows=[],
            generated_at=now,
            partial=False,
        )

    rows = await asyncio.gather(
        *(
            _assemble_row(t, artifact_store=artifact_store, data_layer=data_layer, now=now)
            for t in tickers
        )
    )
    partial = any(r.warnings for r in rows)
    return CoverageOverview(
        group_id=group.id,
        group_name=group.name,
        rows=list(rows),
        generated_at=now,
        partial=partial,
    )


async def _assemble_row(
    ticker: str,
    *,
    artifact_store: ArtifactStore,
    data_layer: DataLayer,
    now: datetime,
) -> CoverageRow:
    ticker = ticker.upper()
    row = CoverageRow(ticker=ticker)

    # 1. Research side — local SQLite, cheap. Newest-first (store sorts DESC).
    try:
        summaries = await artifact_store.list_by_ticker(
            ticker=ticker, include_archived=False, limit=200
        )
    except (sqlite3.Error, RuntimeError, OSError) as exc:
        summaries = []
        row.warnings.append(f"{ticker} 研报读取失败：{exc}")
    _apply_research_fields(row, summaries)

    # 2. Market side — network, degradable independently of the research side.
    await _apply_market_fields(row, ticker, data_layer)

    # 3. Derived — signal + live upside + refresh reasons.
    row.signal = _safe_signal(row, now)
    row.upside_to_target_live = _upside(row.target_price, row.price)
    row.needs_refresh = _needs_refresh(row)
    return row


def _apply_research_fields(row: CoverageRow, summaries: list[ArtifactSummary]) -> None:
    """Verdict / target / entry / run_count / latest_* from the artifact store.

    ``signal`` and ``run_count`` are derived here (not stored columns): run_count
    is the summary count, signal is computed downstream against the live price.
    """
    row.run_count = len(summaries)
    if not summaries:
        return
    latest = summaries[0]  # store returns created_at DESC
    row.latest_verdict = latest.verdict
    row.target_price = latest.target_price
    row.target_date = latest.target_date
    row.entry_price = latest.entry_price
    row.latest_artifact_id = latest.id
    row.latest_type = latest.type
    row.latest_at = latest.created_at


async def _apply_market_fields(row: CoverageRow, ticker: str, data_layer: DataLayer) -> None:
    """Price / 1D / market cap / TTM revenue / EV-EBITDA / P/E.

    Reuses ``extract_financial_data`` — the same assembly behind
    ``/api/data/{ticker}/financials`` — so no caliber is re-derived. Price-only
    fields survive a financials-extraction failure (and vice-versa); both
    degradations surface as row warnings, never an exception.
    """
    price_norm = None
    fin_norm = None
    try:
        price_norm = await data_layer.fetch_canonical(DataType.PRICE, ticker)
    except _MARKET_DEGRADABLE as exc:
        row.warnings.append(f"{ticker} 行情获取失败：{exc}")
    try:
        fin_norm = await data_layer.fetch_canonical(DataType.FINANCIALS, ticker)
    except _MARKET_DEGRADABLE as exc:
        row.warnings.append(f"{ticker} 财务获取失败：{exc}")

    if price_norm is not None:
        row.price = price_norm.current_price
        _, row.change_pct_1d = price_norm.latest_session_change()
        row.price_as_of = price_norm.provenance.as_of
        row.currency = price_norm.quote_currency
        _extend_unique(row.warnings, price_norm.warnings)

    if price_norm is not None and fin_norm is not None:
        try:
            fd = extract_financial_data(fin_norm, price_norm)
        except _MARKET_DEGRADABLE as exc:
            row.warnings.append(f"{ticker} 财务字段提取失败：{exc}")
        else:
            row.market_cap = fd.market.market_cap
            row.revenue_ttm = fd.income.revenue
            row.ev_ebitda = fd.valuation.ev_ebitda
            row.pe = fd.market.pe_ratio
            row.currency = fd.quote_currency or row.currency
            _extend_unique(row.warnings, fd.warnings)


def _safe_signal(row: CoverageRow, now: datetime) -> str | None:
    """compute_signal against the live price, mirroring the route adapter's guards.

    Returns None when the row lacks entry/target/price or compute_signal
    rejects a degenerate artifact (entry==target) — never raises.
    """
    if (
        row.entry_price is None
        or row.target_price is None
        or row.price is None
        or row.price <= 0
        or row.latest_at is None
    ):
        return None
    try:
        verdict: Signal = compute_signal(
            target_price=row.target_price,
            entry_price=row.entry_price,
            current_price=row.price,
            entry_date=row.latest_at,
            target_date=row.target_date,
            now=now,
        )
    except ValueError:
        return None
    return verdict


def _upside(target: float | None, current: float | None) -> float | None:
    """upside_to_target_live = (target - current) / current. Live-price denominator.

    None when either side is missing or the price is non-positive — never a
    fabricated number (Coverage plan: "不能缺价硬算")."""
    if target is None or current is None or current <= 0:
        return None
    return (target - current) / current


def _needs_refresh(row: CoverageRow) -> list[NeedsRefreshReason]:
    """Phase-1 refresh rules. Each reason deep-links to its source.

    Deferred (need data this layer doesn't fetch yet): ``stale_catalyst``
    (catalyst/earnings fetch) and ``run_failed`` (batch-run state, Phase 2).
    """
    reasons: list[NeedsRefreshReason] = []
    if row.run_count == 0:
        reasons.append(NeedsRefreshReason(kind="never_run", detail="覆盖池中但从未跑过 Research"))
        return reasons
    # Reuse the signal's own band logic — no second magic threshold. A closed
    # signal means the target was hit or the thesis broke → time to re-evaluate.
    if row.signal == "hit":
        reasons.append(
            NeedsRefreshReason(
                kind="signal_closed",
                detail="现价已达/超过目标价，结论待复核",
                artifact_id=row.latest_artifact_id,
            )
        )
    elif row.signal == "failed":
        reasons.append(
            NeedsRefreshReason(
                kind="signal_closed",
                detail="现价已跌破论点区间，结论待复核",
                artifact_id=row.latest_artifact_id,
            )
        )
    return reasons


def _extend_unique(target: list[str], extra: list[str]) -> None:
    for item in extra:
        if item not in target:
            target.append(item)


# ── State D: system "Studied Tickers" group ──────────────────────────────────


async def ensure_system_group(
    store: CoverageStore,
    artifact_store: ArtifactStore,
) -> CoverageGroup | None:
    """Seed a one-time ``Studied Tickers`` group for an old user with artifacts
    but no coverage groups (Coverage plan State D).

    Returns the created group, or None when seeding doesn't apply (groups
    already exist, or there are no studied tickers). Idempotent: once any group
    exists this is a no-op, so user edits / deletions are never undone.
    """
    if await store.count_groups() > 0:
        return None
    summaries = await artifact_store.list_by_ticker(ticker=None, include_archived=False, limit=500)
    tickers = sorted({s.ticker for s in summaries if s.ticker})
    if not tickers:
        return None
    group = await store.create_group(
        _SYSTEM_GROUP_NAME,
        "从你的历史研报自动生成；可改名、删 ticker 或删除整组。",
        is_system=True,
    )
    await store.add_members(group.id, tickers)
    logger.info("Seeded system coverage group %s with %d tickers", group.id, len(tickers))
    return group
