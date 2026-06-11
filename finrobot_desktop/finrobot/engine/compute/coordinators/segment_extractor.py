"""SOTP segment extractor — fetches SEC reportable segments and builds the floor.

Batch 3B v1. The coordinator that owns the SOTP-floor data I/O: it consumes
``DataLayer.fetch_segments`` (an explicit SEC augmentation route, NOT the priority
chain), maps each reportable segment onto a deterministic comparable multiple, and
hands the legs + market inputs to the pure ``compute_sotp_breakdown`` operator.

Layering (spec §8#5): segment extraction = coordinator (consumes DataLayer);
the arithmetic = pure operator (zero I/O). This module never touches XBRL parsing
(that's the provider) nor does it author any forward assumption (v1 = floor +
market-implied residual only).

Floor multiples (the F2 caliber): segment GROSS PROFIT × a conservative comparable
EV/gross-profit. These are conservative CURRENT-multiple proxies (traditional auto
OEM / storage-utility peers), NOT growth multiples — so the floor is a genuine
cash-flow floor and the implied option residual is honestly LARGE for an
option-value name. They are flagged ``[金融待核 F2]`` in the source string: a peer
payload probe (Ford/GM/Toyota EV/GP for auto; Enphase/Fluence/utility for energy)
should replace these proxies before any precise multiple claim ships. Using a
growth multiple to force the residual into BofA's through-2040 ~64% band would
fabricate the very forward optimism v1 forbids — so v1 reports the conservative
floor and its (high) implied option share as the honest decomposition.
"""

from __future__ import annotations

from datetime import datetime, timezone

from finrobot.engine.compute.operators.sotp import compute_sotp_breakdown, value_segment
from finrobot.engine.data.layer import DataLayer
from finrobot.engine.models.financial import SegmentValuation, SOTPBreakdown

# Conservative comparable EV/gross-profit multiples (F2 — proxy pending peer probe).
# Keyed by normalized segment member (see edgar_provider._normalize_segment_member).
# Auto: traditional OEM peers trade ~6-8x EV/EBIT; gross-profit basis is more
# conservative still. Energy/storage carries a higher comparable than legacy auto.
_AUTO_EV_GROSS_PROFIT = 6.0
_ENERGY_EV_GROSS_PROFIT = 10.0
_DEFAULT_EV_GROSS_PROFIT = 6.0  # unmatched segment → conservative auto-class proxy

# Normalized-member → (display name, multiple, source caliber).
_SEGMENT_MULTIPLES: dict[str, tuple[str, float, str]] = {
    "Automotive": (
        "Automotive",
        _AUTO_EV_GROSS_PROFIT,
        "auto OEM peer proxy EV/gross-profit (conservative; [金融待核 F2] pending peer probe)",
    ),
    "EnergyGenerationAndStorage": (
        "Energy generation and storage",
        _ENERGY_EV_GROSS_PROFIT,
        "storage/utility peer proxy EV/gross-profit (conservative; [金融待核 F2] pending peer probe)",
    ),
}

_MIN_REPORTABLE_SEGMENTS = 2


async def build_sotp_breakdown(
    data_layer: DataLayer,
    ticker: str,
    *,
    net_debt: float,
    shares_outstanding: float,
    current_price: float,
    option_ev_if_success: float | None = None,
    option_anchor_source: str | None = None,
) -> SOTPBreakdown | None:
    """Fetch SEC reportable segments and assemble the reverse-SOTP decomposition.

    Returns None (the caller drops the SOTP channel) when:
      · SEC is unwired / fetch fails (``fetch_segments`` → None),
      · fewer than two reportable segments with a valuation metric (single-segment
        issuer — SOTP degenerates to ordinary valuation),
      · shares / price are non-positive (no market residual to compute).

    The caller gates on ``classify_market_implied_nature().kind == "option_value"``
    BEFORE invoking this — so a non-option-value name never reaches SEC here.

    ``net_debt`` / ``shares_outstanding`` come from the name's own DCFInputs;
    ``current_price`` is the live price. ``option_ev_if_success`` is the optional
    external sell-side ceiling (v1 default None → floor + implied_option_pct only).
    """
    if shares_outstanding <= 0 or current_price <= 0:
        return None

    result = await data_layer.fetch_segments(ticker)
    if result is None:
        return None

    raw_segments = result.data.get("segments") or {}
    period = result.data.get("period") or {}
    accession = result.data.get("accession")
    currency = result.data.get("currency")
    as_of = datetime.now(tz=timezone.utc)

    warnings: list[str] = list(result.warnings)
    if currency and currency != "USD":
        # Floor multiples + market cap are USD; a non-USD reporter would mix
        # currencies. v1 only ships USD reporters (TSLA); flag and drop otherwise.
        warnings.append(
            f"segment reporting currency {currency} != USD; SOTP floor needs FX "
            "normalization (not in v1 scope) — dropping SOTP channel"
        )
        return None

    period_label = ""
    end = period.get("end") if isinstance(period, dict) else None
    if end:
        period_label = f"FY ending {end}"

    legs: list[SegmentValuation] = []
    for key, seg in raw_segments.items():
        metric = seg.get("gross_profit")
        if metric is None:
            warnings.append(f"segment {key!r}: no gross profit — cannot value, skipped")
            continue
        display, multiple, source = _SEGMENT_MULTIPLES.get(
            key,
            (
                seg.get("label") or key,
                _DEFAULT_EV_GROSS_PROFIT,
                "default conservative EV/gross-profit proxy ([金融待核 F2] no peer mapping)",
            ),
        )
        label = f"{period_label} segment gross profit".strip()
        legs.append(
            value_segment(
                name=display,
                metric_label=label or "segment gross profit",
                metric_value=float(metric),
                multiple=multiple,
                multiple_source=f"{source}" + (f" — 10-K {accession}" if accession else ""),
            )
        )

    if len(legs) < _MIN_REPORTABLE_SEGMENTS:
        # Single modelable segment → SOTP degenerates to ordinary valuation.
        return None

    return compute_sotp_breakdown(
        ticker=ticker,
        modelable_segments=legs,
        net_debt=net_debt,
        shares_outstanding=shares_outstanding,
        current_price=current_price,
        option_ev_if_success=option_ev_if_success,
        option_anchor_source=option_anchor_source,
        as_of=as_of,
        warnings=warnings,
    )
