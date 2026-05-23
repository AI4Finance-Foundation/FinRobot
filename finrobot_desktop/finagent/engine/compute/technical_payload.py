"""Aggregate technical-analysis payload — Monte Carlo + Sniper + Bands.

This module is the deterministic glue for chapter 09 of the equity_research
artifact. It runs three independent compute leaves over the seeded DCF
inputs / current price / historical pricing, then packages them into a
single pydantic model the artifact builder can persist and the front end
can render without further math.

Why a single payload (not three separate structured keys):
  - The chapter renders them together (one section, three sub-cards).
  - One pipeline step means one error-recovery surface — partial failures
    degrade to None on individual fields instead of breaking the artifact.
  - The artifact diff view stays readable when an analyst compares two
    timestamps of the same ticker (one ``technical_analysis`` blob).
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from finagent.engine.compute.historical_valuation import HistoricalBand
from finagent.engine.compute.monte_carlo import MonteCarloResult, run_monte_carlo
from finagent.engine.compute.sniper import (
    SniperPoints,
    SniperRequest,
    calculate_sniper_points,
)
from finagent.engine.data.historical_loaders import (
    BandClassification,
    classify_band,
    compute_bands_via_data_layer,
    load_price_history,
)
from finagent.engine.data.layer import DataLayer
from finagent.engine.models.financial import DCFInputs

logger = logging.getLogger(__name__)


# Default Monte Carlo budget. 10K antithetic simulations finish in ~10ms and
# are dense enough for a stable 5/95 percentile estimate (Glasserman §4.1).
_MC_SIMULATIONS = 10_000


class HistoricalBandSnapshot(BaseModel):
    """JSON-friendly mirror of compute.historical_valuation.HistoricalBand.

    The compute layer returns a frozen dataclass with `date` objects in the
    timeline; pydantic + the React side want ISO strings, so we flatten here.
    """

    model_config = ConfigDict(frozen=True)

    metric: str
    current: float | None
    median: float | None
    p25: float | None
    p75: float | None
    p90: float | None
    timeline: list[tuple[str, float]] = Field(
        description="(ISO date, multiple) pairs, oldest first, ≤120 points."
    )
    sample_count: int
    classification: BandClassification = Field(
        description="UI hint: current vs p75/p90 (spec §6.6)."
    )
    warnings: list[str] = Field(default_factory=list)


class TechnicalAnalysis(BaseModel):
    """Chapter 09 payload — three quant overlays for the equity research report.

    All three fields are optional so a partial failure (e.g. no price history
    for sniper) still produces a usable artifact instead of aborting the run.
    """

    monte_carlo: MonteCarloResult | None = Field(
        default=None,
        description="10K-sim DCF distribution, percentiles, histogram bins.",
    )
    sniper: SniperPoints | None = Field(
        default=None,
        description="Deterministic buy/stop/target levels from DCF + 20d window.",
    )
    historical_bands: HistoricalBandSnapshot | None = Field(
        default=None,
        description="3-year EV/EBITDA timeline + cheap/fair/expensive classifier.",
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="Module-level skip reasons (e.g. 'sniper skipped: no price history').",
    )


async def build_technical_analysis(
    ticker: str,
    dcf_inputs: DCFInputs,
    dcf_target: float,
    current_price: float,
    data_layer: DataLayer,
    band_years: int = 3,
) -> TechnicalAnalysis:
    """Run MC + Sniper + Bands and assemble the payload.

    All three branches are best-effort: each catches its own failure and
    records a warning so the artifact stays partial-but-honest rather than
    failing the whole research pipeline.
    """
    warnings: list[str] = []

    monte_carlo = _safe_monte_carlo(dcf_inputs, current_price, warnings)
    prices = await load_price_history(ticker, data_layer, years=1)
    sniper = _safe_sniper(ticker, current_price, dcf_target, prices, warnings)
    historical_bands = await _safe_historical_bands(
        ticker, data_layer, band_years, warnings
    )

    return TechnicalAnalysis(
        monte_carlo=monte_carlo,
        sniper=sniper,
        historical_bands=historical_bands,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# branch helpers — each returns None + appends to warnings on failure
# ---------------------------------------------------------------------------


def _safe_monte_carlo(
    dcf_inputs: DCFInputs, current_price: float, warnings: list[str]
) -> MonteCarloResult | None:
    if current_price <= 0:
        warnings.append("monte_carlo skipped: current_price unavailable")
        return None
    try:
        return run_monte_carlo(
            inputs=dcf_inputs,
            current_price=current_price,
            n_simulations=_MC_SIMULATIONS,
        )
    except (ValueError, ArithmeticError, RuntimeError) as exc:
        logger.warning("Monte Carlo failed for %s: %s", dcf_inputs, exc)
        warnings.append(f"monte_carlo failed: {exc}")
        return None


def _safe_sniper(
    ticker: str,
    current_price: float,
    dcf_target: float,
    prices: list[Any],
    warnings: list[str],
) -> SniperPoints | None:
    if current_price <= 0 or dcf_target <= 0:
        warnings.append("sniper skipped: missing current_price or dcf_target")
        return None
    if not prices:
        warnings.append("sniper skipped: no historical price data")
        return None
    try:
        request = SniperRequest(
            ticker=ticker,
            current_price=current_price,
            dcf_target=dcf_target,
            historical_prices=[p.close for p in prices],
        )
        return calculate_sniper_points(request)
    except (ValueError, ArithmeticError) as exc:
        logger.warning("Sniper failed for %s: %s", ticker, exc)
        warnings.append(f"sniper failed: {exc}")
        return None


async def _safe_historical_bands(
    ticker: str, data_layer: DataLayer, years: int, warnings: list[str]
) -> HistoricalBandSnapshot | None:
    try:
        band = await compute_bands_via_data_layer(ticker, "ev_ebitda", years, data_layer)
    except (ValueError, RuntimeError) as exc:
        logger.warning("Historical bands failed for %s: %s", ticker, exc)
        warnings.append(f"historical_bands failed: {exc}")
        return None
    if band.sample_count == 0:
        warnings.append("historical_bands skipped: no valid samples")
        return None
    return _snapshot_from_band(band)


def _snapshot_from_band(band: HistoricalBand) -> HistoricalBandSnapshot:
    return HistoricalBandSnapshot(
        metric=band.metric,
        current=band.current,
        median=band.median,
        p25=band.p25,
        p75=band.p75,
        p90=band.p90,
        timeline=[(_iso(d), v) for d, v in band.timeline],
        sample_count=band.sample_count,
        classification=classify_band(band),
        warnings=list(band.warnings),
    )


def _iso(d: date) -> str:
    return d.isoformat()
