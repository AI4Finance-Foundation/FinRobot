"""Aggregate target-price ranges across 4 valuation methods + 2 multiple reverses.

Powers ``GET /api/valuation/aggregate/{ticker}`` (the Football Field section in
v5 §6.4). Pure leaf-layer: takes already-fetched pipeline artifacts plus a few
numeric inputs, returns ``ValuationAggregate``. No provider SDKs, no LLM, no
upper-layer imports.

The hardest correctness rule is §6.4.2: **never re-run a full LBO sweep here.**
We reuse the entry × exit IRR/MOIC grid the LBO pipeline already saved on
``LBOResult.sensitivity`` and post-process it into a target-price band via a
single 5×5 division loop. Running ``calculate_lbo`` once per (entry, exit) cell
would 25× the cost of the endpoint with zero accuracy benefit.

EV/EBITDA and P/FCF rows are *multiple* methods — they reverse-engineer a
band from the company's own 3-year multiple distribution (P25/P75) times a
forward profit number. Forward profit now comes from FMP analyst estimates
(compute/forward_estimates.py); the historical-band input (PR3) is still
unwired at the aggregate route, so the multiple rows stay omitted with a
warning until that lands — the UI surfaces "降级显示 4 行 valuation, 2 行
multiple 未就绪".
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from finrobot.engine.models.financial import (
    DCFResult,
    DDMResult,
    LBOResult,
    PeerComps,
    ValuationAggregate,
    ValuationMethodRange,
)

_DCF_BAND_WIDTH = 0.20
"""Default ±20% band around DCFResult.implied_price when monte carlo is absent.

The DCF pipeline today does not persist a P10–P90 monte-carlo range on
DCFResult, so we approximate the implied band with the same ±20% rule used
historically by build_valuation_synthesis. When monte carlo lands the
``low`` / ``high`` come from real P10 / P90 percentiles.
"""

_DDM_BAND_WIDTH = 0.15
"""Tighter band for DDM — dividend streams are less volatile than FCF."""

_COMPS_PE_BAND_WIDTH = 0.10
"""±1 std proxy when peer-PE std isn't recorded (PeerComps lacks std today)."""


def aggregate_valuation(
    *,
    ticker: str,
    current_price: float | None,
    dcf: DCFResult | None = None,
    peer_comps: PeerComps | None = None,
    ddm: DDMResult | None = None,
    lbo: LBOResult | None = None,
    shares_outstanding: float | None = None,
    forward_eps: float | None = None,
    forward_ebitda: float | None = None,
    forward_fcf: float | None = None,
    historical_ev_ebitda_band: tuple[float, float] | None = None,
    historical_p_fcf_band: tuple[float, float] | None = None,
    as_of: datetime | None = None,
) -> ValuationAggregate:
    """Build the Football Field payload for one ticker.

    Each artifact / number is optional. Missing methods drop out silently with
    a one-line warning. Caller (route layer) is responsible for fetching the
    inputs via DataLayer / ArtifactStore and assembling them.
    """
    methods: list[ValuationMethodRange] = []
    warnings: list[str] = []

    if (m := _dcf_method(dcf)) is not None:
        methods.append(m)
    elif dcf is None:
        warnings.append("dcf: 无 DCF artifact — 跑 AI 完整研报后此行展示")

    if (m := _comps_pe_method(peer_comps, forward_eps, shares_outstanding)) is not None:
        methods.append(m)
    elif peer_comps is None:
        warnings.append("comps_pe: 无 peer_analysis artifact — 跑 AI 完整研报后此行展示")
    elif forward_eps is None:
        warnings.append(
            "comps_pe: forward EPS 不可得（无 FMP analyst-estimates 数据 / 未配置 FMP key）— "
            "降级使用 trailing EPS"
        )

    if (m := _ddm_method(ddm)) is not None:
        methods.append(m)

    if (m := _lbo_method(lbo, shares_outstanding)) is not None:
        methods.append(m)
    elif lbo is not None and shares_outstanding is None:
        warnings.append("lbo: 缺少 shares_outstanding — 目标价反推被跳过")

    if (
        m := _ev_ebitda_method(forward_ebitda, historical_ev_ebitda_band, shares_outstanding, lbo)
    ) is not None:
        methods.append(m)
    else:
        warnings.append(
            "ev_ebitda: 历史估值带(PR3 未接) 或 forward EBITDA 不可得 — multiple 行降级隐藏"
        )

    if (m := _p_fcf_method(forward_fcf, historical_p_fcf_band, shares_outstanding)) is not None:
        methods.append(m)
    else:
        warnings.append("p_fcf: 历史估值带(PR3 未接) 或 forward FCF 不可得 — multiple 行降级隐藏")

    return ValuationAggregate(
        ticker=ticker.upper(),
        current_price=current_price,
        as_of=as_of if as_of is not None else datetime.now(tz=timezone.utc),
        methods=methods,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Per-method extractors
# ---------------------------------------------------------------------------


def _dcf_method(dcf: DCFResult | None) -> ValuationMethodRange | None:
    if dcf is None or dcf.implied_price <= 0:
        return None
    mid = dcf.implied_price
    p10, p90, source = _dcf_band(dcf, mid)
    return ValuationMethodRange(
        method="dcf",
        method_type="valuation",
        low=p10,
        mid=mid,
        high=p90,
        confidence=0.85,
        source=source,
    )


def _dcf_band(dcf: DCFResult, mid: float) -> tuple[float, float, str]:
    """Prefer monte-carlo P10/P90 when present; fall back to ±20% band."""
    sensitivity = dcf.sensitivity_table or {}
    p10 = sensitivity.get("p10") if isinstance(sensitivity, dict) else None
    p90 = sensitivity.get("p90") if isinstance(sensitivity, dict) else None
    if isinstance(p10, (int, float)) and isinstance(p90, (int, float)) and p10 > 0 and p90 > 0:
        return float(p10), float(p90), "monte_carlo_p10_p90"
    return mid * (1 - _DCF_BAND_WIDTH), mid * (1 + _DCF_BAND_WIDTH), "implied_price ± 20%"


def _comps_pe_method(
    peer_comps: PeerComps | None,
    forward_eps: float | None,
    shares_outstanding: float | None,
) -> ValuationMethodRange | None:
    if peer_comps is None:
        return None

    used_forward = forward_eps is not None and forward_eps > 0
    has_shares = shares_outstanding is not None and shares_outstanding > 0
    mid: float | None = None
    source = ""
    confidence = 0.55

    if used_forward:
        # Forward EPS is analyst consensus — already a normalised forward number,
        # paired with the as-reported trailing peer median P/E (we have no peer
        # forward P/E). Highest-confidence path.
        if peer_comps.median_pe is not None and peer_comps.median_pe > 0:
            mid = peer_comps.median_pe * forward_eps  # type: ignore[operator]
            source = "peer_median_pe × forward_eps"
            confidence = 0.78
    else:
        # Trailing path: use the NOPAT core caliber so the target EPS and the
        # peer median P/E share ONE earnings definition — stripping the
        # non-operating items that differ across the set (the apples-to-oranges
        # that put NVDA's comps_pe at $341 on EPS inflated by ~$27B of TTM
        # investment gains). calculate_core_pe fills these in the pipeline.
        core_ni = peer_comps.target.core_net_income
        if (
            peer_comps.median_core_pe is not None
            and peer_comps.median_core_pe > 0
            and core_ni is not None
            and core_ni > 0
            and has_shares
        ):
            core_eps = core_ni / shares_outstanding  # type: ignore[operator]
            mid = peer_comps.median_core_pe * core_eps
            source = "peer_median_core_pe × core_eps（NOPAT 核心盈利口径，forward 不可得）"
            confidence = 0.55
        elif peer_comps.median_pe is not None and peer_comps.median_pe > 0 and has_shares:
            # Fallback: core caliber unavailable (provider omitted operating
            # margin / tax) — keep the as-reported trailing path rather than
            # dropping the method entirely.
            net_income = peer_comps.target.net_income
            if net_income is not None and net_income > 0:
                mid = peer_comps.median_pe * (net_income / shares_outstanding)  # type: ignore[operator]
                source = "peer_median_pe × trailing_eps (forward 不可得)"
                confidence = 0.55

    if mid is None or mid <= 0:
        return None

    band = mid * _COMPS_PE_BAND_WIDTH
    return ValuationMethodRange(
        method="comps_pe",
        method_type="valuation",
        low=mid - band,
        mid=mid,
        high=mid + band,
        confidence=confidence,
        source=source,
    )


def _ddm_method(ddm: DDMResult | None) -> ValuationMethodRange | None:
    if ddm is None or ddm.equity_value_per_share <= 0:
        return None
    mid = ddm.equity_value_per_share
    return ValuationMethodRange(
        method="ddm",
        method_type="valuation",
        low=mid * (1 - _DDM_BAND_WIDTH),
        mid=mid,
        high=mid * (1 + _DDM_BAND_WIDTH),
        confidence=0.55,
        source="perpetuity_growth ± 15%",
    )


def _lbo_method(
    lbo: LBOResult | None, shares_outstanding: float | None
) -> ValuationMethodRange | None:
    """Build LBO target-price band by reusing the saved entry × exit sensitivity grid.

    Per spec §6.4.2: we never re-run ``calculate_lbo`` per cell. Read the grid,
    compute target_price = (exit_multiple × exit_ebitda - remaining_debt) / shares
    for each cell, then take the min/median/max as the band.
    """
    if lbo is None or shares_outstanding is None or shares_outstanding <= 0:
        return None

    grid = lbo.sensitivity or {}
    exit_multiples = grid.get("exit_multiples") if isinstance(grid, dict) else None
    if not isinstance(exit_multiples, list) or not exit_multiples:
        return None

    remaining_debt = lbo.schedule[-1].ending_debt if lbo.schedule else 0.0
    exit_ebitda = lbo.exit_ebitda
    if exit_ebitda <= 0:
        return None

    target_prices = _lbo_target_grid(
        exit_multiples, exit_ebitda, remaining_debt, shares_outstanding
    )
    if not target_prices:
        return None

    target_prices.sort()
    return ValuationMethodRange(
        method="lbo",
        method_type="valuation",
        low=target_prices[0],
        mid=target_prices[len(target_prices) // 2],
        high=target_prices[-1],
        confidence=0.60,
        source="exit_multiple × exit_ebitda - remaining_debt (复用 sensitivity 网格)",
    )


def _lbo_target_grid(
    exit_multiples: list[Any],
    exit_ebitda: float,
    remaining_debt: float,
    shares: float,
) -> list[float]:
    out: list[float] = []
    for raw in exit_multiples:
        try:
            mult = float(raw)
        except (TypeError, ValueError):
            continue
        if mult <= 0:
            continue
        exit_equity = mult * exit_ebitda - remaining_debt
        if exit_equity <= 0:
            continue
        price = exit_equity / shares
        if price > 0:
            out.append(price)
    return out


def _ev_ebitda_method(
    forward_ebitda: float | None,
    band: tuple[float, float] | None,
    shares: float | None,
    lbo: LBOResult | None,
) -> ValuationMethodRange | None:
    if (
        forward_ebitda is None
        or forward_ebitda <= 0
        or band is None
        or shares is None
        or shares <= 0
    ):
        return None
    p25, p75 = band
    if p25 <= 0 or p75 <= 0:
        return None
    # Net debt needed to back out equity value from EV. Reuse LBO's view of
    # remaining debt when available — otherwise the caller must supply.
    net_debt = lbo.schedule[-1].ending_debt if (lbo is not None and lbo.schedule) else 0.0
    low = max(0.01, (p25 * forward_ebitda - net_debt) / shares)
    high = max(low, (p75 * forward_ebitda - net_debt) / shares)
    mid = (low + high) / 2
    return ValuationMethodRange(
        method="ev_ebitda",
        method_type="multiple",
        low=low,
        mid=mid,
        high=high,
        confidence=0.72,
        source="self_3y_p25_p75 × forward_ebitda",
    )


def _p_fcf_method(
    forward_fcf: float | None,
    band: tuple[float, float] | None,
    shares: float | None,
) -> ValuationMethodRange | None:
    if forward_fcf is None or forward_fcf <= 0 or band is None or shares is None or shares <= 0:
        return None
    p25, p75 = band
    if p25 <= 0 or p75 <= 0:
        return None
    low = (p25 * forward_fcf) / shares
    high = (p75 * forward_fcf) / shares
    mid = (low + high) / 2
    return ValuationMethodRange(
        method="p_fcf",
        method_type="multiple",
        low=low,
        mid=mid,
        high=high,
        confidence=0.65,
        source="self_3y_p25_p75 × forward_fcf",
    )
