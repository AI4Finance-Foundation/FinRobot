"""Segment extractor — fetches SEC reportable segments and builds the SOTP floor
(+ a lightweight non-SOTP segment overview for ordinary tickers).

Batch 3B (v1 floor + v2 caliber). The coordinator that owns the SOTP-floor data
I/O: it consumes ``DataLayer.fetch_segments`` (an explicit SEC augmentation route,
NOT the priority chain), maps each reportable segment onto a comparable EV/gross-
profit multiple, and hands the legs + market inputs to the pure
``compute_sotp_breakdown`` operator.

BACKLOG A4 (2026-07-09) added ``build_segment_overview``: a DISPLAY-only sibling
for every ticker that is NOT an SOTP option-value candidate — no multiples, no
implied EV, no market residual, just the segment/product revenue mix for the
Company Overview chapter. It reuses the SAME ``fetch_segments`` XBRL route
(unchanged, still SOTP's primary source too) and falls back to FMP's product-
category breakdown only when XBRL has nothing. The SOTP gate in
``build_sotp_breakdown`` above is NOT touched by this addition.

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
from typing import Any

from finrobot.engine.compute.operators.sotp import compute_sotp_breakdown, value_segment
from finrobot.engine.compute.operators.sotp_scenario import compute_scenario_band
from finrobot.engine.data.interface import DataResult
from finrobot.engine.data.layer import DataLayer
from finrobot.engine.models.financial import (
    SegmentOverview,
    SegmentShare,
    SegmentValuation,
    SOTPBreakdown,
    SOTPScenarioBand,
)

# Standing caveat on every SegmentOverview: ASC 280 lets an issuer omit
# corporate/eliminations items from its segment table, so segment revenues can
# legitimately not sum exactly to consolidated total revenue. revenue_share is
# deliberately computed as a share of THIS breakdown's own segment total (never
# claimed to be a share of consolidated revenue) — this warning makes that
# explicit rather than letting a reader assume an exact reconciliation.
_SEGMENT_RECONCILIATION_CAVEAT = (
    "segment revenue shares are computed against the sum of segments shown here, "
    "not consolidated total revenue — corporate/eliminations items outside the "
    "reportable segments (if any) are not broken out"
)

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
                "default conservative EV/gross-profit proxy 6.0× ([金融待核 F2] no peer mapping)",
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

    # Slice ② — the robotaxi-SUCCESS ceiling stays None. A 12-month analyst target
    # is the wrong caliber for a full-success SOTP ceiling and no sourceable
    # robotaxi-success valuation exists, so the implied success probability is
    # WITHHELD with an explicit refusal (contract②: degrade + disclose, never
    # fabricate a mislabeled number). Street positioning lives in the SEPARATE
    # scenario band below (single-authority: two distinct semantics, two blocks).
    if option_ev_if_success is None:
        warnings.append(
            "implied robotaxi-success probability withheld: no sourceable "
            "full-success SOTP ceiling — a 12-month analyst target is a different "
            "caliber (street positioning, not a robotaxi-success valuation) "
            "[金融待核 F3]"
        )

    # Build the reverse-SOTP breakdown FIRST so the scenario band can anchor on its
    # cash-flow floor (a present value) beside the street cluster — C 4-point merge.
    breakdown = compute_sotp_breakdown(
        ticker=ticker,
        modelable_segments=legs,
        net_debt=net_debt,
        shares_outstanding=shares_outstanding,
        current_price=current_price,
        option_ev_if_success=option_ev_if_success,
        option_anchor_source=option_anchor_source,
        scenario_band=None,
        as_of=as_of,
        warnings=warnings,
    )

    # Slice ③ (C) — forward scenario band: the cash-flow FLOOR anchor (present value,
    # robotaxi-fails) + the 12-month STREET cluster (forward analyst targets), each
    # caliber distinct. range_position is the SAME-caliber street-range position;
    # NO floor→street cross-caliber ratio (compute_scenario_band's hard rule). Its
    # range_position is street positioning, NEVER a robotaxi-success probability.
    breakdown.scenario_band = await _build_scenario_band(
        data_layer, ticker, current_price, breakdown.price_floor, breakdown.warnings
    )
    return breakdown


async def _build_scenario_band(
    data_layer: DataLayer,
    ticker: str,
    current_price: float,
    cash_flow_floor: float,
    warnings: list[str],
) -> SOTPScenarioBand | None:
    """Fetch the 12-month analyst target distribution and build the scenario band.

    ``cash_flow_floor`` (the reverse-SOTP per-share floor, a PRESENT value) rides
    the band as an independent anchor beside the street cluster; the band exposes it
    + ``floor_coverage`` (floor/price) only, never a floor→street cross-caliber
    ratio (C hard rule). Returns None (band dropped; the reverse-SOTP floor still
    ships) when analyst targets are unavailable or the distribution is incomplete/
    degenerate — with a disclosure on ``warnings``. Never fabricates a bound.
    """
    pt = await data_layer.fetch_price_target(ticker)
    if pt is None:
        warnings.append("analyst price targets unavailable — forward street scenario band dropped")
        return None
    d = pt.data or {}
    count = d.get("analyst_count")
    source = (
        f"{d.get('source') or 'FMP analyst price targets'}"
        + (f" · {count} analysts (trailing year)" if count else "")
        + " · street-anchored 12-month target distribution [金融待核 F2]"
    )
    band = compute_scenario_band(
        bear=d.get("low"),
        base=d.get("consensus"),
        bull=d.get("high"),
        median=d.get("median"),
        current_price=current_price,
        analyst_count=count,
        source=source,
        cash_flow_floor=cash_flow_floor,
    )
    if band is None:
        warnings.append("analyst target distribution incomplete/degenerate — scenario band dropped")
    return band


# ---------------------------------------------------------------------------
# Lightweight segment overview (BACKLOG A4, 2026-07-09) — non-SOTP display path
# ---------------------------------------------------------------------------


def _num_or_none(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _segment_shares(
    rows: list[tuple[str, float | None, float | None, float | None]],
) -> list[SegmentShare]:
    """Build ``SegmentShare`` rows with revenue_share = revenue / Σ(revenue shown).

    ``rows`` is ``(name, revenue, gross_profit, operating_income)``. Rows are
    sorted by revenue descending (None-revenue rows last) so the largest segment
    reads first — a display convenience, not a data transform.
    """
    total_revenue = sum(r[1] for r in rows if r[1] is not None)
    shares: list[SegmentShare] = []
    for name, revenue, gross_profit, operating_income in rows:
        share = revenue / total_revenue if revenue is not None and total_revenue > 0 else None
        shares.append(
            SegmentShare(
                name=name,
                revenue=revenue,
                revenue_share=share,
                gross_profit=gross_profit,
                operating_income=operating_income,
            )
        )
    shares.sort(key=lambda s: (s.revenue is None, -(s.revenue or 0.0)))
    return shares


def _segment_overview_from_xbrl(ticker: str, result: DataResult) -> SegmentOverview | None:
    """Build a display-only overview from the SEC XBRL ``fetch_segments`` payload."""
    raw_segments: dict[str, dict[str, Any]] = result.data.get("segments") or {}
    if not raw_segments:
        return None
    period = result.data.get("period")
    end = period.get("end") if isinstance(period, dict) else None
    period_label = f"FY ending {end}" if end else "FY (period unresolved)"
    rows = [
        (
            str(seg.get("label") or key),
            _num_or_none(seg.get("revenue")),
            _num_or_none(seg.get("gross_profit")),
            _num_or_none(seg.get("operating_income")),
        )
        for key, seg in raw_segments.items()
    ]
    warnings = [*result.warnings, _SEGMENT_RECONCILIATION_CAVEAT]
    return SegmentOverview(
        ticker=ticker,
        as_of=datetime.now(tz=timezone.utc),
        source="sec_xbrl_business_segment",
        period_label=period_label,
        segments=_segment_shares(rows),
        warnings=warnings,
    )


async def build_segment_overview(data_layer: DataLayer, ticker: str) -> SegmentOverview | None:
    """Lightweight, display-only reportable-segment revenue mix, or None.

    For tickers that are NOT SOTP option-value candidates (the caller gates on
    that — see ``equity_research._execute_financial_modeling``). No valuation
    math: unlike ``build_sotp_breakdown``, this never touches
    ``compute_sotp_breakdown`` / multiples / implied EV — it exists purely to
    replace the "segment data unavailable" placeholder in the Company Overview
    chapter with a real (small, sourced) breakdown.

    SEC XBRL ONLY (BACKLOG A4, 2026-07-09): ``DataLayer.fetch_segments`` — the
    SAME route SOTP uses, unchanged; audited, GAAP-defined reportable segments.
    An FMP product-category fallback was tried and REMOVED the same day: FMP's
    payload is a different, unaudited PRODUCT taxonomy (not GAAP reportable
    segments) and was demonstrably unreliable (KO live: 2 truncated, mislabeled
    rows summing to ~79% of revenue). Presenting that as "segment revenue"
    misrepresents — 绝不让残缺/错标数据进 artifact (contract②: honest degrade,
    never fabricate).

    Returns None when XBRL has no cleanly-anchorable reportable-segment
    breakdown (single-segment issuer; SEC unwired; or the reportable segments
    collapse onto a non-uniquely-labelled axis, e.g. KO). The chapter then keeps
    its existing empty-state narrative gate; no fabricated panel.
    """
    xbrl_result = await data_layer.fetch_segments(ticker)
    if xbrl_result is not None:
        overview = _segment_overview_from_xbrl(ticker, xbrl_result)
        if overview is not None:
            return overview
    return None
