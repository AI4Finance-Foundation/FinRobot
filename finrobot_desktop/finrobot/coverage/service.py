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
from dataclasses import dataclass
from datetime import datetime, timezone

from finrobot.artifact.models import ArtifactSummary
from finrobot.artifact.store import ArtifactStore
from finrobot.coverage.models import (
    CoverageGroup,
    CoverageGroupDetail,
    CoverageOverview,
    CoverageRow,
    NeedsRefreshReason,
    NumberSource,
)
from finrobot.coverage.sqlite_store import CoverageStore
from finrobot.engine.compute.operators.compare import (
    CompanyValuation,
    ComparisonResult,
    build_company_valuation,
)
from finrobot.engine.compute.coordinators.extractor import extract_financial_data
from finrobot.engine.compute.operators.signal import Signal, compute_signal
from finrobot.engine.data.normalize.contracts import (
    DEGRADED_CLOSE_ONLY,
    DEGRADED_TTM_LAG,
    Provenance,
)
from finrobot.engine.models.financial import (
    FIELD_WARN_EV_MISSING_NET_DEBT,
    FIELD_WARN_SHARES_DERIVED,
    DCFResult,
)
from finrobot.engine.data.interface import ProviderError
from finrobot.engine.data.layer import DataLayer
from finrobot.engine.data.types import DataType
from finrobot.run_store import RunRecord, RunStore

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
_SYSTEM_GROUP_DESC = "打开过的股票自动进这里；可改名、删 ticker 或删除整组。"

# Artifact types that embed a DCF result, and the structured keys it may sit
# under (equity_research nests it under financial_modeling; dcf at dcf_calc;
# ic_memo at dcf_result). Mirrors routes/valuation.py's reconstruction.
_DCF_BEARING_TYPES = ("dcf", "equity_research", "ic_memo")
_DCF_STRUCTURED_KEYS = ("dcf_calc", "financial_modeling", "dcf_result")


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


# ── Overview ─────────────────────────────────────────────────────────────────


# Max concurrent per-ticker market fan-outs on the NETWORK (revalidate) path.
# The cache-only first paint reads local SQLite and ignores this. Without a
# bound, a 100-ticker group fired 200 simultaneous provider calls (100 PRICE +
# 100 FINANCIALS), saturating the chain and rate-limits — measured >180s and
# climbing. A small bound keeps the chain healthy; the desk no longer waits on
# this anyway (it paints from cache, revalidates in the background).
_MARKET_FANOUT_CONCURRENCY = 8


async def build_overview(
    group: CoverageGroupDetail,
    *,
    artifact_store: ArtifactStore,
    data_layer: DataLayer,
    run_store: "RunStore | None" = None,
    now: datetime | None = None,
    cache_only: bool = False,
) -> CoverageOverview:
    """Assemble the Coverage Table for one group.

    Rows are built concurrently — each ticker's chain (artifacts + canonical
    PRICE/FINANCIALS + signal) is independent, so wall-clock is one ticker's
    latency, not N×. On the network path the per-ticker fan-out is bounded by a
    semaphore (``_MARKET_FANOUT_CONCURRENCY``) so a large group can't saturate
    the provider chain.

    ``run_store`` is optional: when given, each row carries the latest run's
    status/error (an in-flight batch run, or a failed attempt) and a
    ``run_failed`` refresh reason.

    ``cache_only`` is the **instant first-paint**: market cells come from the
    canonical cache (allow-stale) with NO network — ~ms at any N (measured 5ms
    for 6 tickers, 4ms for 100). Rows past their freshness TTL carry
    ``market_stale=True``; genuinely-cold rows leave market ``None``. The client
    paints this immediately, then revalidates with a network pass (the default,
    ``cache_only=False``) that repopulates the cache and returns fresh numbers.
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
            cache_only=cache_only,
        )

    latest_runs = {}
    if run_store is not None:
        try:
            latest_runs = await run_store.latest_runs_by_ticker(tickers)
        except (sqlite3.Error, RuntimeError, OSError) as exc:
            logger.warning("Coverage overview run-status lookup failed: %s", exc)

    # Only the network path needs throttling; cache reads are cheap. A shared
    # semaphore caps concurrent outbound market fan-outs across the whole group.
    sem = None if cache_only else asyncio.Semaphore(_MARKET_FANOUT_CONCURRENCY)
    rows = await asyncio.gather(
        *(
            _assemble_row(
                t,
                artifact_store=artifact_store,
                data_layer=data_layer,
                latest_run=latest_runs.get(t.upper()),
                now=now,
                cache_only=cache_only,
                market_sem=sem,
            )
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
        cache_only=cache_only,
    )


async def _assemble_row(
    ticker: str,
    *,
    artifact_store: ArtifactStore,
    data_layer: DataLayer,
    latest_run: "RunRecord | None" = None,
    now: datetime,
    cache_only: bool = False,
    market_sem: "asyncio.Semaphore | None" = None,
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

    # 2. Market side — degradable independently of the research side. The
    # cache-only path reads local SQLite (instant, last-known snapshot); the
    # network path is throttled by the shared semaphore so a big group can't
    # saturate the provider chain.
    if cache_only:
        await _apply_market_fields(row, ticker, data_layer, cache_only=True)
    elif market_sem is not None:
        async with market_sem:
            await _apply_market_fields(row, ticker, data_layer, cache_only=False)
    else:
        await _apply_market_fields(row, ticker, data_layer, cache_only=False)

    # 3. Live run state (in-flight batch run / failed attempt).
    if latest_run is not None:
        row.run_status = latest_run.status
        row.run_error = latest_run.error

    # 4. Derived — signal + live upside + refresh reasons.
    row.signal = _safe_signal(row, now)
    row.upside_to_target_live = _upside(row.target_price, row.price)
    if row.upside_to_target_live is not None:
        # Derived from the artifact's target vs the live price — traces back to
        # the report (as_of = its created_at), not to a data provider.
        row.sources.upside_to_target_live = NumberSource(
            formula_id="upside_to_target_live",
            as_of=row.latest_at,
            artifact_id=row.latest_artifact_id,
        )
    row.needs_refresh = _needs_refresh(row)
    return row


def _apply_research_fields(row: CoverageRow, summaries: list[ArtifactSummary]) -> None:
    """Verdict / target / entry / artifact_count / research_count / latest_*.

    The research-conclusion columns (verdict / target / entry / target_date and
    the latest_* provenance triple) come ONLY from a thesis-bearing report —
    equity_research / ic_memo carry a verdict; a standalone DCF / LBO / comps /
    earnings artifact does not. Sourcing them from ``summaries[0]`` (newest of
    ANY type) let a freshly-run DCF blank the verdict and pass its implied_price
    off as a research target (BUG-054).

    Two counts, deliberately split: ``artifact_count`` is every artifact (total
    activity), ``research_count`` only the thesis-bearing ones (``verdict is not
    None``) — the honest "N 份研报" the UI shows. ``signal`` is computed
    downstream against the live price.
    """
    row.artifact_count = len(summaries)
    row.research_count = sum(1 for s in summaries if s.verdict is not None)
    # A verdict is only ever set on thesis-bearing artifacts, so it's the
    # reliable "is this a research conclusion?" gate. Newest such artifact wins
    # (store returns created_at DESC).
    research = next((s for s in summaries if s.verdict is not None), None)
    if research is None:
        return
    row.latest_verdict = research.verdict
    row.target_price = research.target_price
    row.target_date = research.target_date
    row.entry_price = research.entry_price
    row.latest_artifact_id = research.id
    row.latest_type = research.type
    row.latest_at = research.created_at


# A provenance degraded code → the field it most directly caveats, with a
# concise Chinese note (matching the row-warning style). Only codes with a clear
# single-field attribution live here; ``ccy_inferred`` stays on the currency
# column rather than being smeared across every价-denominated cell.
_DEGRADED_CAVEAT = {
    DEGRADED_CLOSE_ONLY: "实时价缺失，用最近收盘价",
    DEGRADED_TTM_LAG: "TTM 口径滞后(P/E 分母)",
}

# Structured field-warning codes (from extract_financial_data) → cell caveat.
# Attribution happens at the generation site (the field is known there), so this
# maps code→文案 without coupling to the extractor's English prose.
_FIELD_WARN_CAVEAT = {
    FIELD_WARN_EV_MISSING_NET_DEBT: "缺净债(total_debt/cash)，EV 类无法计算",
    FIELD_WARN_SHARES_DERIVED: "股数缺失，按市值/价反推，每股指标近似",
}


def _caveat(degraded: list[str], code: str) -> str | None:
    """The caveat note for ``code`` iff this snapshot is degraded by it."""
    return _DEGRADED_CAVEAT[code] if code in degraded else None


def _field_caveats(field_warnings: dict[str, list[str]], field: str) -> list[str]:
    """Localized caveats for a field's structured warning codes."""
    return [_FIELD_WARN_CAVEAT[c] for c in field_warnings.get(field, []) if c in _FIELD_WARN_CAVEAT]


def _join_caveats(*parts: str | None) -> str | None:
    """Join the non-empty caveats for one cell; None when there are none."""
    items = [p for p in parts if p]
    return "；".join(items) if items else None


def _source(
    prov: Provenance,
    *,
    formula_id: str | None = None,
    formula_warning: str | None = None,
) -> NumberSource:
    """Project a snapshot's :class:`Provenance` into a cell ``NumberSource``."""
    return NumberSource(
        provider=prov.provider,
        as_of=prov.as_of,
        fetched_at=prov.fetched_at,
        formula_id=formula_id,
        formula_warning=formula_warning,
    )


async def _apply_market_fields(
    row: CoverageRow, ticker: str, data_layer: DataLayer, *, cache_only: bool = False
) -> None:
    """Price / 1D / market cap / TTM revenue / EV-EBITDA / P/E.

    Reuses ``extract_financial_data`` — the same assembly behind
    ``/api/data/{ticker}/financials`` — so no caliber is re-derived. Price-only
    fields survive a financials-extraction failure (and vice-versa); both
    degradations surface as row warnings, never an exception.

    ``cache_only`` reads the canonical cache WITHOUT touching the provider chain
    (instant first paint): a snapshot past its TTL still populates the cells and
    sets ``row.market_stale`` (the client shows last-known + "refreshing", not a
    blank shimmer); a true cache miss leaves the cells ``None`` (cold → shimmer).
    """
    price_norm = None
    fin_norm = None
    if cache_only:
        price_hit = await data_layer.read_canonical_cached(DataType.PRICE, ticker)
        if price_hit is not None:
            price_norm, price_stale = price_hit
            row.market_stale = row.market_stale or price_stale
        fin_hit = await data_layer.read_canonical_cached(DataType.FINANCIALS, ticker)
        if fin_hit is not None:
            fin_norm, fin_stale = fin_hit
            row.market_stale = row.market_stale or fin_stale
    else:
        try:
            price_norm = await data_layer.fetch_canonical(DataType.PRICE, ticker)
        except _MARKET_DEGRADABLE as exc:
            row.warnings.append(f"{ticker} 行情获取失败：{exc}")
        try:
            fin_norm = await data_layer.fetch_canonical(DataType.FINANCIALS, ticker)
        except _MARKET_DEGRADABLE as exc:
            row.warnings.append(f"{ticker} 财务获取失败：{exc}")

    if price_norm is not None:
        prov = price_norm.provenance
        row.price = price_norm.current_price
        _, row.change_pct_1d = price_norm.latest_session_change()
        row.price_as_of = prov.as_of
        row.currency = price_norm.quote_currency
        _extend_unique(row.warnings, price_norm.warnings)
        # close_only caveats the price itself (we're showing last close, not a
        # live quote); the 1D change carries its own derivation formula.
        row.sources.price = _source(
            prov, formula_warning=_caveat(prov.degraded, DEGRADED_CLOSE_ONLY)
        )
        row.sources.change_pct_1d = _source(prov, formula_id="latest_session_change")

    if price_norm is not None and fin_norm is not None:
        try:
            fd = extract_financial_data(fin_norm, price_norm)
        except _MARKET_DEGRADABLE as exc:
            row.warnings.append(f"{ticker} 财务字段提取失败：{exc}")
        else:
            fprov = fin_norm.provenance
            row.market_cap = fd.market.market_cap
            row.revenue_ttm = fd.income.revenue
            row.ev_ebitda = fd.valuation.ev_ebitda
            row.pe = fd.market.pe_ratio
            row.currency = fd.quote_currency or row.currency
            _extend_unique(row.warnings, fd.warnings)
            fw = fd.field_warnings
            row.sources.market_cap = _source(fprov, formula_id="market_cap")
            row.sources.revenue_ttm = _source(fprov)
            # EV/EBITDA uncomputable without net debt — caveat sits on the cell.
            row.sources.ev_ebitda = _source(
                fprov,
                formula_id="ev_ebitda",
                formula_warning=_join_caveats(*_field_caveats(fw, "ev_ebitda")),
            )
            # P/E: ttm_lag (denominator) + derived-shares both bite here.
            row.sources.pe = _source(
                fprov,
                formula_id="pe_ttm",
                formula_warning=_join_caveats(
                    _caveat(fprov.degraded, DEGRADED_TTM_LAG), *_field_caveats(fw, "pe")
                ),
            )


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
    """Refresh rules. Each reason deep-links to its source.

    Deferred (needs catalyst/earnings fetch this layer doesn't do yet):
    ``stale_catalyst``.
    """
    reasons: list[NeedsRefreshReason] = []
    # A failed last run is the most actionable signal — retry it. Takes
    # precedence over "never run" (the failure is why there's no artifact).
    if row.run_status == "failed":
        reasons.append(
            NeedsRefreshReason(
                kind="run_failed",
                detail=f"上次运行失败：{row.run_error or '未知错误'}",
            )
        )
        return reasons
    # "never_run" means no *thesis-bearing* research yet — a ticker with only a
    # standalone DCF/LBO/comps (artifact_count > 0 but research_count == 0) still
    # owes a Research run, which is exactly what the detail copy promises.
    if row.research_count == 0:
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
    # Atomic find-or-create so a concurrent ensure_studied_membership /
    # second State-D seed can't race us into two duplicate system groups
    # (BUG-088).
    group = await store.get_or_create_system_group(_SYSTEM_GROUP_NAME, _SYSTEM_GROUP_DESC)
    await store.add_members(group.id, tickers)
    logger.info("Seeded system coverage group %s with %d tickers", group.id, len(tickers))
    return group


async def ensure_studied_membership(
    store: CoverageStore,
    ticker: str,
) -> CoverageGroupDetail:
    """Add ``ticker`` to the default ``Studied Tickers`` workspace (find-or-create).

    The product contract (Coverage redesign §2): opening ``/stocks/:ticker``
    auto-enrols that name into the default workspace. This is the write side of
    that — idempotent, so re-opening a name is a no-op, and a name removed from
    the workspace re-enters on the next open.

    Distinct from :func:`ensure_system_group` (the State-D one-time backfill,
    gated on "zero groups"): this targets the single ``is_system`` group
    regardless of how many hand-built groups exist, creating it on first use if
    the State-D seed never fired (e.g. a brand-new user with no prior artifacts).
    """
    # Atomic find-or-create (BUG-088): the partial unique index +
    # ON CONFLICT DO NOTHING guarantees a single is_system row even when this
    # races a concurrent first-screen seed, so a ticker can no longer be
    # orphaned in a duplicate "Studied Tickers" group.
    group = await store.get_or_create_system_group(_SYSTEM_GROUP_NAME, _SYSTEM_GROUP_DESC)
    detail = await store.add_members(group.id, [ticker])
    # add_members only returns None when the group vanished between the two
    # awaits (another session deleted it) — re-seed once so the auto-add is
    # never silently lost.
    if detail is None:
        fresh = await store.get_or_create_system_group(_SYSTEM_GROUP_NAME, _SYSTEM_GROUP_DESC)
        detail = await store.add_members(fresh.id, [ticker])
        assert detail is not None  # just created
    return detail


# ── Compare (H1) ─────────────────────────────────────────────────────────────


async def build_comparison(
    tickers: list[str],
    *,
    artifact_store: ArtifactStore,
    data_layer: DataLayer,
) -> ComparisonResult:
    """Side-by-side DCF comparison, assembled from each ticker's latest DCF
    artifact + live market fields.

    The expensive DCF *generation* is NOT done here — it runs through the
    async batch-run path (one DCF run per ticker). This function is a fast,
    LLM-free assembly over already-stored results (H1: the GET runs no
    pipeline, so it can't time out). A ticker with no DCF artifact comes back
    as a ``CompanyValuation`` carrying an error → the UI prompts "run DCF
    first". upside uses the **live** current price (to-fair-value-from-today),
    consistent with the Coverage Table.
    """
    companies = await asyncio.gather(
        *(_compare_one(t, artifact_store=artifact_store, data_layer=data_layer) for t in tickers)
    )
    return ComparisonResult(companies=list(companies))


async def _compare_one(
    ticker: str,
    *,
    artifact_store: ArtifactStore,
    data_layer: DataLayer,
) -> CompanyValuation:
    ticker = ticker.upper()
    found = await _latest_dcf_result(artifact_store, ticker)
    if found is None:
        return CompanyValuation(ticker=ticker, error="尚未运行 DCF——先对该 ticker 运行 DCF 再对比")
    dcf = found.dcf
    company_name = ""
    current_price: float | None = None
    ev_ebitda: float | None = None
    pe_ratio: float | None = None
    warnings: list[str] = []
    try:
        fin_norm = await data_layer.fetch_canonical(DataType.FINANCIALS, ticker)
        price_norm = await data_layer.fetch_canonical(DataType.PRICE, ticker)
        fd = extract_financial_data(fin_norm, price_norm)
        company_name = fd.company_name
        current_price = fd.market.current_price
        ev_ebitda = fd.valuation.ev_ebitda
        pe_ratio = fd.market.pe_ratio
        warnings = list(fd.warnings)
    except _MARKET_DEGRADABLE as exc:
        # DCF (implied price, WACC) still compares fine without live market —
        # only current_price-relative upside degrades. Surface, don't drop.
        warnings = [f"{ticker} 实时市场数据获取失败：{exc}"]
    # Provenance: the DCF this row compares may be stale or archived. current_price
    # is live but implied_price/WACC are frozen at dcf_as_of — disclose it so the
    # user can see which rows are today's vs weeks-old, and never compares against
    # an archived (superseded) valuation unknowingly.
    if found.archived:
        warnings.append(f"{ticker} 的 DCF 来自已归档（被新版本取代）的研究——结论可能已过时")
    return build_company_valuation(
        ticker=ticker,
        company_name=company_name,
        current_price=current_price,
        dcf_result=dcf,
        ev_ebitda=ev_ebitda,
        pe_ratio=pe_ratio,
        warnings=warnings,
        dcf_as_of=found.created_at.isoformat(),
        dcf_artifact_id=found.artifact_id,
    )


@dataclass(frozen=True)
class _LatestDcf:
    """A reconstructed DCF plus the provenance of the artifact it came from.

    Carries the source artifact's ``created_at`` (vintage) and ``id`` so the
    Compare assembly can stamp each row — a comparison that mixes a freshly-run
    DCF with a three-week-old stored one must disclose which is which.
    """

    dcf: DCFResult
    created_at: datetime
    artifact_id: str
    archived: bool


async def _latest_dcf_result(artifact_store: ArtifactStore, ticker: str) -> _LatestDcf | None:
    """Reconstruct the most recent DCFResult for a ticker from its stored
    artifacts, together with that artifact's vintage (created_at) and id. Walks
    newest-first across DCF-bearing types; returns the first that parses. (Same
    reconstruction as routes/valuation._parse_dcf, scoped to the single latest
    DCF rather than latest-of-each-type.)"""
    summaries = await artifact_store.list_by_ticker(ticker=ticker, include_archived=True, limit=200)
    for summary in summaries:  # newest first
        if summary.type not in _DCF_BEARING_TYPES:
            continue
        artifact = await artifact_store.get(summary.id)
        if artifact is None or artifact.outputs is None:
            continue
        structured = artifact.outputs.structured
        for key in _DCF_STRUCTURED_KEYS:
            candidate = structured.get(key)
            if isinstance(candidate, dict):
                try:
                    dcf = DCFResult.model_validate(candidate)
                except (TypeError, ValueError) as exc:
                    logger.debug("DCFResult parse failed for %s at %s: %s", ticker, key, exc)
                    continue
                return _LatestDcf(
                    dcf=dcf,
                    created_at=summary.created_at,
                    artifact_id=summary.id,
                    archived=summary.archived,
                )
    return None
