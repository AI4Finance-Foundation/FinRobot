import math as _math
import re

from pydantic import BaseModel

from finagent.engine.models.financial import (
    FinancialData,
    LBOInputs,
    LBOResult,
    PeerComps,
    DCFResult,
    ThesisResult,
)


class ValidationResult(BaseModel):
    passed: bool
    error: str | None = None


def validate_is_non_empty(output: str) -> ValidationResult:
    """P0 validator. Passes if output is a non-empty, non-whitespace string."""
    if output and output.strip():
        return ValidationResult(passed=True)
    return ValidationResult(passed=False, error="Output is empty or whitespace")


def validate_has_fields(output: str, fields: list[str]) -> ValidationResult:
    """P0 validator. Checks that output string mentions all required field names."""
    normalized = output.lower()
    missing = [f for f in fields if f.replace("_", " ").lower() not in normalized]
    if not missing:
        return ValidationResult(passed=True)
    return ValidationResult(
        passed=False,
        error=f"Output missing required fields: {', '.join(missing)}",
    )


# Non-ticker acronyms to exclude from peer detection
_NON_TICKER_ACRONYMS = {
    "WACC",
    "DCF",
    "EBITDA",
    "GAAP",
    "IFRS",
    "FCF",
    "ROIC",
    "ROE",
    "ROA",
    "EPS",
    "YOY",
    "QOQ",
    "CAGR",
    "IPO",
    "LBO",
    "SEC",
    "GDP",
    "CPI",
    "FED",
    "NYSE",
    "ETF",
    "CEO",
    "CFO",
    "COO",
    "BUY",
    "SELL",
    "HOLD",
    "NOTE",
    "USD",
    "EUR",
    "GBP",
    "JPY",
    "CNY",
}


def validate_has_peers(output: str, min_peers: int = 3) -> ValidationResult:
    """Strict validator for peer analysis step.
    Checks that output mentions at least `min_peers` distinct company names/tickers."""
    # Find uppercase 2-5 letter sequences in ORIGINAL text (not uppercased)
    candidates = set(re.findall(r"\b([A-Z]{2,5})\b", output))
    tickers = candidates - _NON_TICKER_ACRONYMS
    if len(tickers) >= min_peers:
        return ValidationResult(passed=True)
    return ValidationResult(
        passed=False,
        error=f"Expected at least {min_peers} peer tickers, found {len(tickers)}: {tickers}",
    )


# DEPRECATED: P0/P1b keyword-based validators below.
# Kept for backward compatibility. New code should use typed validators (bottom of file).
def validate_has_valuation(output: str) -> ValidationResult:
    """Strict validator for financial modeling step.
    Checks that output contains valuation methodology and numbers.
    Must find at least 2 of the valuation indicators."""
    lower = output.lower()
    indicators = [
        any(kw in lower for kw in ["dcf", "discounted cash flow"]),
        any(kw in lower for kw in ["wacc", "discount rate", "cost of capital"]),
        any(kw in lower for kw in ["terminal value", "terminal growth"]),
        any(kw in lower for kw in ["price target", "implied value", "implied price", "fair value"]),
        any(
            kw in lower
            for kw in [
                "revenue projection",
                "ebitda projection",
                "revenue forecast",
                "ebitda forecast",
            ]
        ),
    ]
    found = sum(indicators)
    if found >= 2:
        return ValidationResult(passed=True)
    return ValidationResult(
        passed=False,
        error=f"Expected at least 2 valuation indicators, found {found}",
    )


def validate_has_thesis(output: str) -> ValidationResult:
    """Strict validator for thesis construction step.
    Checks that output contains investment thesis structure.
    Must find at least 2 of the thesis indicators."""
    lower = output.lower()
    indicators = [
        any(
            kw in lower for kw in ["buy", "hold", "sell", "overweight", "underweight", "outperform"]
        ),
        any(kw in lower for kw in ["catalyst", "upside", "driver", "tailwind"]),
        any(kw in lower for kw in ["risk", "downside", "headwind", "threat"]),
        any(kw in lower for kw in ["price target", "target price", "implied value"]),
    ]
    found = sum(indicators)
    if found >= 2:
        return ValidationResult(passed=True)
    return ValidationResult(
        passed=False,
        error=f"Expected at least 2 thesis indicators, found {found}",
    )


def validate_report_format(output: str) -> ValidationResult:
    """Strict validator for report generation step.
    Checks that output has proper report structure."""
    # At least 3 Markdown headers
    headers = re.findall(r"^#{1,3}\s+.+", output, re.MULTILINE)
    if len(headers) < 3:
        return ValidationResult(
            passed=False, error=f"Expected at least 3 headers, found {len(headers)}"
        )

    # At least 200 words
    words = len(output.split())
    if words < 200:
        return ValidationResult(passed=False, error=f"Expected at least 200 words, found {words}")

    # At least 2 of these section keywords
    lower = output.lower()
    section_kws = ["summary", "valuation", "risk", "thesis", "peer", "financial"]
    found = sum(1 for kw in section_kws if kw in lower)
    if found < 2:
        return ValidationResult(
            passed=False, error=f"Expected at least 2 section keywords, found {found}"
        )

    return ValidationResult(passed=True)


def validate_has_comps_table(output: str) -> ValidationResult:
    """Strict validator for comps pipeline output.
    Checks for multiples table structure."""
    # At least 3 company tickers (match uppercase in original text)
    candidates = set(re.findall(r"\b([A-Z]{2,5})\b", output))
    tickers = candidates - _NON_TICKER_ACRONYMS
    if len(tickers) < 3:
        return ValidationResult(
            passed=False,
            error=f"Expected at least 3 company tickers, found {len(tickers)}: {tickers}",
        )

    # At least 2 multiples keywords
    lower = output.lower()
    multiples_kws = ["ev/ebitda", "p/e", "ev/revenue", "multiple"]
    multiples_found = sum(1 for kw in multiples_kws if kw in lower)
    if multiples_found < 2:
        return ValidationResult(
            passed=False,
            error=f"Expected at least 2 multiples keywords, found {multiples_found}",
        )

    # Statistical terms
    stats_kws = ["median", "mean", "average"]
    if not any(kw in lower for kw in stats_kws):
        return ValidationResult(
            passed=False, error="Missing statistical terms (median/mean/average)"
        )

    return ValidationResult(passed=True)


def validate_dcf_output(output: str) -> ValidationResult:
    """Strict validator for DCF pipeline output.
    Checks for DCF model components. Must find at least 3."""
    lower = output.lower()
    indicators = [
        any(kw in lower for kw in ["wacc", "discount rate", "cost of capital"]),
        any(kw in lower for kw in ["terminal value", "terminal growth"]),
        any(kw in lower for kw in ["free cash flow", "fcf"]),
        any(kw in lower for kw in ["sensitivity", "scenario"]),
        any(
            kw in lower
            for kw in [
                "implied price",
                "implied value",
                "valuation range",
                "fair value",
                "price target",
            ]
        ),
    ]
    found = sum(indicators)
    if found >= 3:
        return ValidationResult(passed=True)
    return ValidationResult(
        passed=False,
        error=f"Expected at least 3 DCF components, found {found}",
    )


_VALID_RECOMMENDATIONS = {
    "Buy",
    "Hold",
    "Sell",
    "Overweight",
    "Underweight",
    "Outperform",
    "Underperform",
}


def validate_financial_data(
    data: FinancialData,
    ebitda_margin_range: tuple[float, float] = (-5.0, 0.9),
) -> ValidationResult:
    """Validate extracted financial data is reasonable.

    Args:
        ebitda_margin_range: (min, max) for EBITDA/revenue ratio.
            Default (-500%, 90%) covers pre-revenue biotech through high-margin software.
            Tighten for specific industry analysis if needed.
    """
    if data.income.revenue <= 0:
        return ValidationResult(passed=False, error="Revenue must be positive")
    if data.market.market_cap <= 0:
        return ValidationResult(passed=False, error="Market cap must be positive")
    margin = data.income.ebitda / data.income.revenue
    margin_min, margin_max = ebitda_margin_range
    if not (margin_min <= margin <= margin_max):
        return ValidationResult(
            passed=False,
            error=f"EBITDA margin {margin:.1%} out of range "
                  f"({margin_min:.0%} to {margin_max:.0%})",
        )
    if data.market.pe_ratio is not None and data.market.pe_ratio <= 0:
        return ValidationResult(passed=False, error="PE ratio must be positive if set")
    return ValidationResult(passed=True)


def validate_peer_comps(comps: PeerComps) -> ValidationResult:
    """Validate peer analysis result."""
    if len(comps.peers) < 3:
        return ValidationResult(
            passed=False, error=f"Need at least 3 peers, got {len(comps.peers)}"
        )
    for peer in comps.peers:
        if peer.revenue <= 0:
            return ValidationResult(
                passed=False, error=f"Peer {peer.ticker} has non-positive revenue"
            )
        if peer.ev_ebitda is not None and not (1 <= peer.ev_ebitda <= 100):
            return ValidationResult(
                passed=False,
                error=f"Peer {peer.ticker} EV/EBITDA {peer.ev_ebitda:.1f}x out of range 1-100x",
            )
    if comps.median_ev_ebitda is None:
        return ValidationResult(passed=False, error="Median EV/EBITDA statistics not computed")
    return ValidationResult(passed=True)


def validate_dcf_result(result: DCFResult) -> ValidationResult:
    """Validate DCF output."""
    if result.wacc <= 0:
        return ValidationResult(passed=False, error=f"WACC must be positive, got {result.wacc}")
    if result.wacc > 0.25:
        return ValidationResult(passed=False, error=f"WACC {result.wacc:.4f} exceeds maximum 0.25")
    if result.wacc < 0.03:
        return ValidationResult(passed=False, error=f"WACC {result.wacc:.4f} below minimum 0.03")
    if result.implied_price <= 0:
        return ValidationResult(passed=False, error="Implied price must be positive")
    if result.enterprise_value <= 0:
        return ValidationResult(passed=False, error="Enterprise value must be positive")
    for fcf in result.projected_fcf:
        if not _math.isfinite(fcf):
            return ValidationResult(passed=False, error=f"Non-finite FCF value: {fcf}")
    return ValidationResult(passed=True)


def validate_thesis(thesis: ThesisResult) -> ValidationResult:
    """Validate thesis structure."""
    if thesis.recommendation not in _VALID_RECOMMENDATIONS:
        return ValidationResult(
            passed=False,
            error=f"Recommendation '{thesis.recommendation}' must be one of {sorted(_VALID_RECOMMENDATIONS)}",
        )
    if thesis.price_target <= 0:
        return ValidationResult(passed=False, error="Price target must be positive")
    if len(thesis.catalysts) < 1:
        return ValidationResult(passed=False, error="At least 1 catalyst required")
    if len(thesis.risks) < 1:
        return ValidationResult(passed=False, error="At least 1 risk required")
    return ValidationResult(passed=True)


# ---------------------------------------------------------------------------
# LBO validators (P2d)
# ---------------------------------------------------------------------------


def validate_lbo_inputs(data: LBOInputs) -> ValidationResult:
    """Validate LLM-selected LBO assumptions are financially plausible."""
    if data.entry_ev_ebitda <= 0:
        return ValidationResult(passed=False, error="entry_ev_ebitda must be positive")
    if data.leverage_multiple >= 12:
        return ValidationResult(
            passed=False,
            error=f"leverage_multiple {data.leverage_multiple:.1f}x is unrealistically high (≥12×)",
        )
    if data.ebitda_margin <= 0:
        return ValidationResult(passed=False, error="ebitda_margin must be positive for LBO target")
    return ValidationResult(passed=True)


def validate_lbo_result(result: LBOResult) -> ValidationResult:
    """Validate LBO output values are within plausible bounds."""
    if result.moic <= 0:
        return ValidationResult(passed=False, error=f"MOIC {result.moic:.2f}x must be positive")
    if not (-1.0 <= result.irr <= 10.0):
        return ValidationResult(
            passed=False, error=f"IRR {result.irr:.2%} out of bounds [-100%, 1000%]"
        )
    if result.entry_equity <= 0:
        return ValidationResult(passed=False, error="Entry equity must be positive")
    return ValidationResult(passed=True)
