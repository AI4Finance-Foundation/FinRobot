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
from dataclasses import replace
from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from finrobot.engine.primitives.historical_valuation import HistoricalBand
from finrobot.engine.compute.operators.monte_carlo import (
    MonteCarloResult,
    deterministic_seed,
    run_monte_carlo,
)
from finrobot.engine.compute.operators.sniper import (
    SniperPoints,
    SniperRequest,
    calculate_sniper_levels_only,
    calculate_sniper_points,
)
from finrobot.engine.data.historical_loaders import (
    REPORT_BAND_WINDOW_YEARS,
    BandClassification,
    classify_band,
    compute_bands_via_data_layer,
    load_price_history,
)
from finrobot.engine.data.layer import DataLayer
from finrobot.engine.models.financial import DCFInputs

logger = logging.getLogger(__name__)


# Sentinel warning emitted when the equity_research technical_analysis step is
# skipped because the upstream DCF degraded gracefully (no DCFResult to seed the
# quant overlays). Lives on the model's module so both the producer
# (equity_research._execute_technical_analysis) and the validator
# (pipelines.validators.validate_technical_analysis) reference one constant and
# can never drift. An all-None TechnicalAnalysis carrying this marker is an
# honest, expected degrade — the validator PASSES on it.
TECHNICAL_DCF_UNAVAILABLE_MARKER = "technical_analysis skipped: DCF not applicable (no DCFResult)"


# Default Monte Carlo budget. 10K antithetic simulations finish in ~10ms and
# are dense enough for a stable 5/95 percentile estimate (Glasserman §4.1).
_MC_SIMULATIONS = 10_000


class HistoricalBandSnapshot(BaseModel):
    """JSON-friendly mirror of primitives.historical_valuation.HistoricalBand.

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
    window_years: int | None = Field(
        default=None,
        description=(
            "Trailing window (years) the percentiles were computed over — the "
            "report's REPORT_BAND_WINDOW_YEARS. Lets the front end label the band "
            "(e.g. '5y') and, with the valuation-method band on the same window, "
            "makes it explicit the two bands are one window. None on artifacts "
            "written before this field existed."
        ),
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
        description=(
            "Trailing EV/EBITDA timeline (REPORT_BAND_WINDOW_YEARS window, carried "
            "on the snapshot's window_years) + cheap/fair/expensive classifier."
        ),
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
    band_years: int = REPORT_BAND_WINDOW_YEARS,
    *,
    has_anchor_target: bool = True,
    current_ev_ebitda: float | None = None,
    price_fx_to_usd: float = 1.0,
) -> TechnicalAnalysis:
    """Run MC + Sniper + Bands and assemble the payload.

    All three branches are best-effort: each catches its own failure and
    records a warning so the artifact stays partial-but-honest rather than
    failing the whole research pipeline.

    Args:
        has_anchor_target: ``not valuation_synthesis.valuation_withheld`` — when
            False the synthesis honestly withheld its POINT target, so there is
            no publishable price target to anchor a directional trade on and the
            sniper drops to levels-only (B1: a LONG/SHORT keyed to a withheld
            target is self-contradictory). When a target publishes (even low
            confidence), the sniper anchors it.
        current_ev_ebitda: canonical TTM EV/EBITDA (matches the comps chapter:
            ``(market_cap + net_debt) / TTM_EBITDA``). Used as the band's
            *current* point so the report never shows two different "current
            EV/EBITDA" (B2). None → band falls back to trailing-annual EBITDA.
        price_fx_to_usd: quote→USD spot factor for the raw price history this
            function re-fetches (``load_price_history`` returns native quote-
            currency closes). ``current_price`` and ``dcf_target`` arrive already
            USD-normalized; without scaling the history the sniper would build
            support/resistance off native-ccy closes (e.g. TWD ~1000) while
            comparing them to a USD ``current_price`` (~31) — the second leg of
            BUG-073 caliber drift. 1.0 (default) for USD-quoted issuers → no-op.
            The EV/EBITDA band is a dimensionless ratio and currency-cancels
            per year, so it is NOT scaled.
    """
    warnings: list[str] = []

    monte_carlo = _safe_monte_carlo(ticker, dcf_inputs, current_price, warnings)
    prices = await load_price_history(ticker, data_layer, years=1)
    if price_fx_to_usd != 1.0:
        prices = [replace(p, close=p.close * price_fx_to_usd) for p in prices]
    sniper = _safe_sniper(
        ticker, current_price, dcf_target, prices, warnings, has_anchor_target=has_anchor_target
    )
    historical_bands = await _safe_historical_bands(
        ticker, data_layer, band_years, warnings, current_ev_ebitda=current_ev_ebitda
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
    ticker: str, dcf_inputs: DCFInputs, current_price: float, warnings: list[str]
) -> MonteCarloResult | None:
    if current_price <= 0:
        warnings.append("monte_carlo skipped: current_price unavailable")
        return None
    try:
        # Deterministic seed (crc32 of ticker + UTC day): rerunning the same
        # report on the same day reproduces the exact MC band; the seed lands
        # in assumptions_used so the artifact stays traceable.
        return run_monte_carlo(
            inputs=dcf_inputs,
            current_price=current_price,
            n_simulations=_MC_SIMULATIONS,
            seed=deterministic_seed(ticker),
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
    *,
    has_anchor_target: bool = True,
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
        if not has_anchor_target:
            # B1: the valuation synthesis honestly withheld its POINT target (the
            # only number available would be fabricated). With no publishable
            # target there is nothing to anchor a directional LONG/SHORT on — a
            # trade keyed to the withheld DCF leg would contradict the withholding,
            # the very inconsistency this gate prevents. Emit levels-only
            # (support/resistance, no trade).
            warnings.append(
                "sniper directional trade withheld: no publishable price target "
                "to anchor — only support/resistance shown."
            )
            return calculate_sniper_levels_only(request)
        return calculate_sniper_points(request)
    except (ValueError, ArithmeticError) as exc:
        logger.warning("Sniper failed for %s: %s", ticker, exc)
        warnings.append(f"sniper failed: {exc}")
        return None


async def _safe_historical_bands(
    ticker: str,
    data_layer: DataLayer,
    years: int,
    warnings: list[str],
    *,
    current_ev_ebitda: float | None = None,
) -> HistoricalBandSnapshot | None:
    try:
        band = await compute_bands_via_data_layer(
            ticker, "ev_ebitda", years, data_layer, current_override=current_ev_ebitda
        )
    except (ValueError, RuntimeError) as exc:
        logger.warning("Historical bands failed for %s: %s", ticker, exc)
        warnings.append(f"historical_bands failed: {exc}")
        return None
    if band.sample_count == 0:
        if band.warnings:
            warnings.extend(band.warnings)
        else:
            warnings.append("historical_bands skipped: no valid samples")
        return None
    return _snapshot_from_band(band, window_years=years)


def _snapshot_from_band(band: HistoricalBand, *, window_years: int) -> HistoricalBandSnapshot:
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
        window_years=window_years,
        warnings=list(band.warnings),
    )


def _iso(d: date) -> str:
    return d.isoformat()
