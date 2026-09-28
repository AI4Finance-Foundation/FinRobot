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
    _caveat,
    _field_caveats,
    _join_caveats,
    _needs_refresh,
    _safe_signal,
    _upside,
    build_overview,
    ensure_studied_membership,
    ensure_system_group,
)
from finrobot.engine.data.normalize.contracts import DEGRADED_CLOSE_ONLY, DEGRADED_TTM_LAG
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


def _price(ticker: str = "AAPL", current: float = 200.0, quote_currency: str = "USD"):
    bars = [
        {"date": "2025-06-01", "close": 180.0},
        {"date": "2025-12-01", "close": 196.0},
        {"date": "2026-03-01", "close": current},
    ]
    return normalize_price(
        DataResult(
            data={
                "current_price": current,
                "price_history": bars,
                "quote_currency": quote_currency,
            },
            provider="yfinance",
            ticker=ticker,
            data_type="price",
            timestamp=NOW,
        )
    )


class _StubArtifactStore:
    def __init__(
        self,
        by_ticker: dict[str, list[ArtifactSummary]],
        artifacts: dict[str, object] | None = None,
    ) -> None:
        self._by_ticker = {k.upper(): v for k, v in by_ticker.items()}
        # id → artifact body (for .get); a name with no body returns None, so the
        # market-implied re-solve degrades to leaving market_implied None.
        self._artifacts = artifacts or {}

    async def list_by_ticker(
        self, ticker=None, type=None, include_archived=False, limit=100
    ) -> list[ArtifactSummary]:  # noqa: A002
        if ticker is None:
            flat = [s for lst in self._by_ticker.values() for s in lst]
        else:
            flat = list(self._by_ticker.get(ticker.upper(), []))
        flat.sort(key=lambda s: s.created_at, reverse=True)
        return flat[:limit]

    async def get(self, artifact_id: str) -> object | None:
        return self._artifacts.get(artifact_id)


class _StubDataLayer:
    def __init__(
        self,
        *,
        raise_for: set[str] | None = None,
        current: float = 200.0,
        cached: set[str] | None = None,
        cache_stale: bool = False,
        quote_currency: str = "USD",
        fx_rates: dict[str, float] | None = None,
        fx_raises: bool = False,
    ) -> None:
        self._raise_for = {t.upper() for t in (raise_for or set())}
        self._current = current
        # None == every ticker has a cache snapshot; a set restricts which do
        # (the rest are cold misses → read_canonical_cached returns None).
        self._cached = None if cached is None else {t.upper() for t in cached}
        self._cache_stale = cache_stale
        self._quote_currency = quote_currency
        # ccy → rate_to_usd. None == 1.0 for USD only, raise otherwise.
        self._fx_rates = fx_rates or {}
        self._fx_raises = fx_raises
        self.fx_calls: list[str] = []

    async def fetch_canonical(self, data_type, ticker, **_):
        if ticker.upper() in self._raise_for:
            raise ProviderError(f"simulated outage for {ticker}")
        if data_type == DataType.PRICE:
            return _price(ticker, current=self._current, quote_currency=self._quote_currency)
        return _fin(ticker, quote_currency=self._quote_currency)

    async def read_canonical_cached(self, data_type, ticker, **_):
        if self._cached is not None and ticker.upper() not in self._cached:
            return None
        norm = (
            _price(ticker, current=self._current, quote_currency=self._quote_currency)
            if data_type == DataType.PRICE
            else _fin(ticker, quote_currency=self._quote_currency)
        )
        return norm, self._cache_stale

    async def fx_rate_to_usd(self, currency: str) -> float:
        self.fx_calls.append(currency.upper())
        if currency.upper() == "USD":
            return 1.0
        if self._fx_raises:
            raise ProviderError(f"no FX rate for {currency}")
        return self._fx_rates[currency.upper()]


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
    # _safe_signal now takes the USD-aligned live price explicitly (the second
    # arg), not row.price — the caller is responsible for the FX conversion.
    hit = CoverageRow(ticker="X", entry_price=100, target_price=120, price=115, latest_at=ENTRY)
    assert _safe_signal(hit, 115.0, NOW) == "hit"
    watching = CoverageRow(
        ticker="X", entry_price=100, target_price=120, price=105, latest_at=ENTRY
    )
    assert _safe_signal(watching, 105.0, NOW) == "watching"
    no_price = CoverageRow(
        ticker="X", entry_price=100, target_price=120, price=None, latest_at=ENTRY
    )
    assert _safe_signal(no_price, None, NOW) is None
    degenerate = CoverageRow(
        ticker="X", entry_price=100, target_price=100, price=100, latest_at=ENTRY
    )
    # USD price present but degenerate thesis (entry==target) → ValueError swallowed.
    assert _safe_signal(degenerate, 100.0, NOW) is None


def test_needs_refresh_never_run_and_signal_closed() -> None:
    never = CoverageRow(ticker="X", research_count=0)
    assert [r.kind for r in _needs_refresh(never)] == ["never_run"]

    # Artifacts exist but none is thesis-bearing (only a standalone DCF) →
    # still "never run Research", because research_count is the gate now.
    dcf_only = CoverageRow(ticker="X", artifact_count=3, research_count=0)
    assert [r.kind for r in _needs_refresh(dcf_only)] == ["never_run"]

    hit = CoverageRow(ticker="X", research_count=1, signal="hit", latest_artifact_id="a1")
    reasons = _needs_refresh(hit)
    assert reasons[0].kind == "signal_closed"
    assert reasons[0].artifact_id == "a1"

    watching = CoverageRow(ticker="X", research_count=1, signal="watching")
    assert _needs_refresh(watching) == []


def test_needs_refresh_run_failed_takes_precedence() -> None:
    # A failed run is more actionable than "never run" and precedes it.
    row = CoverageRow(ticker="X", research_count=0, run_status="failed", run_error="boom")
    reasons = _needs_refresh(row)
    assert [r.kind for r in reasons] == ["run_failed"]
    assert "boom" in reasons[0].detail


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
    assert row.artifact_count == 1
    assert row.research_count == 1  # the lone artifact carries a verdict
    assert row.upside_to_target_live == pytest.approx((240 - 200) / 200)
    assert row.signal in {"hit", "watching", "failed"}
    assert ov.partial is False


async def test_overview_populates_market_implied_nature_from_latest_dcf() -> None:
    """When a ticker has a DCF-bearing artifact, the network overview re-solves
    the reverse-DCF against the LIVE price and stamps the row's valuation nature
    + provenance. A live price far above any plausible growth → option_value."""
    from types import SimpleNamespace

    from finrobot.engine.compute.operators.dcf import calculate_dcf
    from finrobot.engine.models.financial import DCFInputs

    inputs = DCFInputs(
        revenue_base=100_000_000_000,
        revenue_growth_rates=[0.05] * 5,
        ebitda_margin=0.35,
        capex_pct_revenue=0.05,
        nwc_pct_revenue=0.02,
        tax_rate=0.21,
        risk_free_rate=0.04,
        beta=1.2,
        equity_risk_premium=0.05,
        cost_of_debt=0.04,
        debt_ratio=0.1,
        terminal_growth_rate=0.025,
        shares_outstanding=1_000_000_000,
        net_debt=10_000_000_000,
    )
    dcf = calculate_dcf(inputs)
    # _summary() defaults to type=equity_research, which nests its DCF under
    # `financial_modeling` (a plain dcf artifact would instead dump it FLAT).
    body = SimpleNamespace(
        outputs=SimpleNamespace(structured={"financial_modeling": dcf.model_dump()})
    )
    store = _StubArtifactStore({"AAPL": [_summary()]}, artifacts={"art_1": body})

    ov = await build_overview(
        _group("AAPL"),
        artifact_store=store,  # type: ignore[arg-type]
        data_layer=_StubDataLayer(current=100_000.0),  # type: ignore[arg-type]
        now=NOW,
    )
    (row,) = ov.rows
    assert row.market_implied is not None
    assert row.market_implied.kind == "option_value"
    assert row.market_implied.ceiling_price is not None
    # Traceable to the artifact the DCF inputs came from.
    assert row.sources.market_implied is not None
    assert row.sources.market_implied.artifact_id == "art_1"


async def test_market_implied_reverse_solves_on_usd_price_for_foreign_listing(
    monkeypatch,
) -> None:
    """The reverse-DCF nature must be solved against the USD-aligned live price, not
    the raw quote-currency price — the DCF inputs are USD, so a foreign LOCAL listing
    (2330.TW, quote=TWD) feeding its raw TWD price would reverse-solve garbage."""
    from types import SimpleNamespace

    import finrobot.coverage.service as svc
    from finrobot.engine.compute.operators.dcf import calculate_dcf
    from finrobot.engine.models.financial import DCFInputs

    inputs = DCFInputs(
        revenue_base=100_000_000_000,
        revenue_growth_rates=[0.05] * 5,
        ebitda_margin=0.35,
        capex_pct_revenue=0.05,
        nwc_pct_revenue=0.02,
        tax_rate=0.21,
        risk_free_rate=0.04,
        beta=1.2,
        equity_risk_premium=0.05,
        cost_of_debt=0.04,
        debt_ratio=0.1,
        terminal_growth_rate=0.025,
        shares_outstanding=1_000_000_000,
        net_debt=10_000_000_000,
    )
    dcf = calculate_dcf(inputs)
    body = SimpleNamespace(
        outputs=SimpleNamespace(structured={"financial_modeling": dcf.model_dump()})
    )
    store = _StubArtifactStore({"2330.TW": [_summary(ticker="2330.TW")]}, artifacts={"art_1": body})

    seen: dict[str, float] = {}
    _orig = svc.classify_market_implied_nature

    def _capture(inputs_, current_price, *, horizon_years):
        seen["price"] = current_price
        return _orig(inputs_, current_price, horizon_years=horizon_years)

    monkeypatch.setattr(svc, "classify_market_implied_nature", _capture)

    # TWD live 3000, rate 0.03178 → $95.34 USD. The reverse-DCF must see ~95, NOT 3000.
    await build_overview(
        _group("2330.TW"),
        artifact_store=store,  # type: ignore[arg-type]
        data_layer=_StubDataLayer(current=3000.0, quote_currency="TWD", fx_rates={"TWD": 0.03178}),  # type: ignore[arg-type]
        now=NOW,
    )
    assert seen["price"] == pytest.approx(3000.0 * 0.03178)  # USD, not the raw 3000 TWD


async def test_overview_market_implied_none_without_dcf() -> None:
    """No retrievable DCF artifact → market_implied stays None, never fabricated."""
    store = _StubArtifactStore({"AAPL": [_summary(verdict="BUY")]})  # summary only, no body
    ov = await build_overview(
        _group("AAPL"),
        artifact_store=store,  # type: ignore[arg-type]
        data_layer=_StubDataLayer(current=200.0),  # type: ignore[arg-type]
        now=NOW,
    )
    assert ov.rows[0].market_implied is None


async def test_research_fields_ignore_newer_non_thesis_artifact() -> None:
    """A standalone DCF run AFTER an equity_research report must not blank the
    verdict or overwrite the research target with its implied_price (BUG-054)."""
    research = _summary(
        artifact_id="art_eq",
        verdict="BUY",
        target=240.0,
        type_="equity_research",
        created_at=ENTRY,
    )
    newer_dcf = _summary(
        artifact_id="art_dcf",
        verdict=None,  # standalone models carry no thesis
        target=99.0,  # implied_price — must NOT become the research target
        type_="dcf",
        created_at=ENTRY + timedelta(days=10),
    )
    # Store returns created_at DESC → the DCF is summaries[0].
    store = _StubArtifactStore({"AAPL": [newer_dcf, research]})
    ov = await build_overview(
        _group("AAPL"),
        artifact_store=store,  # type: ignore[arg-type]
        data_layer=_StubDataLayer(current=200.0),  # type: ignore[arg-type]
        now=NOW,
    )
    (row,) = ov.rows
    assert row.latest_verdict == "BUY"  # from the equity_research, not blanked
    assert row.target_price == 240.0  # NOT the DCF's 99.0
    assert row.latest_type == "equity_research"
    assert row.latest_artifact_id == "art_eq"  # target/upside provenance is correct
    # Total activity counts both; "研报" counts only the thesis-bearing one.
    assert row.artifact_count == 2  # equity_research + dcf
    assert row.research_count == 1  # only the equity_research carries a verdict


def test_caveat_maps_only_attributable_degraded_codes() -> None:
    assert _caveat([DEGRADED_CLOSE_ONLY], DEGRADED_CLOSE_ONLY) is not None
    assert _caveat([DEGRADED_TTM_LAG], DEGRADED_TTM_LAG) is not None
    # Not degraded by the queried code → no caveat (never a fabricated warning).
    assert _caveat([], DEGRADED_CLOSE_ONLY) is None
    assert _caveat([DEGRADED_CLOSE_ONLY], DEGRADED_TTM_LAG) is None


async def test_overview_populates_per_field_sources() -> None:
    store = _StubArtifactStore({"AAPL": [_summary()]})
    ov = await build_overview(
        _group("AAPL"),
        artifact_store=store,  # type: ignore[arg-type]
        data_layer=_StubDataLayer(current=200.0),  # type: ignore[arg-type]
        now=NOW,
    )
    (row,) = ov.rows
    src = row.sources

    # Price/1D trace to the price provider, stamped with both timestamps; the
    # close-only fixture (bars carry only `close`) caveats the price cell.
    assert src.price is not None
    assert src.price.provider == "yfinance"
    assert src.price.as_of is not None
    assert src.price.fetched_at is not None
    assert src.price.formula_warning is not None  # close_only
    assert src.change_pct_1d is not None
    assert src.change_pct_1d.formula_id == "latest_session_change"

    # Fundamentals trace to the financials provider with their derivation id.
    assert src.market_cap is not None and src.market_cap.formula_id == "market_cap"
    assert src.ev_ebitda is not None and src.ev_ebitda.formula_id == "ev_ebitda"
    assert src.pe is not None and src.pe.formula_id == "pe_ttm"
    assert src.revenue_ttm is not None and src.revenue_ttm.provider == "yfinance"

    # Upside is derived from the artifact's target — it deep-links to the report.
    assert src.upside_to_target_live is not None
    assert src.upside_to_target_live.formula_id == "upside_to_target_live"
    assert src.upside_to_target_live.artifact_id == "art_1"
    assert src.upside_to_target_live.provider is None  # not a provider number


async def test_overview_cache_only_serves_stale_snapshot_no_network() -> None:
    # Instant first paint: market cells come from the canonical cache (allow
    # stale) and the provider chain must NOT be touched. A stale snapshot still
    # populates real numbers (last-known) and flags market_stale.
    class _CacheOnlyLayer(_StubDataLayer):
        async def fetch_canonical(self, data_type, ticker, **_):  # pragma: no cover
            raise AssertionError("cache_only must not hit the provider chain")

    store = _StubArtifactStore({"AAPL": [_summary()]})
    ov = await build_overview(
        _group("AAPL"),
        artifact_store=store,  # type: ignore[arg-type]
        data_layer=_CacheOnlyLayer(current=200.0, cache_stale=True),  # type: ignore[arg-type]
        now=NOW,
        cache_only=True,
    )
    assert ov.cache_only is True
    (row,) = ov.rows
    # research side present
    assert row.latest_verdict == "BUY"
    assert row.target_price == 240.0
    # market side served from the (stale) snapshot — real numbers, flagged stale
    assert row.price == 200.0
    assert row.market_cap is not None
    assert row.market_stale is True
    # price present → signal/upside compute off the snapshot, not pending
    assert row.upside_to_target_live is not None
    assert row.sources.price is not None
    assert ov.partial is False  # cache read never degrades


async def test_overview_cache_only_cold_miss_leaves_market_none() -> None:
    # A genuinely cold row (no cache snapshot) leaves market None — the client
    # shimmers it — and never falls through to the network on this path.
    class _CacheOnlyLayer(_StubDataLayer):
        async def fetch_canonical(self, data_type, ticker, **_):  # pragma: no cover
            raise AssertionError("cache_only must not hit the provider chain")

    ov = await build_overview(
        _group("AAPL"),
        artifact_store=_StubArtifactStore({"AAPL": [_summary()]}),  # type: ignore[arg-type]
        data_layer=_CacheOnlyLayer(cached=set()),  # type: ignore[arg-type]
        now=NOW,
        cache_only=True,
    )
    (row,) = ov.rows
    assert row.price is None
    assert row.market_cap is None
    assert row.market_stale is False  # absent, not stale
    assert row.upside_to_target_live is None
    assert ov.partial is False


async def test_overview_network_mode_default_cache_only_false() -> None:
    ov = await build_overview(
        _group("AAPL"),
        artifact_store=_StubArtifactStore({"AAPL": [_summary()]}),  # type: ignore[arg-type]
        data_layer=_StubDataLayer(),  # type: ignore[arg-type]
        now=NOW,
    )
    assert ov.cache_only is False
    assert ov.rows[0].price == 200.0  # market filled via the network path
    assert ov.rows[0].market_stale is False


# ── BUG-073-followup: signal/upside must compare same-currency legs ──────────
#
# entry/target are canonical USD (the normalize→USD invariant; the
# equity_research/ic_memo builders fold data_collection into USD). But the live
# PRICE canonical is NEVER FX-normalized (_apply_canonical_fx is FINANCIALS-only,
# "PRICE is unaffected"), so a foreign LOCAL listing (2330.TW, quote=TWD) feeds a
# TWD live price against a USD target — upside collapsed to ~−97% garbage. The fix
# converts the live price to USD before signal/upside; US (currency==USD) and pure
# ADRs (quote==USD) stay a strict no-op.


async def test_foreign_local_listing_signal_upside_computed_in_usd() -> None:
    """2330.TW class: quote=TWD live price, USD entry/target. Signal/upside MUST
    be computed on the USD-converted live price, not the raw TWD print."""
    # TWD live 640, rate 0.03125 → $20 USD. Target $24 USD, entry $18 USD.
    # Correct USD upside = (24 − 20) / 20 = +0.20 (a healthy "watching"),
    # NOT the broken (24 − 640) / 640 ≈ −0.96.
    store = _StubArtifactStore({"2330.TW": [_summary(ticker="2330.TW", entry=18.0, target=24.0)]})
    layer = _StubDataLayer(current=640.0, quote_currency="TWD", fx_rates={"TWD": 0.03125})
    ov = await build_overview(
        _group("2330.TW"),
        artifact_store=store,  # type: ignore[arg-type]
        data_layer=layer,  # type: ignore[arg-type]
        now=NOW,
    )
    (row,) = ov.rows
    # Display price stays in the honest quote currency (what the exchange prints).
    assert row.price == pytest.approx(640.0)
    assert row.currency == "TWD"
    # But the derived comparison legs are computed in USD.
    assert row.upside_to_target_live == pytest.approx((24.0 - 20.0) / 20.0)
    # USD legs: entry 18 → target 24 (move 6), price 20 → +2 of 6 (33%) → watching.
    # The broken TWD-vs-USD path would have read a hard reverse → "failed".
    assert row.signal == "watching"
    assert "TWD" in layer.fx_calls


async def test_foreign_local_listing_upside_not_garbage_without_fix() -> None:
    """Regression anchor: the raw-TWD-vs-USD upside would be deeply negative. Prove
    the converted upside is sane (positive, since target > USD price)."""
    store = _StubArtifactStore({"2330.TW": [_summary(ticker="2330.TW", entry=18.0, target=24.0)]})
    layer = _StubDataLayer(current=640.0, quote_currency="TWD", fx_rates={"TWD": 0.03125})
    ov = await build_overview(
        _group("2330.TW"),
        artifact_store=store,  # type: ignore[arg-type]
        data_layer=layer,  # type: ignore[arg-type]
        now=NOW,
    )
    (row,) = ov.rows
    assert row.upside_to_target_live is not None and row.upside_to_target_live > 0


async def test_us_issuer_signal_upside_unchanged_no_fx() -> None:
    """US ticker (currency==USD): the FX path is a strict no-op — never calls FX,
    signal/upside identical to before the fix."""
    store = _StubArtifactStore({"AAPL": [_summary(entry=180.0, target=240.0)]})
    layer = _StubDataLayer(current=200.0, quote_currency="USD")
    ov = await build_overview(
        _group("AAPL"),
        artifact_store=store,  # type: ignore[arg-type]
        data_layer=layer,  # type: ignore[arg-type]
        now=NOW,
    )
    (row,) = ov.rows
    assert row.currency == "USD"
    assert row.price == 200.0
    assert row.upside_to_target_live == pytest.approx((240.0 - 200.0) / 200.0)
    assert row.signal in {"hit", "watching", "failed"}
    # The no-op red line: a USD row must NOT touch the FX path at all.
    assert layer.fx_calls == []


async def test_pure_adr_quote_usd_no_fx() -> None:
    """A pure ADR (quote_currency==USD even though the issuer reports abroad):
    the price is already USD → no FX, no conversion."""
    store = _StubArtifactStore({"TSM": [_summary(ticker="TSM", entry=150.0, target=210.0)]})
    layer = _StubDataLayer(current=180.0, quote_currency="USD")
    ov = await build_overview(
        _group("TSM"),
        artifact_store=store,  # type: ignore[arg-type]
        data_layer=layer,  # type: ignore[arg-type]
        now=NOW,
    )
    (row,) = ov.rows
    assert row.currency == "USD"
    assert row.upside_to_target_live == pytest.approx((210.0 - 180.0) / 180.0)
    assert layer.fx_calls == []


async def test_foreign_local_listing_fx_unavailable_degrades_no_fabrication() -> None:
    """FX rate unobtainable → signal/upside left None (degrade), never computed on
    mixed currencies. The display price still shows the honest quote-currency print."""
    store = _StubArtifactStore({"2330.TW": [_summary(ticker="2330.TW", entry=18.0, target=24.0)]})
    layer = _StubDataLayer(current=640.0, quote_currency="TWD", fx_raises=True)
    ov = await build_overview(
        _group("2330.TW"),
        artifact_store=store,  # type: ignore[arg-type]
        data_layer=layer,  # type: ignore[arg-type]
        now=NOW,
    )
    (row,) = ov.rows
    assert row.price == pytest.approx(640.0)  # honest display
    assert row.currency == "TWD"
    # No mixed-currency fabrication: both derived legs degrade to None + a warning.
    assert row.signal is None
    assert row.upside_to_target_live is None
    assert any("FX" in w or "TWD" in w for w in row.warnings)


def test_field_caveats_and_join() -> None:
    fw = {"ev_ebitda": ["ev_missing_net_debt"], "pe": ["shares_derived"]}
    assert _field_caveats(fw, "ev_ebitda") == [
        "net debt (total_debt/cash) missing; EV-based metrics cannot be computed"
    ]
    assert _field_caveats(fw, "pe") == [
        "shares outstanding missing; derived from market cap / price, so per-share metrics are approximate"
    ]
    assert _field_caveats(fw, "market_cap") == []  # no code → no caveat
    assert (
        _field_caveats({"ev_ebitda": ["unknown_code"]}, "ev_ebitda") == []
    )  # unmapped code dropped
    assert _join_caveats(None, "a", None, "b") == "a; b"
    assert _join_caveats(None, None) is None


async def test_overview_field_warnings_land_on_the_right_cell() -> None:
    # A ticker whose provider lacks net debt → EV uncomputable. The caveat must
    # sit on the EV/EBITDA cell (not just a generic row warning).
    class _MissingDebtLayer:
        async def fetch_canonical(self, data_type, ticker, **_):
            if data_type == DataType.PRICE:
                return _price(ticker)
            return _fin(ticker, total_debt=None)

        async def read_canonical_cached(self, data_type, ticker, **_):
            return None  # cold → refresh path falls through to fetch_canonical

    ov = await build_overview(
        _group("AAPL"),
        artifact_store=_StubArtifactStore({"AAPL": [_summary()]}),  # type: ignore[arg-type]
        data_layer=_MissingDebtLayer(),  # type: ignore[arg-type]
        now=NOW,
    )
    (row,) = ov.rows
    assert row.ev_ebitda is None  # uncomputable, not fabricated
    assert row.sources.ev_ebitda is not None
    assert (
        row.sources.ev_ebitda.formula_warning
        == "net debt (total_debt/cash) missing; EV-based metrics cannot be computed"
    )


async def test_overview_degraded_market_leaves_sources_empty() -> None:
    # A market outage must not fabricate provenance for numbers we don't have.
    store = _StubArtifactStore({"NVDA": [_summary(ticker="NVDA")]})
    ov = await build_overview(
        _group("NVDA"),
        artifact_store=store,  # type: ignore[arg-type]
        data_layer=_StubDataLayer(raise_for={"NVDA"}),  # type: ignore[arg-type]
        now=NOW,
    )
    (row,) = ov.rows
    assert row.sources.price is None
    assert row.sources.market_cap is None
    assert row.sources.upside_to_target_live is None  # no live price → no upside


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
    assert row.artifact_count == 1
    assert row.research_count == 1
    # market side degraded, not fabricated
    assert row.price is None
    assert row.market_cap is None
    assert row.warnings  # outage surfaced
    assert ov.partial is True


async def test_overview_warnings_strip_internal_urls() -> None:
    class _LeakyDataLayer(_StubDataLayer):
        async def fetch_canonical(self, data_type, ticker, **_):
            raise ProviderError(
                "Client error '429 Too Many Requests' for url "
                "'https://financialmodelingprep.com/api/v3/quote/NVDA?apikey=secret'\n"
                "For more information check: https://developer.mozilla.org/"
            )

    store = _StubArtifactStore({"NVDA": [_summary(ticker="NVDA", verdict="HOLD")]})
    ov = await build_overview(
        _group("NVDA"),
        artifact_store=store,  # type: ignore[arg-type]
        data_layer=_LeakyDataLayer(),  # type: ignore[arg-type]
        now=NOW,
    )

    (row,) = ov.rows
    blob = " ".join(row.warnings)
    assert row.warnings
    assert "http" not in blob
    assert "apikey" not in blob
    assert "for url" not in blob
    assert "For more information" not in blob


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


class _StubRunStore:
    def __init__(self, by_ticker: dict[str, object]) -> None:
        self._by = {k.upper(): v for k, v in by_ticker.items()}

    async def latest_runs_by_ticker(self, tickers):
        return {t.upper(): self._by[t.upper()] for t in tickers if t.upper() in self._by}


async def test_overview_surfaces_failed_run_status() -> None:
    from finrobot.run_store import RunRecord

    rec = RunRecord(
        run_id="run_x",
        pipeline_type="dcf",
        ticker="NVDA",
        status="failed",
        created_at=NOW.isoformat(),
        error="provider down",
    )
    ov = await build_overview(
        _group("NVDA"),
        artifact_store=_StubArtifactStore({}),  # type: ignore[arg-type]
        data_layer=_StubDataLayer(),  # type: ignore[arg-type]
        run_store=_StubRunStore({"NVDA": rec}),  # type: ignore[arg-type]
        now=NOW,
    )
    (row,) = ov.rows
    assert row.run_status == "failed"
    assert row.run_error == "provider down"
    # run_failed precedes never_run even though the ticker has 0 artifacts.
    assert [r.kind for r in row.needs_refresh] == ["run_failed"]


async def test_overview_never_run_ticker() -> None:
    # In the group but never researched → 0 artifacts.
    ov = await build_overview(
        _group("TSLA"),
        artifact_store=_StubArtifactStore({}),  # type: ignore[arg-type]
        data_layer=_StubDataLayer(),  # type: ignore[arg-type]
        now=NOW,
    )
    (row,) = ov.rows
    assert row.artifact_count == 0
    assert row.research_count == 0
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
    # The Studied Tickers workspace already exists → the State-D backfill is a
    # no-op (it never undoes the user's existing universe).
    await store.get_or_create_system_group("Studied Tickers")
    art = _StubArtifactStore({"AAPL": [_summary()]})
    assert await ensure_system_group(store, art) is None  # type: ignore[arg-type]
    assert await store.count_groups() == 1  # nothing seeded


async def test_ensure_system_group_noop_without_studied_tickers(store: CoverageStore) -> None:
    assert await ensure_system_group(store, _StubArtifactStore({})) is None  # type: ignore[arg-type]
    assert await store.count_groups() == 0


# ── ensure_studied_membership (search auto-add) ──────────────────────────────


async def test_studied_membership_creates_group_on_first_open(store: CoverageStore) -> None:
    # Brand-new user, no groups at all → opening a ticker seeds the system group.
    detail = await ensure_studied_membership(store, "aapl")
    assert detail.is_system is True
    assert detail.name == "Studied Tickers"
    assert [m.ticker for m in detail.members] == ["AAPL"]  # upper-cased


async def test_studied_membership_is_idempotent(store: CoverageStore) -> None:
    await ensure_studied_membership(store, "AAPL")
    detail = await ensure_studied_membership(store, "AAPL")  # re-open → no dup
    assert [m.ticker for m in detail.members] == ["AAPL"]
    assert await store.count_groups() == 1


async def test_studied_membership_reuses_existing_system_group(store: CoverageStore) -> None:
    # State-D already seeded the system group; auto-add must target it, not
    # create a second one.
    seeded = await store.get_or_create_system_group("Studied Tickers")
    await store.add_members(seeded.id, ["MSFT"])
    detail = await ensure_studied_membership(store, "NVDA")
    assert detail.id == seeded.id
    assert sorted(m.ticker for m in detail.members) == ["MSFT", "NVDA"]
    # No second group spawned.
    assert await store.count_groups() == 1


# ── BUG-088: cold-start concurrent find-or-create must not duplicate ──────────


async def test_concurrent_cold_start_studied_membership_no_duplicate(
    store: CoverageStore,
) -> None:
    """Two concurrent first-opens (the cold-start race) must end with ONE
    system group containing BOTH tickers — never two duplicate 'Studied
    Tickers' groups with a ticker orphaned in the loser (BUG-088)."""
    import asyncio

    await asyncio.gather(
        ensure_studied_membership(store, "AAPL"),
        ensure_studied_membership(store, "MSFT"),
    )
    # Exactly one system group, and it holds both tickers (none orphaned).
    systems = [g for g in await store.list_groups() if g.is_system]
    assert len(systems) == 1
    canonical = await store.get_system_group()
    assert canonical is not None
    assert sorted(m.ticker for m in canonical.members) == ["AAPL", "MSFT"]
    assert await store.count_groups() == 1


async def test_partial_unique_index_blocks_second_system_group(
    store: CoverageStore,
) -> None:
    """The DB-level guarantee behind the race fix: a second is_system row is a
    no-op via ON CONFLICT, so get_or_create returns the original."""
    first = await store.get_or_create_system_group("Studied Tickers", "desc")
    second = await store.get_or_create_system_group("Studied Tickers", "desc")
    assert first.id == second.id
    systems = [g for g in await store.list_groups() if g.is_system]
    assert len(systems) == 1


async def test_get_or_create_system_group_finds_preexisting(
    store: CoverageStore,
) -> None:
    """If a system group already exists (e.g. State-D seed), get_or_create
    resolves to it rather than spawning a duplicate."""
    seeded = await store.get_or_create_system_group("Studied Tickers", "desc")
    await store.add_members(seeded.id, ["GOOG"])
    detail = await store.get_or_create_system_group("Studied Tickers", "desc")
    assert detail.id == seeded.id
    assert [m.ticker for m in detail.members] == ["GOOG"]


# ── calendar-aware refresh no-op (rate-limit shield) ──────────────────────────

FRI_CLOSE_TS = 1780689600  # 2026-06-05T20:00:00Z (Fri 16:00 ET) — latest settled close
MON_PREMARKET = datetime(2026, 6, 8, 8, 0, tzinfo=UTC)  # Mon 04:00 ET — market closed
MON_INSESSION = datetime(2026, 6, 8, 14, 30, tzinfo=UTC)  # Mon 10:30 ET — market open


def _price_at(ticker: str, as_of_ts: int, current: float = 200.0):
    """A canonical price whose ``as_of`` is pinned to ``as_of_ts`` (quote instant)."""
    return normalize_price(
        DataResult(
            data={
                "current_price": current,
                "price_history": [{"date": "2026-06-05", "close": current}],
                "quote_timestamp": as_of_ts,
            },
            provider="yfinance",
            ticker=ticker,
            data_type="price",
            timestamp=NOW,
        )
    )


class _CountingLayer:
    """Serves a Friday-close cached snapshot and records every provider fetch.

    ``cold`` tickers have no cached snapshot (read returns None) so the refresh
    path must fetch them — used to exercise the mixed no-op/fetch aggregation."""

    def __init__(self, *, as_of_ts: int = FRI_CLOSE_TS, cold: set[str] | None = None) -> None:
        self._as_of_ts = as_of_ts
        self._cold = {t.upper() for t in (cold or set())}
        self.fetch_calls: list[tuple[object, str]] = []

    async def read_canonical_cached(self, data_type, ticker, **_):
        if ticker.upper() in self._cold:
            return None
        if data_type == DataType.PRICE:
            return _price_at(ticker, self._as_of_ts), False
        return _fin(ticker), False

    async def fetch_canonical(self, data_type, ticker, **_):
        self.fetch_calls.append((data_type, ticker.upper()))
        if data_type == DataType.PRICE:
            return _price_at(ticker, self._as_of_ts)
        return _fin(ticker)


async def test_refresh_noop_when_closed_and_at_latest_close() -> None:
    """Closed market + cache already at the latest settled close → a refresh makes
    ZERO price provider calls, serves cache, and flags overview.refresh_noop."""
    layer = _CountingLayer()
    ov = await build_overview(
        _group("AAPL"),
        artifact_store=_StubArtifactStore({"AAPL": [_summary()]}),  # type: ignore[arg-type]
        data_layer=layer,  # type: ignore[arg-type]
        now=MON_PREMARKET,
    )
    assert ov.cache_only is False  # this is the network refresh path
    assert ov.refresh_noop is True
    assert (DataType.PRICE, "AAPL") not in layer.fetch_calls  # no price provider call
    (row,) = ov.rows
    assert row.price == 200.0  # served from the cached snapshot
    assert row.market_refresh_noop is True
    assert row.session_state == "closed"


async def test_refresh_fetches_when_market_live() -> None:
    """Mid-session a refresh must hit the provider (the price moves) → not a no-op."""
    layer = _CountingLayer()
    ov = await build_overview(
        _group("AAPL"),
        artifact_store=_StubArtifactStore({"AAPL": [_summary()]}),  # type: ignore[arg-type]
        data_layer=layer,  # type: ignore[arg-type]
        now=MON_INSESSION,
    )
    assert ov.refresh_noop is False
    assert (DataType.PRICE, "AAPL") in layer.fetch_calls  # provider WAS called


async def test_refresh_noop_false_when_any_row_was_fetched() -> None:
    """Mixed group: a closed-and-current row (no-op) + a cold row (must fetch) →
    refresh_noop is False; only the cold ticker hits the price provider."""

    layer = _CountingLayer(cold={"MSFT"})  # MSFT has no cache → must fetch
    ov = await build_overview(
        _group("AAPL", "MSFT"),
        artifact_store=_StubArtifactStore({}),  # type: ignore[arg-type]
        data_layer=layer,  # type: ignore[arg-type]
        now=MON_PREMARKET,
    )
    assert ov.refresh_noop is False
    assert (DataType.PRICE, "MSFT") in layer.fetch_calls  # cold ticker fetched
    assert (DataType.PRICE, "AAPL") not in layer.fetch_calls  # closed+current → no-op


def test_refresh_noop_not_serialized_per_row() -> None:
    """market_refresh_noop is an internal aggregation signal — never in the wire
    payload (the client reads the overview-level refresh_noop)."""
    dumped = CoverageRow(ticker="AAPL", market_refresh_noop=True).model_dump()
    assert "market_refresh_noop" not in dumped
