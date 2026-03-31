from pydantic import BaseModel


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

import re


# Non-ticker acronyms to exclude from peer detection
_NON_TICKER_ACRONYMS = {
    "WACC", "DCF", "EBITDA", "GAAP", "IFRS", "FCF", "ROIC", "ROE", "ROA",
    "EPS", "YOY", "QOQ", "CAGR", "IPO", "LBO", "SEC", "GDP", "CPI", "FED",
    "NYSE", "ETF", "CEO", "CFO", "COO", "BUY", "SELL", "HOLD", "NOTE",
    "USD", "EUR", "GBP", "JPY", "CNY",
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
        any(kw in lower for kw in ["revenue projection", "ebitda projection", "revenue forecast", "ebitda forecast"]),
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
        any(kw in lower for kw in ["buy", "hold", "sell", "overweight", "underweight", "outperform"]),
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
        return ValidationResult(passed=False, error=f"Expected at least 3 headers, found {len(headers)}")

    # At least 200 words
    words = len(output.split())
    if words < 200:
        return ValidationResult(passed=False, error=f"Expected at least 200 words, found {words}")

    # At least 2 of these section keywords
    lower = output.lower()
    section_kws = ["summary", "valuation", "risk", "thesis", "peer", "financial"]
    found = sum(1 for kw in section_kws if kw in lower)
    if found < 2:
        return ValidationResult(passed=False, error=f"Expected at least 2 section keywords, found {found}")

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
        return ValidationResult(passed=False, error="Missing statistical terms (median/mean/average)")

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
        any(kw in lower for kw in ["implied price", "implied value", "valuation range", "fair value", "price target"]),
    ]
    found = sum(indicators)
    if found >= 3:
        return ValidationResult(passed=True)
    return ValidationResult(
        passed=False,
        error=f"Expected at least 3 DCF components, found {found}",
    )
