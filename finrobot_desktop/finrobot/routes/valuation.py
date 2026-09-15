"""Valuation aggregation endpoints (v5 §6.4 Football Field + §6.6 bands)."""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import date, datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from starlette.requests import Request

from finrobot.artifact.models import Artifact
from finrobot.artifact.store import ArtifactStore
from finrobot.engine.compute.coordinators.extractor import extract_financial_data
from finrobot.engine.compute.operators.forward_estimates import (
    ForwardFinancials,
    get_forward_financials,
)
from finrobot.engine.primitives.historical_valuation import HistoricalMetricName
from finrobot.engine.primitives.industry import is_balance_sheet_financial, is_commodity_cyclical
from finrobot.engine.compute.operators.multiples import current_ev_ebitda
from finrobot.engine.compute.operators.valuation_aggregator import aggregate_valuation
from finrobot.engine.data.cache import cached_fetch
from finrobot.engine.data.historical_loaders import (
    classify_band,
    compute_bands_via_data_layer,
    fetch_reverse_multiple_band,
)
from finrobot.engine.data.interface import ProviderError
from finrobot.engine.data.layer import DataLayer
from finrobot.engine.data.types import DataType
from finrobot.engine.models.financial import (
    DCFResult,
    DDMResult,
    FinancialData,
    LBOResult,
    PeerComps,
    ValuationAggregate,
)
from finrobot.routes._ready import ensure_engine_ready

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/valuation", tags=["valuation"])


@router.get(
    "/aggregate/{ticker}",
    response_model=ValuationAggregate,
    dependencies=[Depends(ensure_engine_ready)],
)
async def aggregate_for_ticker(ticker: str, request: Request) -> ValuationAggregate:
    """Build the Football Field payload for a ticker (v5 §6.4).

    Pulls the latest equity_research / dcf / ddm / lbo / comps artifacts the
    store has for the ticker and aggregates them via the pure aggregator.
    Missing artifact types simply drop out of the response with a warning.
    """
    store = _store(request)
    data_layer = _data_layer(request)

    ticker = ticker.upper()
    current_price = await _current_price(ticker, data_layer, fmp_api_key=_fmp_api_key(request))

    dcf, peer_comps, ddm, lbo = await _gather_latest_results(store, ticker)
    shares = _shares_outstanding(dcf, lbo)
    current_net_debt = _current_net_debt(dcf)
    forward = await _forward_financials(ticker, data_layer, fmp_api_key=_fmp_api_key(request))
    # Canonical FinancialData: industry/sector for the financial-sector (cash-flow
    # suppression) + cyclical gates, AND the EV/EBITDA TTM denominator (income.ebitda).
    # Was the path-split bug: this route never passed financial_sector, so a bank/insurer
    # got its category-error DCF/EV plotted here even though the report path suppressed
    # them — same ticker, two different football fields (2026-06-24).
    fd = await _financial_data(ticker, data_layer)
    industry = fd.market.industry if fd else None
    sector = fd.market.sector if fd else None
    as_of = datetime.now(tz=timezone.utc)

    # Self historical EV/EBITDA band (P25/P75) → revives the EV/EBITDA reverse row
    # (band × forward consensus EBITDA − current net debt). Previously hardcoded
    # None, so the row could never fire here even though the band is fully
    # computable (it powers /historical-bands). p_fcf stays None: forward_fcf is
    # always None (FMP /analyst-estimates has no FCF field), so band-wiring alone
    # can't honestly revive P/FCF — that needs a separate forward_fcf source.
    ev_band = await fetch_reverse_multiple_band(ticker, "ev_ebitda", data_layer)

    return aggregate_valuation(
        ticker=ticker,
        current_price=current_price,
        dcf=dcf,
        peer_comps=peer_comps,
        ddm=ddm,
        lbo=lbo,
        shares_outstanding=shares,
        current_net_debt=current_net_debt,
        forward_eps=forward.forward_eps,
        # EV/EBITDA denominator = canonical TTM operating EBITDA (income.ebitda), the
        # same caliber as the trailing band — a single-caliber re-rating anchor (batch2).
        # Decoupled from ``forward.forward_ebitda`` (still fetched+FX-scaled for the
        # forward provenance / logging bundle, but no longer the ev denominator): the ev
        # leg reads all inputs from one canonical snapshot, so no cross-currency mix and
        # the row shows for foreign issuers whose native forward EBITDA the guard abstained.
        ttm_ebitda=fd.income.ebitda if fd else None,
        forward_fcf=forward.forward_fcf,
        forward_fiscal_period=forward.fiscal_period,
        forward_confidence=forward.confidence,
        forward_source=forward.source,
        historical_ev_ebitda_band=(ev_band.p25, ev_band.p75) if ev_band else None,
        historical_ev_ebitda_sample_n=ev_band.sample_count if ev_band else None,
        historical_p_fcf_band=None,
        # Cyclical (P/B comps row) + financial-sector (cash-flow suppression) now use
        # the snapshot's real industry/sector — converged with the report path, no more
        # ticker-only cyclical or a missing financial_sector that let bank/insurer DCF
        # through on this route.
        cyclical=is_commodity_cyclical(industry=industry, sector=sector, ticker=ticker),
        financial_sector=is_balance_sheet_financial(industry, sector),
        as_of=as_of,
    )


async def _forward_financials(
    ticker: str, data_layer: DataLayer | None, *, fmp_api_key: str | None = None
) -> ForwardFinancials:
    """Resolve FY1 forward consensus via DataLayer → the red-line leaf.

    Fetches the canonical FORWARD_ESTIMATES snapshot (the hard single-source
    slot every DCF-seed entry shares) and hands its payload to
    ``get_forward_financials``, which owns FY1 selection and口径. When no
    FMP-capable provider is configured ``fetch_canonical`` raises ProviderError
    (caught here → ``payload=None``); the leaf then degrades to ``unavailable``
    (all None) so the aggregator hides the forward-multiple rows with a warning
    instead of inventing a number — matches the BACKLOG P0 acceptance criterion.

    FMP analyst-estimates are denominated in the issuer's REPORTING currency
    (TWD for TSM), but the aggregator multiplies forward EPS by a USD-normalized
    peer P/E and compares the result against a USD current price. So for a foreign
    issuer the forward EPS / EBITDA / FCF are converted to USD here, BEFORE the
    pure aggregator multiplies them — otherwise a USD multiple × TWD EPS prints a
    ~32x-inflated target (BUG-006). The reporting currency comes from the
    canonical FINANCIALS snapshot (the provider tag, taken at face value).
    """
    payload: dict[str, Any] | None = None
    if data_layer is not None:
        try:
            result = await data_layer.fetch_canonical(DataType.FORWARD_ESTIMATES, ticker)
        except (ProviderError, ValueError, KeyError) as exc:
            logger.info("forward estimates fetch failed for %s: %s", ticker, exc)
        else:
            payload = result.payload()

    # Currency-clean USD anchor for the leaf's FX-mismatch guard. The canonical
    # FINANCIALS snapshot is FX-normalized to USD, so its net_income is USD even
    # for an ADR whose /analyst-estimates payload is still native (TWD for UMC,
    # no currency field). Without the anchor the leaf can't tell a native-TWD
    # forward NI from a real one — _forward_to_usd alone is inert here because it
    # reads the post-normalization reporting_currency (already USD).
    trailing_ni_usd, trailing_rev_usd, trailing_eps_usd = await _trailing_usd_anchors(
        ticker, data_layer
    )
    forward = get_forward_financials(
        ticker=ticker,
        yf_info=None,
        fmp_analyst_estimates=payload,
        trailing_net_income_usd=trailing_ni_usd,
        trailing_revenue_usd=trailing_rev_usd,
        trailing_eps_usd=trailing_eps_usd,
    )
    forward = await _forward_to_usd(forward, ticker, data_layer, fmp_api_key=fmp_api_key)
    if forward.fiscal_period is not None:
        logger.info(
            "forward estimates %s: FY-end %s eps=%s ebitda=%s fcf=%s (confidence=%s)",
            ticker,
            forward.fiscal_period,
            forward.forward_eps,
            forward.forward_ebitda,
            forward.forward_fcf,
            forward.confidence,
        )
    return forward


async def _trailing_usd_anchors(
    ticker: str, data_layer: DataLayer | None
) -> tuple[float | None, float | None, float | None]:
    """Currency-clean trailing (net income, revenue, EPS) for the leaf's FX-mismatch guard.

    Reads ``net_income`` / ``revenue`` / ``shares_outstanding`` off the canonical
    FINANCIALS snapshot, which the data layer has already FX-normalized to USD
    (``_apply_canonical_fx``) — so all are USD anchors even for a foreign issuer.
    The EPS anchor = net income / shares (canonical shares are market-cap-consistent
    = per ADR); it covers the hole where FMP UNDER-reports ``netIncomeAvg`` (KOF)
    so the NI/revenue legs stay in-band while the native ``epsAvg`` still leaks.
    (None, None, None) on any fetch failure (the guard then stays inert, never
    fails the forward fetch over a missing anchor)."""
    if data_layer is None:
        return None, None, None
    try:
        fin = await data_layer.fetch_canonical(DataType.FINANCIALS, ticker)
    except (ProviderError, ValueError, KeyError) as exc:
        logger.info("forward guard: trailing anchor lookup failed for %s: %s", ticker, exc)
        return None, None, None
    ni = getattr(fin, "net_income", None)
    rev = getattr(fin, "revenue", None)
    shares = getattr(fin, "shares_outstanding", None)
    ni_f = float(ni) if isinstance(ni, (int, float)) else None
    eps = (
        ni_f / float(shares)
        if (ni_f is not None and ni_f > 0 and isinstance(shares, (int, float)) and shares > 0)
        else None
    )
    return (
        ni_f,
        float(rev) if isinstance(rev, (int, float)) else None,
        eps,
    )


async def _financial_data(ticker: str, data_layer: DataLayer | None) -> FinancialData | None:
    """The canonical FinancialData snapshot, for the aggregate route's gates AND the
    EV/EBITDA TTM denominator.

    Supplies industry/sector (financial-sector cash-flow suppression + cyclical gates)
    and ``income.ebitda`` (the batch2 EV/EBITDA denominator — current TTM operating
    EBITDA, canonical-currency, single-caliber with the trailing band). None on any
    failure → gates default off + the ev row hides (no fabricated denominator), never an
    error. Cache-hot: the snapshot was already fetched by the forward/anchor helpers."""
    if data_layer is None:
        return None
    try:
        fin = await data_layer.fetch_canonical(DataType.FINANCIALS, ticker)
        price = await data_layer.fetch_canonical(DataType.PRICE, ticker)
        return extract_financial_data(fin, price)
    except (ProviderError, ValueError, KeyError, TypeError) as exc:
        logger.info("aggregate: financial-data lookup failed for %s: %s", ticker, exc)
        return None


async def _forward_to_usd(
    forward: ForwardFinancials,
    ticker: str,
    data_layer: DataLayer | None,
    *,
    fmp_api_key: str | None = None,
) -> ForwardFinancials:
    """Convert reporting-currency forward EPS / EBITDA / FCF to USD.

    No-op when the issuer reports in USD (US issuers) or there is nothing to
    convert. The aggregator's forward path pairs a USD-normalized peer P/E with
    forward EPS and a USD current price, so the forward numbers MUST be USD too
    (BUG-006). EPS is per-share, EBITDA / FCF are absolute — all three are
    reporting-currency amounts, so a single reporting→USD rate applies to each.
    """
    has_value = (
        forward.forward_eps is not None
        or forward.forward_ebitda is not None
        or forward.forward_fcf is not None
    )
    if data_layer is None or not has_value:
        return forward

    try:
        fin = await data_layer.fetch_canonical(DataType.FINANCIALS, ticker)
    except (ProviderError, ValueError, KeyError) as exc:
        logger.info("forward FX: reporting currency lookup failed for %s: %s", ticker, exc)
        return forward

    reporting_ccy = getattr(fin, "reporting_currency", "USD").upper()
    if reporting_ccy == "USD":
        return forward

    # Lazy: fx pulls yfinance; kept off the cold-start import path (test_cold_import).
    from finrobot.engine.data.providers.fx import fetch_fx_rate_to_usd

    try:
        rate = await fetch_fx_rate_to_usd(reporting_ccy, fmp_api_key=fmp_api_key)
    except ProviderError as exc:
        # Can't get a rate — drop the un-convertible forward numbers rather than
        # multiply a TWD EPS by a USD P/E. The aggregator then hides those rows.
        logger.warning(
            "forward FX: no %s→USD rate for %s (%s) — dropping forward numbers",
            reporting_ccy,
            ticker,
            exc,
        )
        return replace(
            forward,
            forward_eps=None,
            forward_ebitda=None,
            forward_fcf=None,
            warnings=[
                *forward.warnings,
                f"forward FX {reporting_ccy}→USD 不可得 — forward 行降级隐藏",
            ],
        )

    return replace(
        forward,
        forward_eps=forward.forward_eps * rate if forward.forward_eps is not None else None,
        forward_ebitda=(
            forward.forward_ebitda * rate if forward.forward_ebitda is not None else None
        ),
        forward_fcf=forward.forward_fcf * rate if forward.forward_fcf is not None else None,
        source=f"{forward.source} · {reporting_ccy}→USD @ {rate:.5f}",
    )


def _store(request: Request) -> ArtifactStore:
    store: ArtifactStore | None = getattr(request.app.state, "artifact_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="Artifact store not initialised")
    return store


def _data_layer(request: Request) -> DataLayer | None:
    deps = getattr(request.app.state, "deps", None)
    return getattr(deps, "data_layer", None) if deps is not None else None


def _fmp_api_key(request: Request) -> str | None:
    """FMP key threaded to the FX layer as a fallback source for forward-EPS
    currency conversion (a yfinance rate-limit storm shouldn't strand the rate).
    """
    deps = getattr(request.app.state, "deps", None)
    settings = getattr(deps, "settings", None) if deps is not None else None
    return getattr(settings, "fmp_api_key", None) if settings is not None else None


async def _current_price(
    ticker: str, data_layer: DataLayer | None, *, fmp_api_key: str | None = None
) -> float | None:
    """The live price in USD — the basis the football-field valuation methods sit on.

    The canonical PRICE snapshot is NEVER FX-normalized (the FX gate is
    FINANCIALS-only — see ``DataLayer._apply_canonical_fx``), so for a foreign LOCAL
    listing (quote=TWD) ``current_price`` is in the quote currency. The aggregator
    compares it against USD DCF/comps/DDM/LBO valuations, so it MUST be converted to
    USD first — the price-side mirror of the forward-EPS fix (``_forward_to_usd``).
    No-op for USD quotes (US issuers, pure ADRs). On an FX miss the price is dropped
    (None) rather than fed cross-currency into the field.
    """
    if data_layer is None:
        return None
    try:
        result = await data_layer.fetch_canonical(DataType.PRICE, ticker)
    except (ProviderError, ValueError, KeyError) as exc:
        logger.info("current_price fetch failed for %s: %s", ticker, exc)
        return None
    try:
        price = float(result.current_price) if result.current_price is not None else None
    except (TypeError, ValueError):
        return None
    if not price or price <= 0:
        return None
    quote_ccy = getattr(result, "quote_currency", "USD").upper()
    if quote_ccy == "USD":
        return price
    # Lazy: fx pulls yfinance; kept off the cold-start import path (test_cold_import).
    from finrobot.engine.data.providers.fx import fetch_fx_rate_to_usd

    try:
        rate = await fetch_fx_rate_to_usd(quote_ccy, fmp_api_key=fmp_api_key)
    except ProviderError as exc:
        # Can't put the price on the USD valuation basis — drop it rather than
        # compare a quote-currency price against USD methods.
        logger.warning(
            "current_price FX: no %s→USD rate for %s (%s) — dropping current price",
            quote_ccy,
            ticker,
            exc,
        )
        return None
    return price * rate


async def _gather_latest_results(
    store: ArtifactStore, ticker: str
) -> tuple[DCFResult | None, PeerComps | None, DDMResult | None, LBOResult | None]:
    """Load the most recent artifact of each pipeline type and parse its result."""
    summaries = await store.list_by_ticker(ticker=ticker, include_archived=True, limit=200)
    latest_by_type: dict[str, Artifact] = {}
    for summary in summaries:
        if summary.type in latest_by_type:
            continue
        artifact = await store.get(summary.id)
        if artifact is not None:
            latest_by_type.setdefault(summary.type, artifact)

    dcf = _parse_dcf(latest_by_type)
    peer_comps = _parse_peers(latest_by_type)
    ddm = _parse_ddm(latest_by_type)
    lbo = _parse_lbo(latest_by_type)
    return dcf, peer_comps, ddm, lbo


def _parse_dcf(latest: dict[str, Artifact]) -> DCFResult | None:
    artifact = latest.get("dcf") or latest.get("equity_research") or latest.get("ic_memo")
    if artifact is None:
        return None
    structured = artifact.outputs.structured
    # equity_research nests DCF under `financial_modeling`; ic_memo under
    # `dcf_result`; a plain dcf artifact dumps DCFResult FLAT at the top of
    # structured (no `dcf_calc` nest — that key only ever named the pipeline STEP,
    # so the old `dcf_calc` lookup silently dropped every plain-dcf DCFResult).
    # Try the nests first, then the flat top-level.
    for candidate in (
        structured.get("financial_modeling"),
        structured.get("dcf_result"),
        structured,
    ):
        if isinstance(candidate, dict):
            try:
                return DCFResult.model_validate(candidate)
            except (TypeError, ValueError) as exc:
                logger.debug("DCFResult parse failed: %s", exc)
                continue
    return None


def _parse_peers(latest: dict[str, Artifact]) -> PeerComps | None:
    artifact = latest.get("comps") or latest.get("equity_research")
    if artifact is None:
        return None
    structured = artifact.outputs.structured
    for key in ("statistical_bench", "peer_analysis"):
        candidate = structured.get(key)
        if isinstance(candidate, dict):
            try:
                return PeerComps.model_validate(candidate)
            except (TypeError, ValueError) as exc:
                logger.debug("PeerComps parse failed at %s: %s", key, exc)
                continue
    return None


def _parse_ddm(latest: dict[str, Artifact]) -> DDMResult | None:
    artifact = latest.get("ddm")
    if artifact is None:
        return None
    # build_ddm_artifact dumps DDMResult FLAT at the top of structured — there is
    # no `ddm_calc` nest (that key only ever named the pipeline STEP), so the old
    # `structured.get("ddm_calc")` matched nothing and every DDM method silently
    # dropped out of the valuation reconstruction / football field.
    try:
        return DDMResult.model_validate(artifact.outputs.structured)
    except (TypeError, ValueError) as exc:
        logger.debug("DDMResult parse failed: %s", exc)
        return None


def _parse_lbo(latest: dict[str, Artifact]) -> LBOResult | None:
    artifact = latest.get("lbo") or latest.get("ic_memo")
    if artifact is None:
        return None
    structured = artifact.outputs.structured
    # Standalone build_lbo_artifact dumps LBOResult FLAT at the top level;
    # IC memo stores it under lbo_result, and older route fixtures used
    # lbo_calculation. Accept all real producer shapes, validated by Pydantic.
    for candidate in (
        structured.get("lbo_calculation"),
        structured.get("lbo_result"),
        structured,
    ):
        if isinstance(candidate, dict):
            try:
                return LBOResult.model_validate(candidate)
            except (TypeError, ValueError) as exc:
                logger.debug("LBOResult parse failed: %s", exc)
                continue
    return None


def _shares_outstanding(dcf: DCFResult | None, lbo: LBOResult | None) -> float | None:
    """Best-effort shares lookup from whichever artifact carries it.

    DCFInputs.shares_outstanding is the cleanest source. LBO doesn't carry it
    natively, so DCF wins. Future enhancement: pull from FinancialData snapshot.
    """
    if dcf is not None and dcf.inputs.shares_outstanding > 0:
        return dcf.inputs.shares_outstanding
    _ = lbo  # reserved for future shares-from-LBO fallback when LBOInputs grows the field
    return None


def _current_net_debt(dcf: DCFResult | None) -> float | None:
    """Current net debt (total_debt − cash) for the EV/EBITDA equity bridge.

    DCFInputs.net_debt is computed by dcf_seed as ``total_debt − total_cash`` —
    the same current-period口径 the bridge requires (and the same source the DCF
    own EV→equity bridge subtracts). It is the only net-debt figure this endpoint
    carries without an extra balance-sheet fetch; when no DCF artifact exists the
    EV/EBITDA row stays hidden rather than assuming zero debt. EV/EBITDA must
    never borrow LBO ending_debt (a future, post-paydown figure at exit).
    """
    if dcf is not None:
        return dcf.inputs.net_debt
    return None


async def _current_ev_ebitda_override(
    ticker: str, data_layer: DataLayer, metric: HistoricalMetricName
) -> float | None:
    """Canonical TTM current EV/EBITDA for the standalone bands' current point.

    W1-C2: without this the route let the band fall back to the trailing-ANNUAL
    samples[-1] multiple, so the same ticker could read "极贵" here (annual) while
    the report's comps/technical chapters call it "合理" (TTM) — a signal flip on
    one metric. We compute the SAME authoritative ``current_ev_ebitda`` the
    report consumes (EV = market_cap + net_debt, ÷ TTM EBITDA) off the canonical
    FINANCIALS snapshot and hand it in as ``current_override``.

    Only ``ev_ebitda`` has an EV/EBITDA override — ``p_fcf`` gets None. Degrades
    to None (→ trailing-annual current, which the leaf discloses) when the
    canonical snapshot or its net-debt legs are unavailable; net_debt needs BOTH
    total_debt and total_cash present (None ≠ 0 — never fabricate EV from an
    assumed-zero balance).
    """
    if metric != "ev_ebitda":
        return None
    try:
        fin = await data_layer.fetch_canonical(DataType.FINANCIALS, ticker)
        price = await data_layer.fetch_canonical(DataType.PRICE, ticker)
    except (ProviderError, ValueError, KeyError) as exc:
        logger.info(
            "current EV/EBITDA override: canonical snapshot unavailable for %s: %s", ticker, exc
        )
        return None
    # fetch_canonical(FINANCIALS) returns a NormalizedFinancials, not a
    # FinancialData — the previous `isinstance(fin, FinancialData)` guard was
    # therefore always False, leaving the override permanently None and the band
    # silently back on the trailing-ANNUAL samples[-1] caliber (the very W1-C2
    # flip this override exists to close). Project the canonical snapshot through
    # the same extractor the /financials route uses, then read the TTM legs.
    financial_data = extract_financial_data(fin, price)
    balance = financial_data.balance
    total_debt = balance.total_debt
    total_cash = balance.total_cash
    if total_debt is None or total_cash is None:
        return None
    return current_ev_ebitda(financial_data, float(total_debt) - float(total_cash))


async def _is_balance_sheet_financial_ticker(ticker: str, data_layer: DataLayer) -> bool:
    """True when the issuer is a deposit/float-funded financial (bank / insurer) whose
    EV-based multiples are category errors. Reads industry off the canonical FINANCIALS
    snapshot (NormalizedFinancials carries industry/sector). Best-effort: a provider
    hiccup → False, so a transient outage computes the band rather than hiding it."""
    try:
        fin = await data_layer.fetch_canonical(DataType.FINANCIALS, ticker)
    except (ProviderError, ValueError, KeyError):
        return False
    return is_balance_sheet_financial(industry=fin.industry, sector=fin.sector)


# ---------------------------------------------------------------------------
# v5 §6.6 historical valuation bands
# ---------------------------------------------------------------------------


class HistoricalBandTimelinePoint(BaseModel):
    date: date
    value: float


class HistoricalBandResponse(BaseModel):
    """``GET /api/valuation/historical-bands/{ticker}`` payload (v5 §6.6)."""

    ticker: str
    metric: HistoricalMetricName
    current: float | None
    median: float | None
    p25: float | None
    p75: float | None
    p90: float | None
    timeline: list[HistoricalBandTimelinePoint]
    sample_count: int
    classification: Literal["expensive", "fair", "cheap", "unknown"] = Field(
        description="UI hint: current vs p75/p90 (spec §6.6)"
    )
    warnings: list[str] = Field(default_factory=list)


@router.get(
    "/historical-bands/{ticker}",
    response_model=HistoricalBandResponse,
    dependencies=[Depends(ensure_engine_ready)],
)
async def historical_bands(
    ticker: str,
    request: Request,
    metric: HistoricalMetricName = Query("ev_ebitda"),
    years: int = Query(3, ge=1, le=10),
) -> HistoricalBandResponse:
    """Build EV/EBITDA or P/FCF time series + current vs P25/P75/P90 (v5 §6.6).

    Cached 12h via DataType.HISTORICAL_BANDS so the price + financial fan-out
    only runs once per half-day per ticker / metric combo.
    """
    data_layer = _data_layer(request)
    if data_layer is None:
        raise HTTPException(status_code=503, detail="DataLayer not initialised")

    ticker = ticker.upper()

    # Balance-sheet financials (banks / insurers): the EV/EBITDA band is a category
    # error — EV nets deposits/float as if they were capital structure and there is
    # no clean above-the-line EBITDA, so classifying JPM "expensive" against a 3.3×
    # multiple is meaningless. The report + standalone comps already suppress EV/EBITDA
    # for these issuers (is_balance_sheet_financial, the single authority); this band
    # endpoint is the matching surface the suppression missed. Return an empty band so
    # the frontend ValuationBandCard hides itself (it requires a finite current). Only
    # ev_ebitda is suppressed — a p_fcf band stays valid. (2026-06-26)
    if metric == "ev_ebitda" and await _is_balance_sheet_financial_ticker(ticker, data_layer):
        return HistoricalBandResponse(
            ticker=ticker,
            metric=metric,
            current=None,
            median=None,
            p25=None,
            p75=None,
            p90=None,
            timeline=[],
            sample_count=0,
            classification="unknown",
        )

    async def _build() -> dict[str, Any]:
        override = await _current_ev_ebitda_override(ticker, data_layer, metric)
        band = await compute_bands_via_data_layer(
            ticker, metric, years, data_layer, current_override=override
        )
        classification = classify_band(band)
        payload = HistoricalBandResponse(
            ticker=ticker,
            metric=band.metric,
            current=band.current,
            median=band.median,
            p25=band.p25,
            p75=band.p75,
            p90=band.p90,
            timeline=[HistoricalBandTimelinePoint(date=d, value=v) for d, v in band.timeline],
            sample_count=band.sample_count,
            classification=classification,
            warnings=band.warnings,
        )
        return payload.model_dump(mode="json")

    raw = await cached_fetch(
        data_layer.cache,
        DataType.HISTORICAL_BANDS,
        ticker,
        _build,
        cache_key_suffix=f":{metric}:{years}",
        # Don't cache a transient empty band (steady-state provider outage → all-None
        # percentiles, sample_count 0): caching it would serve the empty result for the
        # full 12h TTL after the outage clears (non-self-healing). Only a band with real
        # samples earns the long TTL; an empty one is re-fetched next request → self-heals.
        # _build never raises (returns the empty band), so the route stays 200, not 500.
        # Bug-4, 2026-06-24.
        should_cache=lambda r: isinstance(r, dict) and r.get("sample_count", 0) > 0,
    )
    return HistoricalBandResponse.model_validate(raw)
