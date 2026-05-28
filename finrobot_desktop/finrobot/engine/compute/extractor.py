from datetime import date, datetime
from typing import Any

from finrobot.engine.data.interface import DataResult
from finrobot.engine.data.keys import NormalizedFinancialKeys
from finrobot.engine.models.financial import (
    FinancialData,
    IncomeStatement,
    BalanceSheet,
    MarketData,
    ValuationMetrics,
    PriceHistory,
    CompanyFinancials,
)
from finrobot.engine.compute.multiples import calculate_ev


def _parse_fiscal_period_end(raw: Any) -> date | None:
    """Parse provider-supplied fiscal-period-end date.

    Historical yfinance fetches stamp each year with ``fiscal_year`` (ISO date
    string like "2024-09-30"); FMP uses ``date`` in the same form. Single-year
    TTM fetches omit both — for those callers the field stays None and downstream
    consumers fall back to ``timestamp.year``.
    """
    if raw is None:
        return None
    if isinstance(raw, date) and not isinstance(raw, datetime):
        return raw
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, str) and raw:
        try:
            return date.fromisoformat(raw[:10])
        except ValueError:
            return None
    return None


def extract_financial_data(
    financials_result: DataResult,
    price_result: DataResult,
) -> FinancialData:
    """Extract structured FinancialData from raw DataResults.

    Raises ValueError for missing critical fields (revenue, market_cap).
    Non-critical missing fields (debt, cash, D&A) are defaulted and recorded in
    FinancialData.warnings so the caller can surface them to the user.
    """
    data: NormalizedFinancialKeys = financials_result.data  # type: ignore[assignment]
    ticker = financials_result.ticker

    # Batch-check required fields
    _REQUIRED = {"revenue", "market_cap"}
    missing = _REQUIRED - set(data.keys())
    if missing:
        raise ValueError(
            f"Provider {financials_result.provider} missing required fields for {ticker}: {missing}"
        )

    revenue = data.get("revenue")
    ebitda = data.get("ebitda")
    market_cap = data.get("market_cap")

    if not revenue:
        raise ValueError(f"Missing or zero revenue for {ticker}")
    if not market_cap:
        raise ValueError(f"Missing or zero market_cap for {ticker}")

    warnings: list[str] = []

    raw_debt = data.get("total_debt")
    raw_cash = data.get("total_cash")
    total_debt = raw_debt if raw_debt is not None else 0
    total_cash = raw_cash if raw_cash is not None else 0

    # --- N15: consistent EV handling ---
    # Only compute EV when both total_debt and total_cash are available.
    # Matches prompts.py behavior: no defaulting missing components to 0.
    ev: float | None = None
    ev_ebitda: float | None = None
    ev_revenue: float | None = None

    if raw_debt is not None and raw_cash is not None:
        ev = calculate_ev(market_cap, total_debt, total_cash)
        ev_ebitda = ev / ebitda if (ebitda and ebitda > 0) else None
        ev_revenue = ev / revenue if revenue > 0 else None
    else:
        missing_ev_parts = []
        if raw_debt is None:
            missing_ev_parts.append("total_debt")
        if raw_cash is None:
            missing_ev_parts.append("total_cash")
        warnings.append(
            f"{', '.join(missing_ev_parts)} not available from provider — "
            "EV and EV-based multiples (EV/EBITDA, EV/Revenue) cannot be computed"
        )

    # D&A is no longer required upstream — dcf_seed falls back to Damodaran
    # industry median when this is missing, with provenance noted on each field.
    da = data.get("depreciation_amortization")

    price_data = price_result.data
    price_history = price_data.get("price_history", [])
    closes = [p["close"] for p in price_history if "close" in p]
    high_52w = max(closes) if closes else None
    low_52w = min(closes) if closes else None

    current_price = price_data.get("current_price") or data.get("current_price")
    if not current_price or current_price <= 0:
        raise ValueError(
            f"Could not determine current_price for {ticker}. "
            "Ensure the price provider is configured and returning data."
        )

    # --- shares_outstanding: refuse silent fallback to 1 ---
    shares = data.get("shares_outstanding")
    if shares is None or shares <= 0:
        shares = market_cap / current_price
        warnings.append(
            f"shares_outstanding missing or invalid from {financials_result.provider} "
            f"for {ticker} — derived as market_cap/price ({shares:,.0f}). "
            "Per-share metrics (EPS, P/E) may be approximate."
        )

    fiscal_period_end = _parse_fiscal_period_end(
        data.get("fiscal_year") or data.get("date")
    )

    return FinancialData(
        ticker=ticker,
        company_name=str(data.get("company_name") or ""),
        timestamp=financials_result.timestamp,
        fiscal_period_end=fiscal_period_end,
        income=IncomeStatement(
            revenue=revenue,
            ebitda=ebitda or 0,
            net_income=data.get("net_income") or 0,
            gross_margin=data.get("gross_margin") or 0,
            operating_margin=data.get("operating_margin") or 0,
            depreciation_amortization=da,
            rd_expense=data.get("rd_expense"),
            sga_expense=data.get("sga_expense"),
            interest_expense=data.get("interest_expense"),
        ),
        balance=BalanceSheet(
            total_debt=total_debt,
            total_cash=total_cash,
        ),
        market=MarketData(
            market_cap=market_cap,
            shares_outstanding=shares,
            current_price=current_price,
            pe_ratio=data.get("pe_ratio"),
            price_52w_high=high_52w,
            price_52w_low=low_52w,
            industry=data.get("industry"),
            sector=data.get("sector"),
            beta=data.get("beta"),
        ),
        valuation=ValuationMetrics(
            enterprise_value=ev,
            ev_ebitda=ev_ebitda,
            ev_revenue=ev_revenue,
        ),
        data_source=financials_result.provider,
        warnings=warnings,
    )


# Map of country names (as returned by yfinance info["country"]) to the
# canonical IS/BS reporting currency (ISO 4217). Covers countries likely to
# appear as ADR peers in US-market equity research.
#
# Rationale: yfinance `financialCurrency` is unreliable for ADRs — it often
# returns "USD" for TSM (Taiwan), ASML (Netherlands), SAP (Germany) etc. when
# the actual IS/BS figures are in the local currency. We use the country field
# (which is correctly populated) as a reliable override signal.
#
# Only override when the provider says "USD" but country implies a different
# home currency — we never override a non-USD provider tag, because that
# would mask legitimate multi-currency structures (e.g. a Bermuda-domiciled
# holding co that genuinely reports in USD).
_COUNTRY_TO_REPORTING_CURRENCY: dict[str, str] = {
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


def _resolve_reporting_currency(
    provider_tag: str,
    ticker: str,
    country: str | None,
) -> str:
    """Return the reliable reporting currency for an issuer.

    If the provider says "USD" but the country mapping implies a different
    home currency AND the ticker has no '.' suffix (i.e. it is listed as an
    ADR on a US exchange, not a local listing already priced in local ccy),
    we override the provider tag. Local listings (e.g. 2330.TW) already have
    the correct non-USD tag from yfinance and are never overridden here.

    Args:
        provider_tag: The raw ``financialCurrency`` value from the provider.
        ticker: The ticker symbol (e.g. "TSM", "2330.TW").
        country: The ``country`` field from the provider, or None.

    Returns:
        ISO 4217 currency code (uppercase).
    """
    normalised = (provider_tag or "USD").upper()

    # Only apply the heuristic when the provider claims USD and a country
    # mapping exists. If provider already says non-USD, trust it.
    if normalised != "USD" or country is None:
        return normalised

    home_ccy = _COUNTRY_TO_REPORTING_CURRENCY.get(country)
    if home_ccy is None:
        return normalised  # US or unknown country — trust USD tag

    # ADR: traded on US exchange (no '.' in ticker) but incorporated abroad.
    # The IS/BS are in the home currency; only market_cap/price come in USD.
    if "." not in ticker:
        return home_ccy

    # Local listing (e.g. 2330.TW): yfinance already returns the correct
    # local currency for financialCurrency — no override needed.
    return normalised


def extract_company_financials(financials_result: DataResult) -> CompanyFinancials:
    """Extract CompanyFinancials for use in peer comparisons.

    ``reporting_currency`` carries the resolved IS/BS currency (ISO 4217).
    For ADRs where yfinance mis-tags ``financialCurrency`` as "USD", the
    country-based override in ``_resolve_reporting_currency`` corrects it so
    the downstream FX normalization step applies the proper conversion before
    EV/EBITDA is computed. Defaults to USD when country is unknown (US issuers).
    """
    data = financials_result.data
    ticker = financials_result.ticker
    provider_ccy = data.get("financial_currency") or "USD"
    country: str | None = data.get("country")
    reporting_currency = _resolve_reporting_currency(provider_ccy, ticker, country)
    return CompanyFinancials(
        ticker=ticker,
        revenue=data.get("revenue") or 0,
        ebitda=data.get("ebitda") or 0,
        net_income=data.get("net_income") or 0,
        market_cap=data.get("market_cap") or 0,
        total_debt=data.get("total_debt") or 0,
        total_cash=data.get("total_cash") or 0,
        gross_margin=data.get("gross_margin") or 0,
        operating_margin=data.get("operating_margin") or 0,
        pe_ratio=data.get("pe_ratio"),
        reporting_currency=reporting_currency,
        quote_currency=(data.get("quote_currency") or "USD").upper(),
    )


def extract_price_history(price_result: DataResult) -> PriceHistory:
    """Extract structured PriceHistory from raw yfinance price DataResult."""
    data = price_result.data
    history = data.get("price_history", [])
    closes = [p["close"] for p in history if "close" in p]
    avg = sum(closes) / len(closes) if closes else 0.0
    return PriceHistory(
        ticker=price_result.ticker,
        period="1y",
        data_points=len(closes),
        current_price=data.get("current_price") or 0,
        high_52w=max(closes) if closes else 0.0,
        low_52w=min(closes) if closes else 0.0,
        avg_price=avg,
    )
