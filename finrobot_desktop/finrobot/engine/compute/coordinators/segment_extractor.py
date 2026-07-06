"""SOTP segment extractor — fetches SEC reportable segments and builds the floor.

Batch 3B (v1 floor + v2 caliber). The coordinator that owns the SOTP-floor data
I/O: it consumes ``DataLayer.fetch_segments`` (an explicit SEC augmentation route,
NOT the priority chain), maps each reportable segment onto a comparable EV/gross-
profit multiple, and hands the legs + market inputs to the pure
``compute_sotp_breakdown`` operator.

Layering (spec §8#5): segment extraction = coordinator (consumes DataLayer); the
arithmetic = pure operator (zero I/O). This module never touches XBRL parsing
(that's the provider) nor authors any forward assumption.

Floor multiples (the F2 caliber, v2 correction 2026-07-06):

  · ENERGY leg — a peer-derived median EV/gross-profit of the solar/storage comp
    set (Enphase / Fluence / SolarEdge). These are pure-plays with NO captive
    finance, so their EV/gross-profit is clean; the multiple is a peer-payload-
    VERIFIED calibration (see ``_ENERGY_MULTIPLE_SOURCE`` for the per-peer values +
    as-of). Computed on ANNUAL (latest-FY) gross profit to caliber-match TSLA's
    annual segment gross profit — NOT TTM: applying a TTM peer multiple to an
    annual segment metric would mix periods (T1). Point-in-time calibration.

  · AUTO leg — kept a CONSERVATIVE PROXY on purpose. Ex-captive-finance industrial
    EV/gross-profit is NOT computable from standardized financials: FMP consolidated
    balance sheets carry no auto-vs-captive-finance debt split, and ``netReceivables``
    is semantically inconsistent across peers (Ford's includes its finance book,
    GM's does not), so captive debt cannot be stripped without fabricating the split.
    The naive captive-INCLUSIVE peer EV/GP (~8.6× as of 2026-07-06) would RAISE the
    floor anti-conservatively, shrinking the honestly-large implied option residual
    an option-value name should show — so the low conservative proxy stays and the
    limitation is disclosed in ``multiple_source``. (Graveyard: comps-peers-recall
    2026-07-06.)

Using a growth multiple to force the residual into a sell-side through-2040 band
would fabricate the very forward optimism the floor forbids — the floor reports the
conservative cash-flow value and its (high) implied option share as the honest
decomposition.
"""

from __future__ import annotations

from datetime import datetime, timezone

from finrobot.engine.compute.operators.sotp import compute_sotp_breakdown, value_segment
from finrobot.engine.data.layer import DataLayer
from finrobot.engine.models.financial import SegmentValuation, SOTPBreakdown

# --- Energy floor multiple — solar/storage peer median EV/gross-profit ----------
# Peer set ENPH / FLNC / SEDG (captive-finance-free pure-plays). Per-peer annual
# EV/GP as of 2026-07-06 (EV = market_cap + total_debt − cash; GP = latest-FY gross
# profit): ENPH 9.4× · FLNC 9.6× · SEDG 16.9× → median 9.6×. Peer-payload verified;
# refresh the median (and the as-of below) when re-calibrating. ANNUAL caliber to
# match TSLA's annual segment gross profit (not TTM).
_ENERGY_EV_GROSS_PROFIT = 9.6
_ENERGY_MULTIPLE_SOURCE = (
    "solar/storage peer median EV/gross-profit 9.6× "
    "[ENPH 9.4× · FLNC 9.6× · SEDG 16.9×, annual FY2025 EV/GP] as-of 2026-07-06 "
    "(captive-finance-free, caliber-matched to annual segment GP)"
)

# --- Auto floor multiple — CONSERVATIVE PROXY by design (see module docstring) --
_AUTO_EV_GROSS_PROFIT = 6.0
_DEFAULT_EV_GROSS_PROFIT = 6.0  # unmatched segment → conservative auto-class proxy
_AUTO_SOURCE = (
    "auto OEM conservative proxy EV/gross-profit 6.0× — ex-captive-finance "
    "industrial multiple not computable from standardized financials (no "
    "auto-vs-finance debt split; netReceivables inconsistent across peers: Ford "
    "includes its finance book, GM does not); naive captive-inclusive peer EV/GP "
    "(~8.6×) would raise the floor anti-conservatively [金融待核 F2]"
)

# Normalized-member → (display name, multiple, source caliber).
_SEGMENT_MULTIPLES: dict[str, tuple[str, float, str]] = {
    "Automotive": ("Automotive", _AUTO_EV_GROSS_PROFIT, _AUTO_SOURCE),
    "EnergyGenerationAndStorage": (
        "Energy generation and storage",
        _ENERGY_EV_GROSS_PROFIT,
        _ENERGY_MULTIPLE_SOURCE,
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
    external sell-side SUCCESS-state ceiling (default None → floor +
    implied_option_pct only; a 12-month street target is NOT a robotaxi-success
    ceiling, so the caller leaves it None — see equity_research / valuation-
    synthesis-recall 2026-07-06).
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
        # currencies. Only USD reporters ship (TSLA); flag and drop otherwise.
        warnings.append(
            f"segment reporting currency {currency} != USD; SOTP floor needs FX "
            "normalization (not in scope) — dropping SOTP channel"
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
                "default conservative EV/gross-profit proxy 6.0× "
                "([金融待核 F2] no peer mapping)",
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
