"""Forward financial estimates — the one true entry point for forward EPS / EBITDA / FCF.

v5 PR4c. Spec §6.4.1 made this a red-line module: nothing else in the codebase
may compute or guess forward EPS / EBITDA / FCF. Football Field's multiple
rows (EV/EBITDA and P/FCF reverse-engineering, spec §6.4) read from here;
the audit test below grep-pins that no other call site shells out an analyst
consensus number on its own.

Today's behaviour (degraded path — FMP /v3/analyst-estimates not yet wired):

  * forward_eps: from yfinance ``info["forwardEps"]`` when present.
  * forward_revenue: derive from ``forward_eps × shares_outstanding /
    profit_margin`` is a stretch, so we leave it None until FMP lands. This
    is acceptable per spec §6.4.1 — without forward_revenue we drop forward
    EBITDA / FCF to None too and let the aggregator hide those rows.
  * forward_ebitda / forward_fcf: derived from ``forward_revenue × TTM
    margin`` once forward_revenue is available. Until then they're None.
  * confidence: ``low`` whenever any derived (non-consensus) number is used
    or when TTM margin volatility > 20%, ``medium`` when forward_eps came
    straight from analyst data with stable margins, ``high`` reserved for
    when FMP consensus EBITDA / FCF lands (PR4c.2).

Open spike for PR4c.2: wire FMP ``/v3/analyst-estimates/{ticker}`` to fill
``forward_revenue`` / ``forward_ebitda`` / ``forward_fcf`` directly. Audit
test ``test_forward_estimates_is_only_entry`` keeps the gate in place so
new code can't bypass this leaf.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Any, Literal

ConfidenceLevel = Literal["high", "medium", "low", "unavailable"]


@dataclass(frozen=True)
class ForwardFinancials:
    """All forward-looking numbers any caller is allowed to use.

    ``source`` describes provenance so downstream banners can render an
    accurate "this came from analyst consensus" / "this is derived from
    TTM × forecast revenue" label (散户友好, no opaque numbers).
    """

    ticker: str
    forward_eps: float | None
    forward_revenue: float | None
    forward_ebitda: float | None
    forward_fcf: float | None
    confidence: ConfidenceLevel
    source: str
    warnings: list[str]


_TTM_VOLATILITY_THRESHOLD = 0.20
"""TTM margin std/mean ratio above which we down-rate confidence to 'low'."""


def get_forward_financials(
    *,
    ticker: str,
    yf_info: dict[str, Any] | None,
    historical_ebitda_margins: list[float] | None = None,
    historical_fcf_margins: list[float] | None = None,
    fmp_analyst_estimates: dict[str, Any] | None = None,
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
        fmp_analyst_estimates: PR4c.2 hook — when wired, prefer FMP's
            consensus forward EBITDA / FCF / revenue over yfinance forward_eps
            derivations. None today.

    Returns:
        ForwardFinancials with whatever could be filled and a Chinese-language
        warning list explaining each None.
    """
    warnings: list[str] = []

    if fmp_analyst_estimates:
        return _from_fmp(ticker, fmp_analyst_estimates, warnings)

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


def _from_fmp(ticker: str, fmp: dict[str, Any], warnings: list[str]) -> ForwardFinancials:
    """Parse FMP /v3/analyst-estimates response shape.

    Expected shape (FMP returns a list, most-recent first):
      [{
        "date": "2026-12-31",
        "estimatedRevenueAvg": 1.2e11,
        "estimatedEbitdaAvg": 4.5e10,
        "estimatedEpsAvg": 12.5,
        ...
      }, ...]
    """
    rows = fmp.get("rows") if isinstance(fmp, dict) else fmp
    if not isinstance(rows, list) or not rows:
        return _unavailable(ticker, "FMP analyst-estimates 返回空 — 降级到 yfinance forward EPS")

    latest = rows[0] if isinstance(rows[0], dict) else None
    if latest is None:
        return _unavailable(ticker, "FMP analyst-estimates 行格式异常")

    forward_eps = _coerce_positive_float(latest.get("estimatedEpsAvg"))
    forward_revenue = _coerce_positive_float(latest.get("estimatedRevenueAvg"))
    forward_ebitda = _coerce_positive_float(latest.get("estimatedEbitdaAvg"))
    forward_fcf = _coerce_positive_float(latest.get("estimatedFreeCashFlowAvg"))

    if forward_eps is None and forward_revenue is None:
        return _unavailable(ticker, "FMP 行缺关键字段 (eps/revenue)")

    confidence: ConfidenceLevel = (
        "high" if forward_ebitda is not None and forward_fcf is not None else "medium"
    )

    return ForwardFinancials(
        ticker=ticker.upper(),
        forward_eps=forward_eps,
        forward_revenue=forward_revenue,
        forward_ebitda=forward_ebitda,
        forward_fcf=forward_fcf,
        confidence=confidence,
        source="FMP /v3/analyst-estimates consensus",
        warnings=warnings,
    )


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
    return f if f > 0 else None
