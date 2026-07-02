from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator
from starlette.requests import Request

from finrobot.routes._ready import ensure_engine_ready

from finrobot.engine.compute.operators.dcf import (
    ReverseSolveReason,
    calculate_dcf,
    calculate_sensitivity,
    solve_for_implied_growth,
    solve_for_implied_horizon,
    solve_for_implied_wacc,
)
from finrobot.engine.compute.operators.lbo import calculate_lbo
from finrobot.engine.compute.operators.monte_carlo import (
    MonteCarloRequest,
    MonteCarloResult,
    run_monte_carlo,
)
from finrobot.engine.compute.operators.sniper import (
    SniperPoints,
    SniperRequest,
    calculate_sniper_points,
)
from finrobot.engine.compute.operators.wacc import calculate_wacc
from finrobot.engine.data.interface import ProviderError
from finrobot.engine.data.ticker import validate_ticker
from finrobot.engine.models.financial import (
    DCFInputs,
    DCFResult,
    FinancialData,
    LBOInputs,
    LBOResult,
)
from finrobot.warning_text import safe_error_text

if TYPE_CHECKING:
    from finrobot.engine.deps import FinRobotDeps

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/compute", tags=["compute"])


def _compute_http_error(exc: Exception, *, context: str | None = None) -> HTTPException:
    """Map a compute/data-layer exception to its HTTP status + 中文 detail.

    Mirrors ``routes/data.py::_data_http_error`` so the compute endpoints
    surface the same vocabulary the desktop UI already handles:

    - ProviderError → 502 (the seed routes fetch live data; upstream is down)
    - ValueError    → 422 (invalid inputs / degenerate model / unknown ticker)

    Without this the pure operators (and the seed routes' ``fetch_canonical``)
    were called bare, so an operator ``ValueError`` or a provider outage became
    an opaque 500. ``context`` is a short phrase (ticker or operation) for detail.
    """
    where = f" ({context})" if context else ""
    detail = safe_error_text(exc)
    if isinstance(exc, ProviderError):
        return HTTPException(
            status_code=502, detail=f"Data source temporarily unavailable{where}: {detail}"
        )
    return HTTPException(
        status_code=422, detail=f"Computation could not be completed{where}: {detail}"
    )


def apply_growth_scale_override(inputs: DCFInputs, scale: float | None) -> DCFInputs:
    """Scale all seeded revenue_growth_rates by ``1 + scale`` uniformly.

    The 'Revenue Growth Scale' override on /api/compute/dcf-seed.
    ``scale=None`` is the identity (no change);
    ``scale=0.1`` raises every year's growth by 10%; ``scale=-0.2`` cuts by
    20%. The DCFInputs is returned via ``model_copy`` so the seeded provenance
    dict is preserved unchanged.
    """
    if scale is None:
        return inputs
    factor = 1.0 + scale
    return inputs.model_copy(
        update={"revenue_growth_rates": [g * factor for g in inputs.revenue_growth_rates]}
    )


class WaccRequest(BaseModel):
    risk_free_rate: float = Field(ge=0, le=0.15)
    beta: float = Field(ge=0, le=5)
    equity_risk_premium: float = Field(ge=0, le=0.15)
    cost_of_debt: float = Field(ge=0, le=0.20)
    tax_rate: float = Field(ge=0, le=1)
    debt_ratio: float = Field(ge=0, le=1)


class WaccResponse(BaseModel):
    cost_of_equity: float
    wacc: float


DcfWaccAxis = Annotated[float, Field(ge=0, le=0.50, allow_inf_nan=False)]
DcfTerminalGrowthAxis = Annotated[float, Field(ge=-0.05, le=0.10, allow_inf_nan=False)]


class DcfSensitivityRequest(BaseModel):
    inputs: DCFInputs
    wacc_range: list[DcfWaccAxis] = Field(min_length=1, max_length=25)
    tg_range: list[DcfTerminalGrowthAxis] = Field(min_length=1, max_length=25)


class DcfSensitivityResult(BaseModel):
    wacc_values: list[float]
    tg_values: list[float]
    implied_prices: list[list[float | None]]


class DcfSeedRequest(BaseModel):
    """One-shot DCF seeded from a ticker — single authoritative entry point.

    Backend fetches financials + historical, calls ``seed_dcf_inputs`` to
    derive every assumption from real filings (or Damodaran industry fallback),
    then runs calculate_dcf + sensitivity + reverse DCF in one shot.
    """

    ticker: str = Field(min_length=1, max_length=12)
    wacc_override: float | None = Field(default=None, ge=0, le=0.50)
    tg_override: float | None = Field(default=None, ge=-0.05, le=0.10)
    growth_scale_override: float | None = Field(
        default=None,
        ge=-0.5,
        le=0.5,
        description=(
            "Multiplier applied uniformly to every seeded revenue_growth_rate. "
            "0.1 → +10% to each year's growth, -0.2 → -20%, None → unchanged."
        ),
    )
    mid_year: bool = False
    include_reverse: bool = True

    @field_validator("ticker")
    @classmethod
    def _validate_ticker(cls, value: str) -> str:
        return validate_ticker(value)


class DcfSeedResponse(BaseModel):
    """Bundled DCF output. inputs.assumption_provenance carries the per-field
    sources for the UI's "展开专家详情" tooltip."""

    inputs: DCFInputs
    result: DCFResult
    current_price: float | None = None
    reverse_growth: "DcfReverseResult | None" = None
    reverse_wacc: "DcfReverseResult | None" = None
    reverse_horizon: "DcfReverseResult | None" = None


class DcfReverseResult(BaseModel):
    solve_for: str
    target_price: float
    implied_growth: float | None = None
    implied_wacc: float | None = None
    implied_horizon: float | None = None
    # The growth rate held fixed when solve_for="horizon". Horizon and growth
    # trade off, so the implied horizon is a function of this assumed growth — the
    # UI MUST show it so the answer reads "under g=X%, ~N years", not a bare N.
    assumed_growth: float | None = None
    computed_price: float | None = None
    wacc: float | None = None
    terminal_growth: float
    horizon_years: int
    bracket: list[float]
    price_at_lo: float
    price_at_hi: float
    iterations: int
    # Whether the bisection bracket actually collapsed below tolerance. The
    # growth/wacc solvers emit it; without this field pydantic silently dropped
    # it from the response, so a caller couldn't tell an exact solve from a
    # capped approximation (BUG-035). Horizon solves omit it → default True.
    converged: bool = True
    # Structured outcome code (contract ①). Replaces the legacy human-readable
    # ``message`` f-string: the operators emit a machine code, the desktop panel
    # maps it to a localized sentence (bypassing the prose-through-the-API leak
    # where the old message rendered raw, skipping i18n). The growth/wacc solvers
    # omit a code on success; the horizon solver always emits one (SOLVED on the
    # happy path).
    reason_code: ReverseSolveReason | None = None


class LboSeedRequest(BaseModel):
    """One-shot LBO seeded from a ticker — single authoritative entry point.

    Backend fetches financials + historical, calls ``seed_lbo_inputs`` to
    derive every assumption from real filings (or Damodaran industry fallback /
    PE convention for deal-structure quantities), then runs calculate_lbo +
    sensitivity in one shot. Replaces the legacy front-end path that shipped
    14 hardcoded LBO parameters per ticker.
    """

    ticker: str = Field(min_length=1, max_length=12)
    holding_period_years: int | None = Field(default=None, ge=1, le=10)
    entry_ev_ebitda: float | None = Field(default=None, gt=0, le=30)
    exit_ev_ebitda: float | None = Field(default=None, gt=0, le=30)
    leverage_multiple: float | None = Field(default=None, ge=0, le=20)

    @field_validator("ticker")
    @classmethod
    def _validate_ticker(cls, value: str) -> str:
        return validate_ticker(value)


class LboSeedResponse(BaseModel):
    """Bundled LBO output. inputs.assumption_provenance carries the per-field
    sources for the UI's "展开专家详情" tooltip — mirrors DcfSeedResponse."""

    inputs: LBOInputs
    result: LBOResult
    current_price: float | None = None


@router.post("/wacc", response_model=WaccResponse)
async def compute_wacc(request: WaccRequest) -> WaccResponse:
    try:
        cost_of_equity, wacc = calculate_wacc(
            request.risk_free_rate,
            request.beta,
            request.equity_risk_premium,
            request.cost_of_debt,
            request.tax_rate,
            request.debt_ratio,
        )
    except ValueError as exc:
        raise _compute_http_error(exc, context="WACC") from exc
    return WaccResponse(cost_of_equity=cost_of_equity, wacc=wacc)


@router.post("/dcf", response_model=DCFResult, dependencies=[Depends(ensure_engine_ready)])
async def compute_dcf(inputs: DCFInputs) -> DCFResult:
    try:
        return calculate_dcf(inputs)
    except ValueError as exc:
        raise _compute_http_error(exc, context="DCF") from exc


async def _seed_dcf_inputs_for_ticker(
    deps: FinRobotDeps, ticker: str
) -> tuple[FinancialData, DCFInputs]:
    """Route-boundary adapter over the shared seed coordinator: maps the request
    ``deps`` to the ``(data_layer, fmp_api_key)`` the coordinator consumes.

    The fetch-and-seed logic now lives in
    ``engine/compute/coordinators/dcf_seed.py`` so the chat orchestrator's
    ``run_monte_carlo`` tool can reuse it without an engine→routes upward import.
    Still the single shared seed path for the dcf-seed and dcf-equivalence-line
    endpoints — they call this adapter unchanged.
    """
    from finrobot.engine.compute.coordinators.dcf_seed import seed_dcf_inputs_for_ticker

    return await seed_dcf_inputs_for_ticker(
        deps.data_layer, ticker, fmp_api_key=getattr(deps.settings, "fmp_api_key", None)
    )


@router.post(
    "/dcf-seed", response_model=DcfSeedResponse, dependencies=[Depends(ensure_engine_ready)]
)
async def compute_dcf_seed(body: DcfSeedRequest, request: Request) -> DcfSeedResponse:
    """One-shot DCF for a ticker — the front-end's single authoritative path.

    Replaces the legacy front-end hardcoded DCFInputs payload (removed in D1):
      1. fetch financials (LTM) + price + multi-year history
      2. seed_dcf_inputs → DCFInputs (with assumption_provenance per field)
      3. calculate_dcf + calculate_sensitivity
      4. solve_for_implied_growth + solve_for_implied_wacc (when include_reverse)

    Everything returned in a single bundled response so the UI doesn't need
    follow-up calls to render the valuation card.
    """
    from finrobot.engine.pipelines._helpers import build_sensitivity_ranges

    deps = request.app.state.deps
    ticker = body.ticker

    try:
        financial_data, dcf_inputs = await _seed_dcf_inputs_for_ticker(deps, ticker)
        dcf_inputs = apply_growth_scale_override(dcf_inputs, body.growth_scale_override)
        result = calculate_dcf(
            dcf_inputs,
            wacc_override=body.wacc_override,
            tg_override=body.tg_override,
            mid_year=body.mid_year,
        )
        wacc_range, tg_range = build_sensitivity_ranges(
            result.wacc, result.inputs.terminal_growth_rate
        )
        sensitivity = calculate_sensitivity(dcf_inputs, wacc_range, tg_range)
        result = result.model_copy(update={"sensitivity_table": sensitivity})

        current_price = financial_data.market.current_price
        reverse_growth: DcfReverseResult | None = None
        reverse_wacc: DcfReverseResult | None = None
        reverse_horizon: DcfReverseResult | None = None
        if body.include_reverse and current_price and current_price > 0:
            rg = solve_for_implied_growth(
                dcf_inputs,
                target_price=current_price,
                wacc_override=body.wacc_override,
                tg_override=body.tg_override,
                mid_year=body.mid_year,
            )
            reverse_growth = DcfReverseResult(solve_for="growth", **rg)
            rw = solve_for_implied_wacc(
                dcf_inputs,
                target_price=current_price,
                tg_override=body.tg_override,
                mid_year=body.mid_year,
            )
            reverse_wacc = DcfReverseResult(solve_for="wacc", **rw)
            # Horizon reverse needs a growth axis to hold fixed (it trades off
            # against horizon). Default to the seeded first-year growth; the
            # response echoes it as assumed_growth so the implied horizon is read
            # "under g=X%, ~N years".
            seeded_growth = (
                dcf_inputs.revenue_growth_rates[0]
                if dcf_inputs.revenue_growth_rates
                else dcf_inputs.terminal_growth_rate
            )
            rh = solve_for_implied_horizon(
                dcf_inputs,
                target_price=current_price,
                growth_rate=seeded_growth,
                wacc_override=body.wacc_override,
                tg_override=body.tg_override,
                mid_year=body.mid_year,
            )
            reverse_horizon = DcfReverseResult(solve_for="horizon", **rh)
    except (ValueError, ProviderError) as exc:
        raise _compute_http_error(exc, context=ticker) from exc

    return DcfSeedResponse(
        inputs=dcf_inputs,
        result=result,
        current_price=current_price,
        reverse_growth=reverse_growth,
        reverse_wacc=reverse_wacc,
        reverse_horizon=reverse_horizon,
    )


class DcfEquivalenceLineRequest(BaseModel):
    """Inputs for the (growth, horizon) equivalence line at a fixed WACC.

    Powers the 'market-implied expectations' reverse-DCF probe: for a fixed
    discount rate, every point on the line is a (constant growth, explicit-window
    length) pair that reprices the stock to ``target_price``. The line *is* the
    honest answer — the market price implies a family of (growth, horizon) combos,
    not one. The WACC slider re-requests this with a new ``wacc_override`` to shift
    the whole line (exposing the third axis).
    """

    ticker: str = Field(min_length=1, max_length=12)
    target_price: float | None = Field(
        default=None, gt=0, description="Defaults to current market price when omitted."
    )
    wacc_override: float | None = Field(
        default=None, ge=0, le=0.50, description="The fixed discount rate (slider value)."
    )
    tg_override: float | None = Field(default=None, ge=-0.05, le=0.10)
    growth_lo: float = Field(default=0.20, ge=-0.20, le=1.0)
    growth_hi: float = Field(default=0.50, ge=-0.20, le=1.5)
    steps: int = Field(default=13, ge=3, le=40)
    mid_year: bool = False

    @field_validator("ticker")
    @classmethod
    def _validate_ticker(cls, value: str) -> str:
        return validate_ticker(value)

    @model_validator(mode="after")
    def _validate_growth_bounds(self) -> DcfEquivalenceLineRequest:
        if self.growth_hi <= self.growth_lo:
            raise ValueError("growth_hi must be greater than growth_lo.")
        return self


class DcfEquivalencePoint(BaseModel):
    growth: float
    implied_horizon: float | None = None
    """None when target_price is unreachable at this growth within max horizon —
    the front end renders these as a gap, never as 0."""


class DcfEquivalenceLineResponse(BaseModel):
    """The equivalence line + the axes it holds fixed (the visible prefixes)."""

    ticker: str
    target_price: float
    wacc: float
    """The discount rate held fixed for the WHOLE line —换个 WACC 整条线平移."""
    terminal_growth: float
    points: list[DcfEquivalencePoint]


def build_equivalence_line(
    dcf_inputs: DCFInputs,
    target_price: float,
    *,
    wacc_override: float | None = None,
    tg_override: float | None = None,
    growth_lo: float = 0.20,
    growth_hi: float = 0.50,
    steps: int = 13,
    mid_year: bool = False,
) -> tuple[float, float, list[DcfEquivalencePoint]]:
    """Pure (growth → implied horizon) sweep at a fixed WACC.

    For each growth rate across [growth_lo, growth_hi], solve the explicit-window
    length that reprices to ``target_price``, holding the discount rate fixed.
    Returns ``(fixed_wacc, terminal_growth, points)``. Points whose target is
    unreachable at their growth carry ``implied_horizon=None``. No I/O, no LLM —
    unit-tested directly; the endpoint is a thin seed-and-wrap around it.
    """
    fixed_wacc: float | None = None
    terminal_growth = dcf_inputs.terminal_growth_rate
    points: list[DcfEquivalencePoint] = []
    step = (growth_hi - growth_lo) / (steps - 1) if steps > 1 else 0.0
    for i in range(steps):
        g = growth_lo + step * i
        rh = solve_for_implied_horizon(
            dcf_inputs,
            target_price=target_price,
            growth_rate=g,
            wacc_override=wacc_override,
            tg_override=tg_override,
            mid_year=mid_year,
        )
        # wacc / terminal_growth are constant across the loop; capture once.
        if fixed_wacc is None:
            fixed_wacc = float(rh["wacc"])
            terminal_growth = float(rh["terminal_growth"])
        points.append(DcfEquivalencePoint(growth=g, implied_horizon=rh["implied_horizon"]))
    return (fixed_wacc if fixed_wacc is not None else 0.0), terminal_growth, points


@router.post(
    "/dcf-equivalence-line",
    response_model=DcfEquivalenceLineResponse,
    dependencies=[Depends(ensure_engine_ready)],
)
async def compute_dcf_equivalence_line(
    body: DcfEquivalenceLineRequest, request: Request
) -> DcfEquivalenceLineResponse:
    """Trace the (growth → implied horizon) equivalence line at a fixed WACC.

    Pure deterministic solver loop — no LLM. Cheap enough to call on every
    WACC-slider drag (debounced client-side).
    """
    deps = request.app.state.deps
    ticker = body.ticker

    try:
        financial_data, dcf_inputs = await _seed_dcf_inputs_for_ticker(deps, ticker)
        target_price = body.target_price or financial_data.market.current_price

        wacc, terminal_growth, points = build_equivalence_line(
            dcf_inputs,
            target_price,
            wacc_override=body.wacc_override,
            tg_override=body.tg_override,
            growth_lo=body.growth_lo,
            growth_hi=body.growth_hi,
            steps=body.steps,
            mid_year=body.mid_year,
        )
    except (ValueError, ProviderError) as exc:
        raise _compute_http_error(exc, context=ticker) from exc
    return DcfEquivalenceLineResponse(
        ticker=ticker,
        target_price=target_price,
        wacc=wacc,
        terminal_growth=terminal_growth,
        points=points,
    )


@router.post("/dcf-sensitivity", response_model=DcfSensitivityResult)
async def compute_dcf_sensitivity(
    request: DcfSensitivityRequest,
) -> DcfSensitivityResult:
    try:
        raw = await asyncio.to_thread(
            calculate_sensitivity,
            request.inputs,
            request.wacc_range,
            request.tg_range,
        )
    except ValueError as exc:
        raise _compute_http_error(exc, context="DCF sensitivity") from exc
    return DcfSensitivityResult(**raw)


@router.post("/lbo", response_model=LBOResult)
async def compute_lbo(inputs: LBOInputs) -> LBOResult:
    try:
        return calculate_lbo(inputs)
    except ValueError as exc:
        raise _compute_http_error(exc, context=inputs.ticker) from exc


@router.post(
    "/lbo-seed", response_model=LboSeedResponse, dependencies=[Depends(ensure_engine_ready)]
)
async def compute_lbo_seed(body: LboSeedRequest, request: Request) -> LboSeedResponse:
    """One-shot LBO for a ticker — the front-end's single authoritative path.

    Replaces the legacy hardcoded LBO body shipped from the UI (14 parameters
    identical for every company). Structurally mirrors /dcf-seed:
      1. fetch financials (LTM) + price + multi-year history
      2. seed_lbo_inputs → LBOInputs (with assumption_provenance per field)
      3. calculate_lbo + calculate_lbo_sensitivity

    Everything returned in a single bundled response so the UI doesn't need
    follow-up calls to render the LBO panel.
    """
    from finrobot.engine.compute.coordinators.extractor import extract_financial_data
    from finrobot.engine.compute.coordinators.historical_extractor import fetch_historical_metrics
    from finrobot.engine.compute.operators.lbo_seed import seed_lbo_inputs
    from finrobot.engine.data.types import DataType
    from finrobot.engine.models.financial import HistoricalMetrics

    deps: FinRobotDeps = request.app.state.deps
    ticker = body.ticker

    try:
        _fin = await deps.data_layer.fetch_canonical(DataType.FINANCIALS, ticker)
        _price = await deps.data_layer.fetch_canonical(DataType.PRICE, ticker)
        financial_data = extract_financial_data(_fin, _price)
    except (ValueError, ProviderError) as exc:
        raise _compute_http_error(exc, context=ticker) from exc

    try:
        historical = await fetch_historical_metrics(deps.data_layer, ticker)
    except (ValueError, KeyError, TypeError, AttributeError, RuntimeError, OSError) as exc:
        logger.warning("Historical extraction failed for %s: %s", ticker, exc)
        historical = HistoricalMetrics(
            years=[],
            revenue=[],
            revenue_growth_yoy=[],
            cogs=[],
            gross_profit=[],
            gross_margin=[],
            sga=[],
            sga_ratio=[],
            ebitda=[],
            ebitda_margin=[],
            operating_income=[],
            operating_margin=[],
            net_income=[],
            eps=[],
            pe_ratio=[],
            cagr_revenue=None,
            ticker=ticker,
        )

    # Build the kwargs dict so we only pass overrides the caller actually set —
    # otherwise seed_lbo_inputs receives None and falls over its defaults.
    seed_kwargs: dict[str, float | int] = {}
    if body.holding_period_years is not None:
        seed_kwargs["holding_period_years"] = body.holding_period_years
    if body.entry_ev_ebitda is not None:
        seed_kwargs["entry_ev_ebitda"] = body.entry_ev_ebitda
    if body.exit_ev_ebitda is not None:
        seed_kwargs["exit_ev_ebitda"] = body.exit_ev_ebitda
    if body.leverage_multiple is not None:
        seed_kwargs["leverage_multiple"] = body.leverage_multiple

    try:
        lbo_inputs = seed_lbo_inputs(financial_data, historical, **seed_kwargs)  # type: ignore[arg-type]
        lbo_result = calculate_lbo(lbo_inputs)
    except (ValueError, ProviderError) as exc:
        raise _compute_http_error(exc, context=ticker) from exc

    return LboSeedResponse(
        inputs=lbo_inputs,
        result=lbo_result,
        current_price=financial_data.market.current_price,
    )


@router.post("/monte-carlo", response_model=MonteCarloResult)
async def compute_monte_carlo(request: MonteCarloRequest) -> MonteCarloResult:
    """Run Monte Carlo DCF simulation (CPU-bound, offloaded to thread)."""
    try:
        return await asyncio.to_thread(
            run_monte_carlo,
            inputs=request.inputs,
            current_price=request.current_price,
            n_simulations=request.n_simulations,
            n_bins=request.n_bins,
            revenue_growth_std=request.revenue_growth_std,
            ebitda_margin_std=request.ebitda_margin_std,
            wacc_std=request.wacc_std,
            terminal_growth_std=request.terminal_growth_std,
            seed=request.seed,
            mid_year=request.mid_year,
        )
    except ValueError as exc:
        raise _compute_http_error(exc, context="Monte Carlo") from exc


@router.post("/sniper", response_model=SniperPoints)
async def compute_sniper(body: SniperRequest) -> SniperPoints:
    """Compute deterministic entry/exit price levels from DCF target + price history.

    Returns ideal_buy, secondary_buy, stop_loss, take_profit, position_size_pct,
    support/resistance levels, and risk/reward ratio. All numbers trace to typed
    inputs — no LLM inference.
    """
    try:
        return calculate_sniper_points(body)
    except ValueError as exc:
        raise _compute_http_error(exc, context=body.ticker) from exc
