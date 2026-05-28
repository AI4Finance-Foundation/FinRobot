from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter
from pydantic import BaseModel, Field
from starlette.requests import Request

from finrobot.engine.compute.composite_score import (
    CompositeScore,
    ScoreRequest,
    calculate_composite_score,
)
from finrobot.engine.compute.dcf import (
    calculate_dcf,
    calculate_sensitivity,
    solve_for_implied_growth,
    solve_for_implied_wacc,
)
from finrobot.engine.compute.lbo import calculate_lbo
from finrobot.engine.compute.monte_carlo import (
    MonteCarloRequest,
    MonteCarloResult,
    run_monte_carlo,
)
from finrobot.engine.compute.sniper import (
    SniperPoints,
    SniperRequest,
    calculate_sniper_points,
)
from finrobot.engine.compute.wacc import calculate_wacc
from finrobot.engine.models.financial import (
    DCFInputs,
    DCFResult,
    LBOInputs,
    LBOResult,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/compute", tags=["compute"])


def apply_growth_scale_override(inputs: DCFInputs, scale: float | None) -> DCFInputs:
    """Scale all seeded revenue_growth_rates by ``1 + scale`` uniformly.

    Used by /api/compute/dcf-seed when the What-if Editor's 'Revenue Growth
    Scale' slider is dragged. ``scale=None`` is the identity (no change);
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


class DcfSensitivityRequest(BaseModel):
    inputs: DCFInputs
    wacc_range: list[float] = Field(min_length=1)
    tg_range: list[float] = Field(min_length=1)


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

    ticker: str = Field(min_length=1, max_length=10)
    wacc_override: float | None = Field(default=None, ge=0, le=0.50)
    tg_override: float | None = Field(default=None, ge=-0.05, le=0.10)
    growth_scale_override: float | None = Field(
        default=None,
        ge=-0.5,
        le=0.5,
        description=(
            "Multiplier applied uniformly to every seeded revenue_growth_rate. "
            "0.1 → +10% to each year's growth, -0.2 → -20%, None → unchanged. "
            "Drives the What-if Editor's 'Revenue Growth Scale' slider."
        ),
    )
    mid_year: bool = False
    include_reverse: bool = True


class DcfSeedResponse(BaseModel):
    """Bundled DCF output. inputs.assumption_provenance carries the per-field
    sources for the UI's "展开专家详情" tooltip."""

    inputs: DCFInputs
    result: DCFResult
    current_price: float | None = None
    reverse_growth: "DcfReverseResult | None" = None
    reverse_wacc: "DcfReverseResult | None" = None


class DcfReverseRequest(BaseModel):
    """Reverse-DCF input: solve either for implied growth or implied WACC."""

    inputs: DCFInputs
    target_price: float = Field(gt=0)
    # Which axis to solve. "growth" finds the constant revenue growth rate that
    # justifies target_price; "wacc" finds the discount rate.
    solve_for: str = Field(default="growth", pattern="^(growth|wacc)$")
    horizon_years: int = Field(default=5, ge=1, le=15)
    wacc_override: float | None = Field(default=None, ge=0, le=0.50)
    tg_override: float | None = Field(default=None, ge=-0.05, le=0.10)
    mid_year: bool = False


class DcfReverseResult(BaseModel):
    solve_for: str
    target_price: float
    implied_growth: float | None = None
    implied_wacc: float | None = None
    computed_price: float | None = None
    wacc: float | None = None
    terminal_growth: float
    horizon_years: int
    bracket: list[float]
    price_at_lo: float
    price_at_hi: float
    iterations: int
    message: str | None = None


class LboSeedRequest(BaseModel):
    """One-shot LBO seeded from a ticker — single authoritative entry point.

    Backend fetches financials + historical, calls ``seed_lbo_inputs`` to
    derive every assumption from real filings (or Damodaran industry fallback /
    PE convention for deal-structure quantities), then runs calculate_lbo +
    sensitivity in one shot. Replaces the legacy front-end path that shipped
    14 hardcoded LBO parameters per ticker.
    """

    ticker: str = Field(min_length=1, max_length=10)
    holding_period_years: int | None = Field(default=None, ge=1, le=10)
    entry_ev_ebitda: float | None = Field(default=None, gt=0, le=30)
    exit_ev_ebitda: float | None = Field(default=None, gt=0, le=30)
    leverage_multiple: float | None = Field(default=None, ge=0, le=20)


class LboSeedResponse(BaseModel):
    """Bundled LBO output. inputs.assumption_provenance carries the per-field
    sources for the UI's "展开专家详情" tooltip — mirrors DcfSeedResponse."""

    inputs: LBOInputs
    result: LBOResult
    current_price: float | None = None


@router.post("/wacc", response_model=WaccResponse)
async def compute_wacc(request: WaccRequest) -> WaccResponse:
    cost_of_equity, wacc = calculate_wacc(
        request.risk_free_rate,
        request.beta,
        request.equity_risk_premium,
        request.cost_of_debt,
        request.tax_rate,
        request.debt_ratio,
    )
    return WaccResponse(cost_of_equity=cost_of_equity, wacc=wacc)


@router.post("/dcf", response_model=DCFResult)
async def compute_dcf(inputs: DCFInputs) -> DCFResult:
    return calculate_dcf(inputs)


@router.post("/dcf-seed", response_model=DcfSeedResponse)
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
    from finrobot.engine.compute.dcf_seed import seed_dcf_inputs
    from finrobot.engine.compute.extractor import extract_financial_data
    from finrobot.engine.compute.historical_extractor import extract_historical_metrics
    from finrobot.engine.data.types import DataType
    from finrobot.engine.pipelines._helpers import build_sensitivity_ranges

    deps = request.app.state.deps
    ticker = body.ticker.upper()

    fin_result = await deps.data_layer.fetch(DataType.FINANCIALS, ticker)
    price_result = await deps.data_layer.fetch(DataType.PRICE, ticker)
    financial_data = extract_financial_data(fin_result, price_result)

    try:
        historical = await extract_historical_metrics(deps.data_layer, ticker)
    except (
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        RuntimeError,
        OSError,
    ) as exc:
        # yfinance / provider variants can fail with a wide range of low-level
        # errors; we degrade gracefully to an empty HistoricalMetrics so
        # dcf_seed falls through to Damodaran industry medians.
        logger.warning("Historical extraction failed for %s: %s", ticker, exc)
        from finrobot.engine.models.financial import HistoricalMetrics

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

    dcf_inputs = seed_dcf_inputs(financial_data, historical)
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

    return DcfSeedResponse(
        inputs=dcf_inputs,
        result=result,
        current_price=current_price,
        reverse_growth=reverse_growth,
        reverse_wacc=reverse_wacc,
    )


@router.post("/dcf-sensitivity", response_model=DcfSensitivityResult)
async def compute_dcf_sensitivity(
    request: DcfSensitivityRequest,
) -> DcfSensitivityResult:
    raw = calculate_sensitivity(
        request.inputs,
        request.wacc_range,
        request.tg_range,
    )
    return DcfSensitivityResult(**raw)


@router.post("/lbo", response_model=LBOResult)
async def compute_lbo(inputs: LBOInputs) -> LBOResult:
    return calculate_lbo(inputs)


@router.post("/lbo-seed", response_model=LboSeedResponse)
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
    from finrobot.engine.compute.extractor import extract_financial_data
    from finrobot.engine.compute.historical_extractor import extract_historical_metrics
    from finrobot.engine.compute.lbo_seed import seed_lbo_inputs
    from finrobot.engine.data.types import DataType
    from finrobot.engine.models.financial import HistoricalMetrics

    deps = request.app.state.deps
    ticker = body.ticker.upper()

    fin_result = await deps.data_layer.fetch(DataType.FINANCIALS, ticker)
    price_result = await deps.data_layer.fetch(DataType.PRICE, ticker)
    financial_data = extract_financial_data(fin_result, price_result)

    try:
        historical = await extract_historical_metrics(deps.data_layer, ticker)
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

    lbo_inputs = seed_lbo_inputs(financial_data, historical, **seed_kwargs)  # type: ignore[arg-type]
    lbo_result = calculate_lbo(lbo_inputs)

    return LboSeedResponse(
        inputs=lbo_inputs,
        result=lbo_result,
        current_price=financial_data.market.current_price,
    )


@router.post("/monte-carlo", response_model=MonteCarloResult)
async def compute_monte_carlo(request: MonteCarloRequest) -> MonteCarloResult:
    """Run Monte Carlo DCF simulation (CPU-bound, offloaded to thread)."""
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
        mid_year=request.mid_year,
    )


@router.post("/sniper", response_model=SniperPoints)
async def compute_sniper(body: SniperRequest) -> SniperPoints:
    """Compute deterministic entry/exit price levels from DCF target + price history.

    Returns ideal_buy, secondary_buy, stop_loss, take_profit, position_size_pct,
    support/resistance levels, and risk/reward ratio. All numbers trace to typed
    inputs — no LLM inference.
    """
    return calculate_sniper_points(body)


@router.post("/score", response_model=CompositeScore)
async def compute_score(body: ScoreRequest) -> CompositeScore:
    """Compute a 0-100 composite score from fundamentals, valuation, catalysts, sentiment.

    Weights: fundamental 30%, valuation 30%, catalyst 20%, sentiment 20%.
    Signal: STRONG_BUY (>=80) / BUY (>=60) / HOLD (>=40) / SELL (>=20) / STRONG_SELL.
    All thresholds are hardcoded — no LLM reasoning.
    """
    return calculate_composite_score(body)
