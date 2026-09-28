"""Scenario SOTP — reverse-SOTP market-implied decomposition (pure operator).

Batch 3B v1. Mirrors the reverse-DCF range (``dcf.market_implied_check``):
instead of forecasting a point target — which for an option-value name would
require fabricating a robotaxi/FSD success probability (a banned intuition-driven
number) — this DECOMPOSES the live market cap into

  1. a deterministic cash-flow FLOOR  = Σ (modelable segment metric × comparable
     multiple) − net_debt, 100% sourceable to SEC-filed reportable segments; and
  2. the market-IMPLIED option value     = market_equity − equity_floor (pure
     subtraction), i.e. what the market assigns to robotaxi/FSD/Optimus above the
     cash-flow floor — reverse-derived from price, never authored by an LLM.

What this does that a raw LLM cannot: every number is reproducible from the same
inputs (segment facts + multiples + live price), and the option value is a pure
arithmetic residual of the price, not a narrated guess. This is the option-value
CHANNEL — it is consumed as ``structured_context["sotp_breakdown"]`` / a
football-field row, and is deliberately kept OUT of confidence-weighted point
synthesis so it never trips the method-corroboration span gate
(``METHOD_CORROBORATION_SPAN_K``) against the DCF floor.

ZERO I/O: segment extraction (SEC) lives in the coordinator
(``segment_extractor``); this module is arithmetic only.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

from finrobot.engine.models.financial import (
    SegmentValuation,
    SOTPBreakdown,
    SOTPScenarioBand,
)


def value_segment(
    *,
    name: str,
    metric_label: str,
    metric_value: float,
    multiple: float,
    multiple_source: str,
) -> SegmentValuation:
    """One segment's EV leg: ``implied_ev = metric_value × multiple`` (pure)."""
    return SegmentValuation(
        name=name,
        metric_label=metric_label,
        metric_value=metric_value,
        multiple=multiple,
        multiple_source=multiple_source,
        implied_ev=metric_value * multiple,
    )


def compute_sotp_breakdown(
    *,
    ticker: str,
    modelable_segments: list[SegmentValuation],
    net_debt: float,
    shares_outstanding: float,
    current_price: float,
    option_ev_if_success: float | None = None,
    option_anchor_source: str | None = None,
    scenario_band: SOTPScenarioBand | None = None,
    as_of: datetime | None = None,
    warnings: list[str] | None = None,
) -> SOTPBreakdown:
    """Assemble the reverse-SOTP decomposition from pre-extracted legs + market.

    Args:
      modelable_segments: cash-flow-modelable legs (Automotive / Energy …) with
        ``implied_ev`` already computed via :func:`value_segment`.
      net_debt: subtracted to bridge EV floor → equity floor (negative = net cash,
        added back).
      shares_outstanding / current_price: live market inputs for the residual.
      option_ev_if_success: OPTIONAL external sell-side SOTP success-state ceiling.
        When given (with a source string), the market-implied success probability
        = implied_option_ev / option_ev_if_success is surfaced. v1 default None —
        the floor + implied_option_pct legs are zero-anchor, the most robust.

    Raises ``ValueError`` on non-positive / non-finite market inputs (a div-by-zero
    floor or residual is a bug, not a degenerate-but-legal case — the caller must
    gate on a real quote and share count).
    """
    if not math.isfinite(shares_outstanding) or shares_outstanding <= 0:
        raise ValueError(
            f"SOTP needs positive shares_outstanding, got {shares_outstanding!r} for {ticker}"
        )
    if not math.isfinite(current_price) or current_price <= 0:
        raise ValueError(f"SOTP needs positive current_price, got {current_price!r} for {ticker}")
    warn = list(warnings or [])

    ev_floor = sum(s.implied_ev for s in modelable_segments)
    equity_floor = ev_floor - net_debt
    price_floor = equity_floor / shares_outstanding
    market_equity = current_price * shares_outstanding
    implied_option_ev = market_equity - equity_floor
    # market_equity > 0 (current_price>0, shares>0 enforced); safe divisor.
    implied_option_pct = implied_option_ev / market_equity

    floor_exceeds_market = equity_floor > market_equity
    if floor_exceeds_market:
        warn.append(
            "equity floor exceeds market cap — not an option-premium name; "
            "SOTP option decomposition does not apply (route to ordinary multi-method)."
        )

    implied_success_probability: float | None = None
    market_exceeds_success_ceiling = False
    if option_ev_if_success is not None and option_ev_if_success > 0:
        implied_success_probability = implied_option_ev / option_ev_if_success
        if implied_success_probability > 1:
            market_exceeds_success_ceiling = True
            warn.append(
                "market-implied option value exceeds even the full-success SOTP "
                "ceiling (implied success probability > 1) — stronger over-pricing "
                "signal than reverse-DCF unreachable."
            )

    return SOTPBreakdown(
        ticker=ticker,
        as_of=as_of or datetime.now(tz=timezone.utc),
        modelable_segments=modelable_segments,
        ev_floor=ev_floor,
        net_debt=net_debt,
        equity_floor=equity_floor,
        price_floor=price_floor,
        shares_outstanding=shares_outstanding,
        current_price=current_price,
        market_equity=market_equity,
        implied_option_ev=implied_option_ev,
        implied_option_pct=implied_option_pct,
        option_ev_if_success=option_ev_if_success,
        option_anchor_source=option_anchor_source,
        implied_success_probability=implied_success_probability,
        floor_exceeds_market=floor_exceeds_market,
        market_exceeds_success_ceiling=market_exceeds_success_ceiling,
        scenario_band=scenario_band,
        warnings=warn,
    )
