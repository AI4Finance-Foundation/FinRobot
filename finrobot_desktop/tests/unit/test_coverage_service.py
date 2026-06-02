"""coverage/service.py — overview assembly + State-D system group.

Market inputs are built through the real ``normalize_*`` path (same as a
``DataLayer.fetch_canonical`` consumer) so ``extract_financial_data`` runs for
real; the artifact store and data layer are stubbed at their method surface.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from finrobot.artifact.models import ArtifactSummary
from finrobot.coverage.models import CoverageGroupDetail, CoverageMember, CoverageRow
from finrobot.coverage.service import (
    _needs_refresh,
    _safe_signal,
    _upside,
    build_overview,
    ensure_system_group,
)
from finrobot.coverage.sqlite_store import CoverageStore
from finrobot.engine.data.interface import DataResult, ProviderError
from finrobot.engine.data.normalize.financials import normalize_financials
from finrobot.engine.data.normalize.price import normalize_price
from finrobot.engine.data.types import DataType

UTC = timezone.utc
ENTRY = datetime(2026, 4, 1, tzinfo=UTC)
NOW = ENTRY + timedelta(days=30)


# ── builders ─────────────────────────────────────────────────────────────────


def _summary(
    *,
    artifact_id: str = "art_1",
    ticker: str = "AAPL",
    entry: float | None = 180.0,
    target: float | None = 240.0,
    verdict: str | None = "BUY",
    created_at: datetime = ENTRY,
    type_: str = "equity_research",
) -> ArtifactSummary:
    return ArtifactSummary(
        id=artifact_id,
        ticker=ticker,
        cross_tickers=[],
        type=type_,
        created_at=created_at,
        headline="x",
        source="pipeline:equity_research",
        archived=False,
        entry_price=entry,
        target_price=target,
        target_date=created_at + timedelta(days=365),
        signal=None,
        verdict=verdict,
    )


def _fin(ticker: str = "AAPL", **overrides):
    data = dict(
        revenue=100e9,
        ebitda=35e9,
        net_income=20e9,
        gross_margin=0.47,
        operating_margin=0.28,
        pe_ratio=28.5,
        market_cap=3e12,
        shares_outstanding=15e9,
        current_price=200.0,
        total_debt=50e9,
        total_cash=20e9,
    )
    data.update(overrides)
    return normalize_financials(
        DataResult(
            data=data, provider="yfinance", ticker=ticker, data_type="financials", timestamp=NOW
        )
    )


def _price(ticker: str = "AAPL", current: float = 200.0):
    bars = [
        {"date": "2025-06-01", "close": 180.0},
        {"date": "2025-12-01", "close": 196.0},
        {"date": "2026-03-01", "close": current},
    ]
    return normalize_price(
        DataResult(
            data={"current_price": current, "price_history": bars},
            provider="yfinance",
            ticker=ticker,
            data_type="price",
            timestamp=NOW,
        )
    )


class _StubArtifactStore:
    def __init__(self, by_ticker: dict[str, list[ArtifactSummary]]) -> None:
        self._by_ticker = {k.upper(): v for k, v in by_ticker.items()}

    async def list_by_ticker(
        self, ticker=None, type=None, include_archived=False, limit=100
    ) -> list[ArtifactSummary]:  # noqa: A002
        if ticker is None:
            flat = [s for lst in self._by_ticker.values() for s in lst]
        else:
            flat = list(self._by_ticker.get(ticker.upper(), []))
        flat.sort(key=lambda s: s.created_at, reverse=True)
        return flat[:limit]


class _StubDataLayer:
    def __init__(self, *, raise_for: set[str] | None = None, current: float = 200.0) -> None:
        self._raise_for = {t.upper() for t in (raise_for or set())}
        self._current = current

    async def fetch_canonical(self, data_type, ticker, **_):
        if ticker.upper() in self._raise_for:
            raise ProviderError(f"simulated outage for {ticker}")
        if data_type == DataType.PRICE:
            return _price(ticker, current=self._current)
        return _fin(ticker)


def _group(*tickers: str) -> CoverageGroupDetail:
    return CoverageGroupDetail(
        id="cov_test",
        name="Test",
        is_system=False,
        created_at=ENTRY,
        updated_at=ENTRY,
        members=[CoverageMember(ticker=t, added_at=ENTRY) for t in tickers],
    )


# ── pure helpers ───────────────────────────────────────────────────────────


def test_upside_live_denominator() -> None:
    assert _upside(240.0, 200.0) == pytest.approx(0.20)
    assert _upside(None, 200.0) is None
    assert _upside(240.0, None) is None
    assert _upside(240.0, 0.0) is None  # never divide by a non-positive price


def test_safe_signal_classifies_and_guards() -> None:
    hit = CoverageRow(ticker="X", entry_price=100, target_price=120, price=115, latest_at=ENTRY)
    assert _safe_signal(hit, NOW) == "hit"
    watching = CoverageRow(
        ticker="X", entry_price=100, target_price=120, price=105, latest_at=ENTRY
    )
    assert _safe_signal(watching, NOW) == "watching"
    no_price = CoverageRow(
        ticker="X", entry_price=100, target_price=120, price=None, latest_at=ENTRY
    )
    assert _safe_signal(no_price, NOW) is None
    degenerate = CoverageRow(
        ticker="X", entry_price=100, target_price=100, price=100, latest_at=ENTRY
    )
    assert _safe_signal(degenerate, NOW) is None  # compute_signal ValueError swallowed


def test_needs_refresh_never_run_and_signal_closed() -> None:
    never = CoverageRow(ticker="X", run_count=0)
    assert [r.kind for r in _needs_refresh(never)] == ["never_run"]

    hit = CoverageRow(ticker="X", run_count=2, signal="hit", latest_artifact_id="a1")
    reasons = _needs_refresh(hit)
    assert reasons[0].kind == "signal_closed"
    assert reasons[0].artifact_id == "a1"

    watching = CoverageRow(ticker="X", run_count=2, signal="watching")
    assert _needs_refresh(watching) == []


# ── build_overview ───────────────────────────────────────────────────────────


async def test_overview_empty_group() -> None:
    ov = await build_overview(
        _group(),
        artifact_store=_StubArtifactStore({}),  # type: ignore[arg-type]
        data_layer=_StubDataLayer(),  # type: ignore[arg-type]
        now=NOW,
    )
    assert ov.rows == []
    assert ov.partial is False


async def test_overview_happy_path_fields() -> None:
    store = _StubArtifactStore({"AAPL": [_summary()]})
    ov = await build_overview(
        _group("AAPL"),
        artifact_store=store,  # type: ignore[arg-type]
        data_layer=_StubDataLayer(current=200.0),  # type: ignore[arg-type]
        now=NOW,
    )
    (row,) = ov.rows
    assert row.ticker == "AAPL"
    assert row.price == 200.0
    assert row.market_cap == pytest.approx(3e12)
    assert row.revenue_ttm == pytest.approx(100e9)
    assert row.pe == pytest.approx(28.5)
    assert row.ev_ebitda is not None
    assert row.latest_verdict == "BUY"
    assert row.run_count == 1
    assert row.upside_to_target_live == pytest.approx((240 - 200) / 200)
    assert row.signal in {"hit", "watching", "failed"}
    assert ov.partial is False


async def test_overview_degraded_market_keeps_research_and_flags_partial() -> None:
    store = _StubArtifactStore({"NVDA": [_summary(ticker="NVDA", verdict="HOLD")]})
    ov = await build_overview(
        _group("NVDA"),
        artifact_store=store,  # type: ignore[arg-type]
        data_layer=_StubDataLayer(raise_for={"NVDA"}),  # type: ignore[arg-type]
        now=NOW,
    )
    (row,) = ov.rows
    # research side survives the market outage
    assert row.latest_verdict == "HOLD"
    assert row.run_count == 1
    # market side degraded, not fabricated
    assert row.price is None
    assert row.market_cap is None
    assert row.warnings  # outage surfaced
    assert ov.partial is True


async def test_overview_one_bad_ticker_does_not_blank_others() -> None:
    store = _StubArtifactStore(
        {"AAPL": [_summary(ticker="AAPL")], "NVDA": [_summary(ticker="NVDA")]}
    )
    ov = await build_overview(
        _group("AAPL", "NVDA"),
        artifact_store=store,  # type: ignore[arg-type]
        data_layer=_StubDataLayer(raise_for={"NVDA"}),  # type: ignore[arg-type]
        now=NOW,
    )
    by_ticker = {r.ticker: r for r in ov.rows}
    assert by_ticker["AAPL"].price == 200.0  # healthy ticker unaffected
    assert by_ticker["NVDA"].price is None  # bad ticker degraded
    assert ov.partial is True


async def test_overview_never_run_ticker() -> None:
    # In the group but never researched → 0 artifacts.
    ov = await build_overview(
        _group("TSLA"),
        artifact_store=_StubArtifactStore({}),  # type: ignore[arg-type]
        data_layer=_StubDataLayer(),  # type: ignore[arg-type]
        now=NOW,
    )
    (row,) = ov.rows
    assert row.run_count == 0
    assert [r.kind for r in row.needs_refresh] == ["never_run"]


# ── ensure_system_group (State D) ────────────────────────────────────────────


@pytest.fixture
async def store(tmp_path: Path):
    s = CoverageStore(db_path=tmp_path / "coverage.db")
    yield s
    await s.close()


async def test_ensure_system_group_seeds_from_artifacts(store: CoverageStore) -> None:
    art = _StubArtifactStore({"AAPL": [_summary(ticker="AAPL")], "MSFT": [_summary(ticker="MSFT")]})
    group = await ensure_system_group(store, art)  # type: ignore[arg-type]
    assert group is not None
    assert group.is_system is True
    detail = await store.get_group(group.id)
    assert detail is not None
    assert sorted(m.ticker for m in detail.members) == ["AAPL", "MSFT"]


async def test_ensure_system_group_noop_when_groups_exist(store: CoverageStore) -> None:
    await store.create_group("Existing")
    art = _StubArtifactStore({"AAPL": [_summary()]})
    assert await ensure_system_group(store, art) is None  # type: ignore[arg-type]
    assert await store.count_groups() == 1  # nothing seeded


async def test_ensure_system_group_noop_without_studied_tickers(store: CoverageStore) -> None:
    assert await ensure_system_group(store, _StubArtifactStore({})) is None  # type: ignore[arg-type]
    assert await store.count_groups() == 0
