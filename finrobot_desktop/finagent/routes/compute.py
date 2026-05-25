from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter
from pydantic import BaseModel, Field
from starlette.requests import Request

from finagent.engine.compute.composite_score import (
    CompositeScore,
    ScoreRequest,
    calculate_composite_score,
)
from finagent.engine.compute.dcf import (
    calculate_dcf,
    calculate_sensitivity,
    solve_for_implied_growth,
    solve_for_implied_wacc,
)
from finagent.engine.compute.ddm import calculate_ddm
from finagent.engine.compute.lbo import calculate_lbo, calculate_lbo_sensitivity
from finagent.engine.compute.monte_carlo import (
    MonteCarloRequest,
    MonteCarloResult,
    run_monte_carlo,
)
from finagent.engine.compute.multiples import calculate_multiples, calculate_peer_statistics
from finagent.engine.compute.sniper import (
    SniperPoints,
    SniperRequest,
    calculate_sniper_points,
)
from finagent.engine.compute.wacc import calculate_wacc
from finagent.engine.models.financial import (
    CompanyFinancials,
    DCFInputs,
    DCFResult,
    DDMInputs,
    DDMResult,
    LBOInputs,
    LBOResult,
    PeerComps,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/compute", tags=["compute"])


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


class LboSensitivityRequest(BaseModel):
    inputs: LBOInputs
    entry_range: list[float] | None = None
    exit_range: list[float] | None = None


class LboSensitivityResult(BaseModel):
    entry_multiples: list[float]
    exit_multiples: list[float]
    irr_grid: list[list[float | None]]
    moic_grid: list[list[float | None]]


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

    Replaces the legacy hardcoded DEFAULT_COMPUTE_BODY shipped from the UI:
      1. fetch financials (LTM) + price + multi-year history
      2. seed_dcf_inputs → DCFInputs (with assumption_provenance per field)
      3. calculate_dcf + calculate_sensitivity
      4. solve_for_implied_growth + solve_for_implied_wacc (when include_reverse)

    Everything returned in a single bundled response so the UI doesn't need
    follow-up calls to render the valuation card.
    """
    from finagent.engine.compute.dcf_seed import seed_dcf_inputs
    from finagent.engine.compute.extractor import extract_financial_data
    from finagent.engine.compute.historical_extractor import extract_historical_from_yfinance
    from finagent.engine.data.types import DataType
    from finagent.engine.pipelines._helpers import build_sensitivity_ranges

    deps = request.app.state.deps
    ticker = body.ticker.upper()

    fin_result = await deps.data_layer.fetch(DataType.FINANCIALS, ticker)
    price_result = await deps.data_layer.fetch(DataType.PRICE, ticker)
    financial_data = extract_financial_data(fin_result, price_result)

    try:
        historical = await extract_historical_from_yfinance(ticker)
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
        from finagent.engine.models.financial import HistoricalMetrics

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


@router.post("/dcf-reverse", response_model=DcfReverseResult)
async def compute_dcf_reverse(request: DcfReverseRequest) -> DcfReverseResult:
    """Reverse DCF — given the current market price, solve for either the
    implied revenue growth rate or the implied discount rate.

    The standard DCF answers "is this stock fair?". Reverse DCF flips it:
    "what is the market actually assuming?". A retail investor can then judge
    whether those assumptions are plausible against history, sector base
    rates, or management guidance.

    Reference: Damodaran, "Investment Valuation", Ch. 13 — implied valuation.
    """
    if request.solve_for == "growth":
        result = solve_for_implied_growth(
            request.inputs,
            target_price=request.target_price,
            horizon_years=request.horizon_years,
            wacc_override=request.wacc_override,
            tg_override=request.tg_override,
            mid_year=request.mid_year,
        )
        return DcfReverseResult(
            solve_for="growth",
            target_price=request.target_price,
            implied_growth=result["implied_growth"],
            computed_price=result["computed_price"],
            wacc=result["wacc"],
            terminal_growth=result["terminal_growth"],
            horizon_years=result["horizon_years"],
            bracket=list(result["bracket"]),
            price_at_lo=result["price_at_lo"],
            price_at_hi=result["price_at_hi"],
            iterations=result["iterations"],
            message=result.get("message"),
        )

    # solve_for == "wacc"
    result = solve_for_implied_wacc(
        request.inputs,
        target_price=request.target_price,
        tg_override=request.tg_override,
        mid_year=request.mid_year,
    )
    return DcfReverseResult(
        solve_for="wacc",
        target_price=request.target_price,
        implied_wacc=result["implied_wacc"],
        computed_price=result["computed_price"],
        terminal_growth=result["terminal_growth"],
        horizon_years=result["horizon_years"],
        bracket=list(result["bracket"]),
        price_at_lo=result["price_at_lo"],
        price_at_hi=result["price_at_hi"],
        iterations=result["iterations"],
        message=result.get("message"),
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


@router.post("/ddm", response_model=DDMResult)
async def compute_ddm(inputs: DDMInputs) -> DDMResult:
    """Run DDM valuation for banks and dividend-paying stocks."""
    return calculate_ddm(inputs)


@router.post("/lbo", response_model=LBOResult)
async def compute_lbo(inputs: LBOInputs) -> LBOResult:
    return calculate_lbo(inputs)


@router.post("/lbo-sensitivity", response_model=LboSensitivityResult)
async def compute_lbo_sensitivity(
    request: LboSensitivityRequest,
) -> LboSensitivityResult:
    raw = calculate_lbo_sensitivity(
        request.inputs,
        entry_range=request.entry_range,
        exit_range=request.exit_range,
    )
    return LboSensitivityResult(**raw)


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
    from finagent.engine.compute.extractor import extract_financial_data
    from finagent.engine.compute.historical_extractor import extract_historical_from_yfinance
    from finagent.engine.compute.lbo_seed import seed_lbo_inputs
    from finagent.engine.data.types import DataType
    from finagent.engine.models.financial import HistoricalMetrics

    deps = request.app.state.deps
    ticker = body.ticker.upper()

    fin_result = await deps.data_layer.fetch(DataType.FINANCIALS, ticker)
    price_result = await deps.data_layer.fetch(DataType.PRICE, ticker)
    financial_data = extract_financial_data(fin_result, price_result)

    try:
        historical = await extract_historical_from_yfinance(ticker)
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


@router.post("/multiples", response_model=CompanyFinancials)
async def compute_multiples(company: CompanyFinancials) -> CompanyFinancials:
    return calculate_multiples(company)


@router.post("/peer-stats", response_model=PeerComps)
async def compute_peer_stats(comps: PeerComps) -> PeerComps:
    return calculate_peer_statistics(comps)


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
