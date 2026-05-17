from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter
from pydantic import BaseModel, Field
from starlette.requests import Request

from finagent.engine.compute.compare import (
    CompanyValuation,
    ComparisonResult,
    build_company_valuation,
)
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
    FinancialData,
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


class CompareRequest(BaseModel):
    """Request body for multi-company comparison."""

    tickers: list[str] = Field(min_length=2, max_length=10)


@router.post("/compare", response_model=ComparisonResult)
async def compare_companies(request_body: CompareRequest, request: Request) -> ComparisonResult:
    """Run DCF pipeline for each ticker and return side-by-side comparison.

    Fetches financials and runs the DCF pipeline concurrently for all tickers.
    Companies that fail (missing data, LLM error) are included with an error
    field set rather than failing the entire request.
    """
    from finagent.engine.pipelines.dcf import create_dcf_pipeline

    deps = request.app.state.deps
    sub_agents = request.app.state.sub_agents

    async def _run_one(ticker: str) -> CompanyValuation:
        """Run DCF pipeline for a single ticker, returning a CompanyValuation."""
        try:
            pipeline = create_dcf_pipeline(sub_agents)
            result = await pipeline.execute(deps, ticker)

            # Single pass: pick up DCFResult and FinancialData (supplementary metrics)
            dcf_result: DCFResult | None = None
            financials: FinancialData | None = None
            for value in result.structured_data.values():
                if dcf_result is None and isinstance(value, DCFResult):
                    dcf_result = value
                elif financials is None and isinstance(value, FinancialData):
                    financials = value
                if dcf_result is not None and financials is not None:
                    break

            if dcf_result is None:
                return CompanyValuation(
                    ticker=ticker, error="DCF pipeline completed but no DCFResult found"
                )

            return build_company_valuation(
                ticker=ticker,
                company_name=financials.company_name if financials else "",
                current_price=financials.market.current_price if financials else None,
                dcf_result=dcf_result,
                ev_ebitda=financials.valuation.ev_ebitda if financials else None,
                pe_ratio=financials.market.pe_ratio if financials else None,
                warnings=list(financials.warnings) if financials else [],
            )
        except (ValueError, RuntimeError, KeyError, TypeError) as e:
            logger.warning("Compare: %s failed: %s", ticker, e)
            return CompanyValuation(ticker=ticker, error=str(e)[:200])

    tasks = [_run_one(t.upper()) for t in request_body.tickers]
    companies = await asyncio.gather(*tasks)
    return ComparisonResult(companies=list(companies))


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
