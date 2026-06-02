"""Cross-currency peer-comps normalization to canonical USD.

yfinance carries TWO currency codes per issuer and they DISAGREE for
foreign-listed ADRs: ``currency`` is the quote currency (drives marketCap)
and ``financialCurrency`` is the IS/BS reporting currency.

- US issuers (NVDA / AAPL / MSFT): both = USD → no-op.
- ADR like TSM: ``quote_currency=USD`` (marketCap is USD), but
  ``reporting_currency=TWD`` (revenue/ebitda/net_income/debt/cash are TWD).
  Computing EV/EBITDA from this mix gives 0.158x — exactly the failure
  mode this module guards against.
- Local listing like 2330.TW: both = TWD → all line items need conversion.

Damodaran (Investment Valuation 3e Ch.7), CFA L2 Equity 2024 R.27, and
sell-side IB convention (GS / MS / JPM global sector comp sheets) all
require single-currency comparison for cross-border comps.

**MVP scope**: today's spot rate per peer for each currency that needs
conversion. The strict IAS 21 / ASC 830 translation (IS uses fiscal-period
average rate, BS uses period-end spot) is on the roadmap. The MVP rate
gap is ~2-3% for major peer currencies in normal volatility regimes and
never inverts the EV/EBITDA ordering — well inside the 5-15x typical
peer-spread noise floor.
"""

from __future__ import annotations

from finrobot.engine.models.financial import CompanyFinancials


def normalize_company_to_usd(
    company: CompanyFinancials,
    reporting_fx_rate_to_usd: float,
    quote_fx_rate_to_usd: float,
) -> CompanyFinancials:
    """Return a copy of ``company`` with all monetary fields converted to USD.

    Args:
        company: A peer's financials carrying ``reporting_currency`` and
            ``quote_currency`` tags from the extractor layer.
        reporting_fx_rate_to_usd: Multiplicative factor for IS/BS items —
            ``USD_value = local_value × rate``. For TWD → USD at 32 TWD/USD,
            the rate is ``1/32 ≈ 0.0313``. Ignored when
            ``company.reporting_currency`` is already USD.
        quote_fx_rate_to_usd: Multiplicative factor for ``market_cap`` and
            ``enterprise_value`` (both follow the quote currency). Same
            sign convention as above. Ignored when
            ``company.quote_currency`` is already USD.

    Callers obtain rates from
    ``finrobot.engine.data.providers.fx.fetch_fx_rate_to_usd``. For US
    issuers (both currencies = USD) the call is still safe — both rates
    are unused and the input is returned unchanged.

    Returns:
        A new ``CompanyFinancials`` with both currency tags set to USD and
        every monetary field scaled by the appropriate rate. Ratio fields
        (``ev_ebitda``, ``ev_revenue``, ``pe_ratio``, margins) are passed
        through untouched — they are dimensionless once the numerator and
        denominator are denominated consistently, and they will typically
        be recomputed by ``calculate_multiples`` downstream anyway.

    Fast path: when both currency tags are already USD the input is
    returned unchanged (no copy).

    Raises:
        ValueError: If a rate that will actually be applied (i.e. the
            corresponding currency is non-USD) is non-positive or NaN.
    """
    reporting_src = company.reporting_currency.upper()
    quote_src = company.quote_currency.upper()

    if reporting_src == "USD" and quote_src == "USD":
        return company

    if reporting_src != "USD":
        _validate_rate(reporting_fx_rate_to_usd, company.ticker, reporting_src, "reporting")
        reporting_rate = reporting_fx_rate_to_usd
    else:
        reporting_rate = 1.0

    if quote_src != "USD":
        _validate_rate(quote_fx_rate_to_usd, company.ticker, quote_src, "quote")
        quote_rate = quote_fx_rate_to_usd
    else:
        quote_rate = 1.0

    converted = company.model_copy(deep=True)
    converted.revenue = company.revenue * reporting_rate
    # None (provider didn't report) stays None through FX — converting an unknown
    # to 0 would re-fabricate the value the model now refuses to assume.
    converted.ebitda = company.ebitda * reporting_rate if company.ebitda is not None else None
    converted.net_income = (
        company.net_income * reporting_rate if company.net_income is not None else None
    )
    converted.total_debt = (
        company.total_debt * reporting_rate if company.total_debt is not None else None
    )
    converted.total_cash = (
        company.total_cash * reporting_rate if company.total_cash is not None else None
    )
    # income_tax_expense is a reporting-currency line item: it MUST scale with
    # net_income so calculate_core_pe's effective tax rate tax/(net_income+tax)
    # stays currency-invariant. Scaling net_income alone would skew the ratio and
    # corrupt a foreign issuer's NOPAT core P/E (BUG-018).
    converted.income_tax_expense = (
        company.income_tax_expense * reporting_rate
        if company.income_tax_expense is not None
        else None
    )
    # operating_income is a reporting-currency absolute (EBIT) feeding core_pe's
    # NOPAT — scale it like revenue/net_income so the USD core P/E is consistent.
    converted.operating_income = (
        company.operating_income * reporting_rate if company.operating_income is not None else None
    )

    converted.market_cap = company.market_cap * quote_rate
    if company.enterprise_value is not None:
        # EV mixes a quote-currency component (market_cap) with reporting-
        # currency components (debt/cash). When the two currencies disagree
        # the pre-normalization EV is meaningless; the only safe move is to
        # drop the cached value and let calculate_multiples recompute it
        # from the now-consistently-USD inputs.
        if reporting_src != quote_src:
            converted.enterprise_value = None
        else:
            converted.enterprise_value = company.enterprise_value * reporting_rate

    converted.reporting_currency = "USD"
    converted.quote_currency = "USD"
    return converted


def _validate_rate(rate: float, ticker: str, src_ccy: str, kind: str) -> None:
    if rate <= 0 or rate != rate:  # NaN guard
        raise ValueError(
            f"{kind}_fx_rate_to_usd must be positive and finite, got {rate!r} "
            f"for {ticker} ({src_ccy} → USD)"
        )
