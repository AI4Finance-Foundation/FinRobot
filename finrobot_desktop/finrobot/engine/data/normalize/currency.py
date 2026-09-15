"""Canonical FX normalization for the data layer (ADR-0004 / ADR-0006).

The IS/BS reporting currency is the PROVIDER TAG, taken at face value. There is
deliberately no country→currency rewrite here, and one must never come back:
a country-keyed heuristic ("USD tag + foreign country ⇒ must really be the home
currency") existed until 2026-06-10 and was retired on live evidence — a
21-ticker basket probe found yfinance ``financialCurrency`` correct 21/21
(TSM=TWD, SAP=EUR, SONY=JPY, … all 12 non-USD reporters tagged right), while
the heuristic itself corrupted 7 of 9 genuinely-USD-reporting foreign issuers
(SHEL/BP/RIO/AZN/LIN→GBP, TTE→EUR, LULU→CAD), FX-"normalizing" correct USD
statements by ~±27% across every line item. The failure mode it guarded had
healed upstream; only the harm remained. FMP supplies an authoritative
``reportedCurrency`` outright (probe 2026-06-08).

The residual ambiguity — a foreign issuer whose snapshot reads USD/USD could
in principle still be a provider mis-tag — is owned by the family-1 verifier
``audit_foreign_issuer_usd_tags`` (severity=review, banner only): flag for an
analyst's eye, never rewrite a number on a guess.
"""

from __future__ import annotations

from finrobot.engine.data.normalize.contracts import NormalizedFinancials
from finrobot.engine.primitives.dividend import reconcile_per_share_dividend_to_quote_unit


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
    # ADR per-share/per-ADR reconciliation: the provider per-share DPS is per-ORDINARY
    # share while the (untouched, quote-currency) price is per-ADR — FX-scaling alone
    # leaves it on the wrong unit (TSM: $0.69 per ordinary beside a per-ADR price/yield
    # ≈ $3.8). Re-derive to the quote unit from the dimensionless yield × price so the
    # DISPLAYED DPS/price/yield are self-consistent — the same guard the DDM seed runs,
    # now applied at the canonical layer so every consumer (report summary, /financials)
    # gets it, not just the bank DDM path. dividend_yield is currency-invariant (unchanged).
    reconciled_dps, dps_note = reconcile_per_share_dividend_to_quote_unit(
        converted.dividend_per_share, financials.dividend_yield, converted.current_price
    )
    converted.dividend_per_share = reconciled_dps
    if dps_note is not None:
        converted.warnings = [*converted.warnings, dps_note]
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
