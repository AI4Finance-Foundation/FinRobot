from __future__ import annotations

import asyncio

from fastapi import APIRouter
from pydantic import BaseModel, Field

from finagent.engine.compute.dcf import calculate_dcf, calculate_sensitivity
from finagent.engine.compute.lbo import calculate_lbo, calculate_lbo_sensitivity
from finagent.engine.compute.monte_carlo import (
    MonteCarloRequest,
    MonteCarloResult,
    run_monte_carlo,
)
from finagent.engine.compute.multiples import calculate_multiples, calculate_peer_statistics
from finagent.engine.compute.wacc import calculate_wacc
from finagent.engine.models.financial import (
    CompanyFinancials,
    DCFInputs,
    DCFResult,
    LBOInputs,
    LBOResult,
    PeerComps,
)

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
    )
