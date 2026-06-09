"""Forward financial estimates — the one true entry point for forward EPS / EBITDA / FCF.

v5 PR4c. Spec §6.4.1 made this a red-line module: nothing else in the codebase
may compute or guess forward EPS / EBITDA / FCF. Football Field's multiple
rows (EV/EBITDA and P/FCF reverse-engineering, spec §6.4) read from here;
the audit test below grep-pins that no other call site shells out an analyst
consensus number on its own.

Two resolution paths:

  * FMP consensus (preferred) — when ``fmp_analyst_estimates`` is supplied
    (DataType.FORWARD_ESTIMATES via DataLayer), the FY1 row (nearest
    fiscal-year-end ≥ as_of) fills forward EPS / revenue / EBITDA from analyst
    consensus. FMP's analyst-estimates endpoint does NOT carry free cash flow,
    so forward_fcf stays None and the P/FCF reverse row stays hidden.
    confidence = ``high`` when consensus EBITDA is present (forward P/E AND
    EV/EBITDA both consensus-driven), else ``medium``. ``fiscal_period`` records
    the exact FYE used so the forward P/E denominator is auditable.
  * yfinance degraded path — when no FMP payload is available, forward_eps
    comes from yfinance ``info["forwardEps"]`` only; forward revenue / EBITDA
    / FCF stay None (no back-fill, per spec §6.4.1) and the aggregator hides
    those rows. confidence = ``low`` (or down-rated on >20% TTM-margin
    volatility), ``unavailable`` when even forward_eps is missing.

Spec §6.4.1 keeps this a red-line leaf: nothing else may compute or guess a
forward EPS / EBITDA / FCF number. The audit tests in
``tests/audit/test_forward_estimates_red_lines.py`` grep-pin that gate.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

ConfidenceLevel = Literal["high", "medium", "low", "unavailable"]


@dataclass(frozen=True)
class ForwardFinancials:
    """All forward-looking numbers any caller is allowed to use.

    ``source`` describes provenance so downstream banners can render an
    accurate "this came from analyst consensus" / "this is derived from
    TTM × forecast revenue" label — every number stays traceable to its口径.
    ``fiscal_period`` records WHICH forecast fiscal-year-end these numbers
    belong to (e.g. "2026-09-30") so the forward P/E denominator is auditable
    and comps PE / EV-EBITDA / FCF-yield all share one fiscal-year口径.
    """

    ticker: str
    forward_eps: float | None
    forward_revenue: float | None
    forward_ebitda: float | None
    forward_fcf: float | None
    confidence: ConfidenceLevel
    source: str
    warnings: list[str]
    fiscal_period: str | None = None
    forward_net_income: float | None = None
    """FY1 consensus net income (FMP ``estimatedNetIncomeAvg``), reporting currency.

    Lets a market-cap-centric consumer (the peer comps set, whose CompanyFinancials
    carries ``market_cap`` but no price/shares) compute forward P/E as
    ``market_cap / forward_net_income`` — algebraically the SAME caliber as the
    target side's ``price / forward_eps`` (market_cap = price × shares,
    forward_net_income = forward_eps × shares). None on the yfinance degraded path
    (consensus net income unavailable there)."""


_TTM_VOLATILITY_THRESHOLD = 0.20
"""TTM margin std/mean ratio above which we down-rate confidence to 'low'."""


def get_forward_financials(
    *,
    ticker: str,
    yf_info: dict[str, Any] | None,
    historical_ebitda_margins: list[float] | None = None,
    historical_fcf_margins: list[float] | None = None,
    fmp_analyst_estimates: dict[str, Any] | None = None,
    as_of: date | None = None,
) -> ForwardFinancials:
    """Resolve every forward financial number for one ticker.

    Args:
        ticker: Uppercase ticker symbol.
        yf_info: yfinance Ticker.info dict (or the FinancialData.raw_data
            equivalent) — used for forward_eps / shares fallback.
        historical_ebitda_margins: 3-year EBITDA-margin list for volatility
            assessment and EBITDA derivation. Empty / None drops EBITDA
            confidence to 'low'.
        historical_fcf_margins: 3-year FCF-margin list (same role).
        fmp_analyst_estimates: FMP /v3/analyst-estimates payload, shape
            ``{"rows": [...]}`` (newest/farthest-future first). When present,
            FMP consensus is preferred over the yfinance forward_eps fallback.
        as_of: Reference date for forward-period selection. The leaf picks the
            nearest fiscal-year-end ≥ as_of (FY1). Defaults to today.

    Returns:
        ForwardFinancials with whatever could be filled and a Chinese-language
        warning list explaining each None.
    """
    warnings: list[str] = []

    if fmp_analyst_estimates:
        return _from_fmp(ticker, fmp_analyst_estimates, warnings, as_of or date.today())

    if not yf_info:
        return _unavailable(ticker, "无 yfinance info — forward 全部不可得")

    forward_eps = _coerce_positive_float(yf_info.get("forward_eps") or yf_info.get("forwardEps"))
    if forward_eps is None:
        warnings.append("forward_eps 不可得 — FMP /v3/analyst-estimates 待集成（PR4c.2）")

    # Without FMP we have no consensus forward revenue, so forward EBITDA / FCF
    # can't be derived either. Stay honest rather than back-fill.
    forward_revenue: float | None = None
    forward_ebitda: float | None = None
    forward_fcf: float | None = None
    if forward_eps is not None:
        warnings.append(
            "forward_revenue / forward_ebitda / forward_fcf 暂不可得："
            "yfinance 只有 forward EPS，consensus 营收/利润待 FMP analyst-estimates 集成"
        )

    confidence: ConfidenceLevel = "low" if forward_eps is not None else "unavailable"

    margin_warning = _margin_volatility_warning(historical_ebitda_margins, historical_fcf_margins)
    if margin_warning is not None:
        warnings.append(margin_warning)
        confidence = "low"

    source = (
        "yfinance.info.forwardEps (degraded · FMP consensus 待集成)"
        if forward_eps is not None
        else "无可用 forward 数据源"
    )

    return ForwardFinancials(
        ticker=ticker.upper(),
        forward_eps=forward_eps,
        forward_revenue=forward_revenue,
        forward_ebitda=forward_ebitda,
        forward_fcf=forward_fcf,
        confidence=confidence,
        source=source,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# FMP path — wired-but-empty hook for PR4c.2
# ---------------------------------------------------------------------------


def get_forward_revenue_growth(
    fmp_analyst_estimates: dict[str, Any] | None,
    *,
    as_of: date | None = None,
    max_years: int = 3,
) -> list[float]:
    """Forward YoY revenue-growth path (FY1..FYn) from FMP analyst-estimates.

    Returns up to ``max_years`` consecutive consensus growth rates — FY1/last
    actual − 1, then FY2/FY1 − 1, … — for seeding the DCF explicit window so the
    model reflects analyst consensus instead of a backward-looking trailing CAGR.
    Returns ``[]`` (caller falls back to trailing-CAGR seeding) when the payload
    is absent, has no parseable rows, or carries no past-actual row to anchor the
    FY1 growth. Far-out rows (beyond ``max_years``) are dropped — FMP consensus
    past ~3 years is sparse and non-monotonic.

    Lives here, not in dcf_seed, because §6.4.1 makes this leaf the only place
    allowed to mint a forward-consensus number; dcf_seed consumes the plain rates.
    """
    rows = (
        fmp_analyst_estimates.get("rows")
        if isinstance(fmp_analyst_estimates, dict)
        else fmp_analyst_estimates
    )
    if not isinstance(rows, list) or not rows:
        return []
    ref = as_of or date.today()
    parsed: list[tuple[date, float]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        d = _parse_iso_date(row.get("date"))
        rev = _coerce_positive_float(row.get("estimatedRevenueAvg"))
        if d is not None and rev is not None:
            parsed.append((d, rev))
    parsed.sort(key=lambda p: p[0])
    base = [p for p in parsed if p[0] < ref]
    forward = [p for p in parsed if p[0] >= ref][:max_years]
    if not base or not forward:
        return []
    seq = [base[-1][1]] + [p[1] for p in forward]
    return [seq[i] / seq[i - 1] - 1 for i in range(1, len(seq))]


def _from_fmp(
    ticker: str, fmp: dict[str, Any], warnings: list[str], as_of: date
) -> ForwardFinancials:
    """Parse FMP /v3/analyst-estimates response shape.

    Expected shape (FMP returns a list of fiscal years, farthest-future first):
      [{
        "date": "2026-09-30",          # fiscal-year-end
        "estimatedRevenueAvg": 1.2e11,  # absolute, reporting currency
        "estimatedEbitdaAvg": 4.5e10,   # absolute, reporting currency
        "estimatedEpsAvg": 12.5,        # per-share, reporting currency
        ...
      }, ...]

    The "forward" period is FY1 — the nearest fiscal-year-end ≥ ``as_of`` —
    NOT ``rows[0]`` (which is the farthest-future year FMP returns). Using a
    FY+3 estimate as the forward P/E numerator would be a wrong number.
    """
    rows = fmp.get("rows") if isinstance(fmp, dict) else fmp
    if not isinstance(rows, list) or not rows:
        return _unavailable(ticker, "FMP analyst-estimates 返回空 — 降级到 yfinance forward EPS")

    chosen, period_warning = _select_forward_row(rows, as_of)
    if chosen is None:
        return _unavailable(ticker, "FMP analyst-estimates 行格式异常")
    if period_warning is not None:
        warnings.append(period_warning)

    forward_eps = _coerce_positive_float(chosen.get("estimatedEpsAvg"))
    forward_revenue = _coerce_positive_float(chosen.get("estimatedRevenueAvg"))
    forward_ebitda = _coerce_positive_float(chosen.get("estimatedEbitdaAvg"))
    forward_fcf = _coerce_positive_float(chosen.get("estimatedFreeCashFlowAvg"))
    forward_net_income = _coerce_positive_float(chosen.get("estimatedNetIncomeAvg"))

    if forward_eps is None and forward_revenue is None:
        return _unavailable(ticker, "FMP 行缺关键字段 (eps/revenue)")

    # FMP /v3/analyst-estimates supplies consensus EPS / revenue / EBITDA but
    # NOT free cash flow (estimatedFreeCashFlowAvg is absent → forward_fcf stays
    # None, so the P/FCF reverse row stays hidden). Don't gate 'high' on FCF or
    # it's unreachable: 'high' = consensus EPS + EBITDA (forward P/E AND forward
    # EV/EBITDA both consensus-driven); 'medium' = EPS / revenue only.
    if forward_eps is None:
        warnings.append("FMP 行无 estimatedEpsAvg — forward P/E 不可得")
    confidence: ConfidenceLevel = "high" if forward_ebitda is not None else "medium"

    fiscal_period = chosen.get("date") if isinstance(chosen.get("date"), str) else None

    return ForwardFinancials(
        ticker=ticker.upper(),
        forward_eps=forward_eps,
        forward_revenue=forward_revenue,
        forward_ebitda=forward_ebitda,
        forward_fcf=forward_fcf,
        confidence=confidence,
        source="FMP /v3/analyst-estimates consensus",
        warnings=warnings,
        fiscal_period=fiscal_period,
        forward_net_income=forward_net_income,
    )


def _select_forward_row(rows: list[Any], as_of: date) -> tuple[dict[str, Any] | None, str | None]:
    """Pick the FY1 estimate row: nearest fiscal-year-end ≥ as_of.

    Falls back to the most-recent past row (with a staleness warning) when no
    future fiscal year remains, and to the first usable row when no row carries
    a parseable date at all. Returns (row, warning_or_None).
    """
    dated: list[tuple[date, dict[str, Any]]] = []
    undated_first: dict[str, Any] | None = None
    for row in rows:
        if not isinstance(row, dict):
            continue
        parsed = _parse_iso_date(row.get("date"))
        if parsed is not None:
            dated.append((parsed, row))
        elif undated_first is None:
            undated_first = row

    future = sorted((d for d in dated if d[0] >= as_of), key=lambda dr: dr[0])
    if future:
        return future[0][1], None

    if dated:
        latest = max(dated, key=lambda dr: dr[0])
        return latest[1], (
            f"FMP analyst-estimates 最新预测期 {latest[0].isoformat()} 早于 "
            f"{as_of.isoformat()} — forward 数据可能过期"
        )

    if undated_first is not None:
        return undated_first, "FMP analyst-estimates 行缺 date — 无法确认 forward 财年口径"

    return None, None


def _parse_iso_date(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _unavailable(ticker: str, reason: str) -> ForwardFinancials:
    return ForwardFinancials(
        ticker=ticker.upper(),
        forward_eps=None,
        forward_revenue=None,
        forward_ebitda=None,
        forward_fcf=None,
        confidence="unavailable",
        source="未集成 / 数据缺失",
        warnings=[reason],
    )


def _margin_volatility_warning(
    ebitda_margins: list[float] | None, fcf_margins: list[float] | None
) -> str | None:
    """If TTM margins are too volatile to extrapolate, flag it."""
    for label, series in (("EBITDA", ebitda_margins), ("FCF", fcf_margins)):
        if not series or len(series) < 2:
            continue
        mean = statistics.fmean(series)
        if abs(mean) < 1e-9:
            continue
        stdev = statistics.pstdev(series)
        if stdev / abs(mean) > _TTM_VOLATILITY_THRESHOLD:
            return (
                f"TTM {label} 利润率波动 {stdev / abs(mean):.0%} > 20% — "
                "forward 推算 confidence 降为 low"
            )
    return None


def _coerce_positive_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    # `f > 0` drops NaN and -Inf but PASSES +Inf (inf > 0 is True) — an asymmetric
    # gate that leaked +Inf into avg_*_surprise_pct. Require finiteness too.
    return f if f > 0 and math.isfinite(f) else None
