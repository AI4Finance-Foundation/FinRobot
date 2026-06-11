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

import math

from finrobot.engine.models.financial import CompanyFinancials, FinancialData


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
    # preferred + NCI are reporting-currency balance items (EV-bridge completeness):
    # scale with debt/cash so calculate_multiples recomputes a SINGLE-currency EV for
    # an ADR peer (reporting≠quote drops the cached EV below, forcing a recompute that
    # would otherwise add reporting-ccy preferred/NCI onto a USD EV). None stays None.
    converted.preferred_stock = (
        company.preferred_stock * reporting_rate if company.preferred_stock is not None else None
    )
    converted.noncontrolling_interest = (
        company.noncontrolling_interest * reporting_rate
        if company.noncontrolling_interest is not None
        else None
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
    # book_value_per_share is a reporting-currency per-share amount: scale it to USD
    # so _comps_pb_method (peer_median_pb × target_bvps) multiplies a USD bvps. The
    # pb_ratio itself was computed single-currency in extract_company_financials and
    # is dimensionless — but only US issuers carry it (reporting==quote gate), so a
    # foreign peer's pb_ratio is already None here; no recompute needed.
    converted.book_value_per_share = (
        company.book_value_per_share * reporting_rate
        if company.book_value_per_share is not None
        else None
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


def normalize_financialdata_to_usd(
    financials: FinancialData,
    reporting_fx_rate_to_usd: float,
    quote_fx_rate_to_usd: float,
) -> FinancialData:
    """Return a copy of ``financials`` with all monetary fields converted to USD.

    The ``FinancialData`` sibling of :func:`normalize_company_to_usd`. Used at the
    DCF/DDM seed boundary so the absolute valuation models never mix a
    reporting-currency numerator (TWD revenue/net_income/debt) with a
    quote-currency denominator (USD market_cap/shares) — the cross-currency garbage
    that prints a TWD-per-share implied price as USD and a meaningless WACC
    debt-weight (BUG-073). Symmetric with the peer-comps path (BUG-018).

    Field rules (identical caliber to the peer normalizer):

    - **reporting-currency** (income statement + balance sheet line items) scaled by
      ``reporting_fx_rate_to_usd``: ``income.revenue / ebitda / net_income /
      operating_income / depreciation_amortization / rd_expense / sga_expense /
      interest_expense / income_tax_expense`` and ``balance.total_debt /
      total_cash``. ``None`` stays ``None`` (a missing figure is not 0).
    - **quote-currency** (market quote) scaled by ``quote_fx_rate_to_usd``:
      ``market.market_cap`` and the per-share price fields
      ``current_price / price_52w_high / price_52w_low`` (all quoted in the quote
      currency).
    - **enterprise_value** mixes quote-currency market_cap with reporting-currency
      net debt; when the two currencies disagree the cached value is meaningless,
      so it is dropped (recomputed downstream from the now-USD inputs). When they
      agree it scales by the (shared) rate.
    - **recomputed**: ``pe_ratio`` is re-derived from the converted USD
      ``market_cap / net_income``. It is NOT safely dimensionless when the
      provider computed it pre-normalization across two currencies (quote-ccy
      market_cap / reporting-ccy net_income — the SAP/TSM/TM ADR bug, probe
      2026-06-06), so the cached value cannot be carried through; the FX boundary
      is the first point both sides share a currency.
    - **untouched**: ``shares_outstanding`` (a count), ``beta`` and the margin
      fields (dimensionless ratios). Per-share *amounts* that are already in the
      quote currency are handled above.

    Args:
        financials: A ticker's snapshot carrying ``reporting_currency`` and
            ``quote_currency`` tags from the extractor layer.
        reporting_fx_rate_to_usd: Multiplicative factor for IS/BS items —
            ``USD_value = local_value × rate`` (TWD→USD at 32 TWD/USD ⇒
            ``1/32 ≈ 0.0313``). Ignored when ``reporting_currency`` is USD.
        quote_fx_rate_to_usd: Multiplicative factor for market_cap / EV and the
            per-share price fields. Ignored when ``quote_currency`` is USD.

    Returns:
        A new ``FinancialData`` with both currency tags set to USD and every
        monetary field scaled. Fast path: when both tags are already USD the input
        is returned unchanged (no copy) — the common US-issuer no-op.

    Raises:
        ValueError: If a rate that will actually be applied (the corresponding
            currency is non-USD) is non-positive or NaN.
    """
    reporting_src = financials.reporting_currency.upper()
    quote_src = financials.quote_currency.upper()

    if reporting_src == "USD" and quote_src == "USD":
        return financials

    if reporting_src != "USD":
        _validate_rate(reporting_fx_rate_to_usd, financials.ticker, reporting_src, "reporting")
        reporting_rate = reporting_fx_rate_to_usd
    else:
        reporting_rate = 1.0

    if quote_src != "USD":
        _validate_rate(quote_fx_rate_to_usd, financials.ticker, quote_src, "quote")
        quote_rate = quote_fx_rate_to_usd
    else:
        quote_rate = 1.0

    converted = financials.model_copy(deep=True)

    # ----- income statement (reporting currency) ----------------------------
    inc = financials.income
    converted.income.revenue = inc.revenue * reporting_rate
    converted.income.ebitda = inc.ebitda * reporting_rate if inc.ebitda is not None else None
    converted.income.net_income = (
        inc.net_income * reporting_rate if inc.net_income is not None else None
    )
    converted.income.operating_income = (
        inc.operating_income * reporting_rate if inc.operating_income is not None else None
    )
    converted.income.depreciation_amortization = (
        inc.depreciation_amortization * reporting_rate
        if inc.depreciation_amortization is not None
        else None
    )
    converted.income.rd_expense = (
        inc.rd_expense * reporting_rate if inc.rd_expense is not None else None
    )
    converted.income.sga_expense = (
        inc.sga_expense * reporting_rate if inc.sga_expense is not None else None
    )
    converted.income.interest_expense = (
        inc.interest_expense * reporting_rate if inc.interest_expense is not None else None
    )
    # income_tax_expense scales with net_income so the effective tax rate
    # tax/(net_income+tax) stays currency-invariant (mirrors the peer path).
    converted.income.income_tax_expense = (
        inc.income_tax_expense * reporting_rate if inc.income_tax_expense is not None else None
    )

    # ----- balance sheet (reporting currency) -------------------------------
    # None ≠ 0: preserve "not reported" through the FX conversion rather than
    # scaling a fabricated zero (mirrors the income_tax_expense guard above).
    converted.balance.total_debt = (
        None
        if financials.balance.total_debt is None
        else financials.balance.total_debt * reporting_rate
    )
    converted.balance.total_cash = (
        None
        if financials.balance.total_cash is None
        else financials.balance.total_cash * reporting_rate
    )
    # preferred stock + NCI are reporting-currency balance-sheet items (EV-bridge
    # completeness, numeric-audit family 3). Scale with the other IS/BS lines; None
    # stays None (a missing figure is not 0).
    converted.balance.preferred_stock = (
        None
        if financials.balance.preferred_stock is None
        else financials.balance.preferred_stock * reporting_rate
    )
    converted.balance.noncontrolling_interest = (
        None
        if financials.balance.noncontrolling_interest is None
        else financials.balance.noncontrolling_interest * reporting_rate
    )

    # ----- market quote (quote currency) ------------------------------------
    mkt = financials.market
    converted.market.market_cap = mkt.market_cap * quote_rate
    converted.market.current_price = mkt.current_price * quote_rate
    converted.market.price_52w_high = (
        mkt.price_52w_high * quote_rate if mkt.price_52w_high is not None else None
    )
    converted.market.price_52w_low = (
        mkt.price_52w_low * quote_rate if mkt.price_52w_low is not None else None
    )

    # ----- enterprise_value (mixed) -----------------------------------------
    ev = financials.valuation.enterprise_value
    if ev is not None:
        # EV = quote-ccy market_cap + reporting-ccy net debt. When the two
        # currencies disagree the cached value is meaningless; drop it so any
        # downstream consumer recomputes from the now-consistently-USD inputs.
        converted.valuation.enterprise_value = (
            None if reporting_src != quote_src else ev * quote_rate
        )

    # ----- pe_ratio (re-derived from the now-USD inputs) --------------------
    # The provider may have computed pe = mkt_cap(quote ccy) / net_income(reporting
    # ccy) BEFORE FX normalization — a dimensionally-mixed P/E for ADRs (SAP/TSM/TM,
    # probe 2026-06-06). This is the first point both numerator and denominator are
    # in one currency, so re-derive rather than carry the mixed cached value.
    ni_usd = converted.income.net_income
    converted.market.pe_ratio = (
        converted.market.market_cap / ni_usd
        if (converted.market.market_cap and ni_usd and ni_usd > 0)
        else None
    )

    converted.reporting_currency = "USD"
    converted.quote_currency = "USD"
    return converted


def _validate_rate(rate: float, ticker: str, src_ccy: str, kind: str) -> None:
    # isfinite rejects NaN AND ±Inf — `rate <= 0 or rate != rate` lets +Inf
    # through (positive, equal to itself) and an Inf rate fabricates Inf USD
    # line items downstream.
    if rate <= 0 or not math.isfinite(rate):
        raise ValueError(
            f"{kind}_fx_rate_to_usd must be positive and finite, got {rate!r} "
            f"for {ticker} ({src_ccy} → USD)"
        )
