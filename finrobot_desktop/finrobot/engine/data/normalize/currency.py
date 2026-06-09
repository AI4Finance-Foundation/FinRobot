"""Reporting-currency resolution for the normalization layer (ADR-0004).

yfinance ``financialCurrency`` is unreliable for ADRs — it often returns "USD"
for TSM/ASML/SAP when the IS/BS are actually in the home currency. FMP frequently
omits the field entirely. We use the country field as a reliable override signal.

We only override when the provider says "USD" but country implies a different
home currency — never override a non-USD provider tag, which would mask
legitimate multi-currency structures (e.g. a Bermuda-domiciled holding co that
genuinely reports in USD).
"""

from __future__ import annotations

from finrobot.engine.data.normalize.contracts import NormalizedFinancials

# Keys are yfinance-style full country names on purpose. FMP returns ISO-2 codes
# ("TW" not "Taiwan"), so this override is inert on the FMP path — and that is
# CORRECT, not a gap. Probe 2026-06-08 (12 foreign ADRs): FMP always supplies an
# authoritative ``reportedCurrency`` (TSM=TWD, SAP=EUR, NVO=DKK …) so the USD-tag
# branch in resolve_reporting_currency never fires for FMP; the only FMP "USD"
# tags are genuinely-USD reporters (SHEL/BP/TTE/RIO — GB/FR oil & mining majors
# that report in USD). Adding ISO-2 keys would false-positive all four, corrupting
# correct USD into GBP/EUR. Do NOT "fix" the key style to match FMP country codes.
COUNTRY_TO_REPORTING_CURRENCY: dict[str, str] = {
    "Taiwan": "TWD",
    "Japan": "JPY",
    "South Korea": "KRW",
    "China": "CNY",
    "Hong Kong": "HKD",
    "Germany": "EUR",
    "Netherlands": "EUR",
    "France": "EUR",
    "Italy": "EUR",
    "Spain": "EUR",
    "Switzerland": "CHF",
    "Sweden": "SEK",
    "Denmark": "DKK",
    "Norway": "NOK",
    "United Kingdom": "GBP",
    "Australia": "AUD",
    "Canada": "CAD",
    "India": "INR",
    "Brazil": "BRL",
    "Mexico": "MXN",
    "Singapore": "SGD",
    "Israel": "ILS",
}


def resolve_reporting_currency(
    provider_tag: str | None,
    ticker: str,
    country: str | None,
) -> str:
    """Reliable IS/BS reporting currency (ISO 4217, uppercase).

    Overrides a "USD" provider tag with the country's home currency only for
    ADRs (no '.' suffix). Local listings (e.g. 2330.TW) already carry the
    correct non-USD tag and are never overridden.
    """
    normalised = (provider_tag or "USD").upper()
    if normalised != "USD" or country is None:
        return normalised
    home_ccy = COUNTRY_TO_REPORTING_CURRENCY.get(country)
    if home_ccy is None:
        return normalised  # US or unknown country — trust USD
    if "." not in ticker:
        return home_ccy  # ADR on a US exchange — IS/BS in home currency
    return normalised  # local listing — provider tag already correct


def normalize_canonical_financials_currency(
    financials: NormalizedFinancials,
    reporting_to_quote_rate: float,
) -> NormalizedFinancials:
    """Express a canonical snapshot's reporting-currency line items in its QUOTE
    currency so the object is single-currency before any EV/multiple forms.

    The canonical FX gate (ADR-0006): ``DataLayer._fetch_canonical_uncached``
    calls this for FINANCIALS whenever ``reporting_currency != quote_currency``
    — the foreign-ADR mix where IS/BS line items are in the home currency (TWD
    for TSM) but the market quote is USD. Left mixed, ``extract_financial_data``
    forms ``EV = market_cap(USD) + total_debt(TWD) - total_cash(TWD)``, which
    goes negative when the TWD legs dwarf the USD cap (live -75B TSM bug, probe
    2026-06-09). After conversion ``reporting_currency == quote_currency``, so no
    downstream consumer (the /financials route, Coverage, the AI orchestrator)
    can produce a cross-currency ratio.

    Only the *reporting-currency* amounts are scaled — the market quote
    (``market_cap`` / ``current_price``) is already in the quote currency and is
    left untouched. ``pe_ratio`` / ``forward_pe`` may have been provider-computed
    across the two currencies, so they are re-derived once both sides share one
    currency (or set to ``None`` when not derivable). Margins, yields, beta and
    share counts are dimensionless / currency-invariant and pass through.

    Args:
        financials: a canonical snapshot carrying ``reporting_currency`` and
            ``quote_currency`` tags.
        reporting_to_quote_rate: factor that expresses one unit of the reporting
            currency in the quote currency (``quote_value = reporting_value ×
            rate``). When the quote currency is USD this is the reporting→USD
            spot; otherwise reporting→USD ÷ quote→USD. Supplied by the caller.

    Returns:
        A new ``NormalizedFinancials`` in a single currency (= the quote
        currency). Fast path: when ``reporting_currency == quote_currency`` the
        input is returned unchanged (US issuers and local listings — no copy).

    Raises:
        ValueError: if ``reporting_to_quote_rate`` is non-positive or NaN (only
        checked on the conversion path, never on the no-op fast path).
    """
    if financials.reporting_currency.upper() == financials.quote_currency.upper():
        return financials
    if reporting_to_quote_rate <= 0 or reporting_to_quote_rate != reporting_to_quote_rate:
        raise ValueError(
            f"reporting_to_quote_rate must be positive and finite, got "
            f"{reporting_to_quote_rate!r} for {financials.ticker} "
            f"({financials.reporting_currency}→{financials.quote_currency})"
        )

    rate = reporting_to_quote_rate

    def _scale(value: float | None) -> float | None:
        # None ≠ 0: a missing figure stays missing through FX rather than
        # being scaled from a fabricated zero.
        return value * rate if value is not None else None

    converted = financials.model_copy(deep=True)

    # Reporting-currency absolutes (income statement / balance sheet / cash flow)
    # and per-share amounts (EPS, BVPS, DPS) — everything denominated in the home
    # reporting currency.
    converted.revenue = _scale(financials.revenue)
    converted.ebitda = _scale(financials.ebitda)
    converted.net_income = _scale(financials.net_income)
    converted.operating_income = _scale(financials.operating_income)
    converted.income_tax_expense = _scale(financials.income_tax_expense)
    converted.depreciation_amortization = _scale(financials.depreciation_amortization)
    converted.rd_expense = _scale(financials.rd_expense)
    converted.sga_expense = _scale(financials.sga_expense)
    converted.interest_expense = _scale(financials.interest_expense)
    converted.total_debt = _scale(financials.total_debt)
    converted.total_cash = _scale(financials.total_cash)
    converted.preferred_stock = _scale(financials.preferred_stock)
    converted.noncontrolling_interest = _scale(financials.noncontrolling_interest)
    converted.operating_cash_flow = _scale(financials.operating_cash_flow)
    converted.capital_expenditure = _scale(financials.capital_expenditure)
    converted.book_value_per_share = _scale(financials.book_value_per_share)
    converted.dividend_per_share = _scale(financials.dividend_per_share)
    converted.forward_eps = _scale(financials.forward_eps)
    converted.trailing_eps = _scale(financials.trailing_eps)

    # market_cap / current_price are already in the quote currency — untouched.

    # Re-derive ratios the provider may have computed across the two currencies
    # (market_cap[quote] / net_income[reporting]) now that both share the quote
    # currency. None when not derivable, mirroring normalize_financialdata_to_usd.
    ni_q = converted.net_income
    converted.pe_ratio = (
        converted.market_cap / ni_q if (converted.market_cap and ni_q and ni_q > 0) else None
    )
    fwd_eps_q = converted.forward_eps
    converted.forward_pe = (
        converted.current_price / fwd_eps_q
        if (converted.current_price and fwd_eps_q and fwd_eps_q > 0)
        else None
    )

    converted.reporting_currency = financials.quote_currency
    return converted
