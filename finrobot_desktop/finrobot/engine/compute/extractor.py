from finrobot.engine.data.interface import DataResult
from finrobot.engine.data.normalize.currency import resolve_reporting_currency
from finrobot.engine.data.normalize.financials import normalize_financials
from finrobot.engine.data.normalize.price import normalize_price
from finrobot.engine.data.normalize.window import trailing_52w_high_low
from finrobot.engine.models.financial import (
    DataProvenance,
    FinancialData,
    IncomeStatement,
    BalanceSheet,
    MarketData,
    ValuationMetrics,
    PriceHistory,
    CompanyFinancials,
)
from finrobot.engine.compute.multiples import (
    calculate_ebitda_operating,
    calculate_ebitda_reported,
    calculate_ev,
)


def extract_financial_data(
    financials_result: DataResult,
    price_result: DataResult,
) -> FinancialData:
    """Extract structured FinancialData from raw DataResults.

    The raw provider dicts are first pressed through the normalization contract
    (``normalize_financials`` / ``normalize_price``) so every field below reads
    a typed canonical value instead of an unspecified provider-specific dict
    (ADR-0004). 52-week high/low come from the windowed, intraday-aware
    canonical series; ``provenance`` carries source/as_of/degraded to the UI.

    Raises ValueError for missing critical fields (revenue, market_cap).
    Non-critical missing fields (debt, cash, D&A) are defaulted and recorded in
    FinancialData.warnings so the caller can surface them to the user.
    """
    fin = normalize_financials(financials_result)
    price = normalize_price(price_result)
    ticker = fin.ticker

    revenue = fin.revenue
    market_cap = fin.market_cap

    # Two EBITDA calibers, recomputed from absolute line items so neither
    # rides on a provider's opaque (and, for the latest quarter, sometimes
    # D&A-less) ebitda field. Operating is the primary EV/EBITDA numerator;
    # reported is the street cross-check. Falls back to the provider-supplied
    # ebitda only when components are absent (e.g. yfinance-sourced snapshots).
    ebitda_operating = calculate_ebitda_operating(
        fin.operating_income, fin.depreciation_amortization
    )
    if ebitda_operating is None:
        ebitda_operating = fin.ebitda
    ebitda_reported = calculate_ebitda_reported(
        fin.net_income,
        fin.income_tax_expense,
        fin.interest_expense,
        fin.depreciation_amortization,
    )
    ebitda = ebitda_operating

    if not revenue:
        raise ValueError(f"Missing or zero revenue for {ticker}")
    if not market_cap:
        raise ValueError(f"Missing or zero market_cap for {ticker}")

    warnings: list[str] = []

    raw_debt = fin.total_debt
    raw_cash = fin.total_cash
    total_debt = raw_debt if raw_debt is not None else 0
    total_cash = raw_cash if raw_cash is not None else 0

    # --- N15: consistent EV handling ---
    # Only compute EV when both total_debt and total_cash are available.
    # Matches prompts.py behavior: no defaulting missing components to 0.
    ev: float | None = None
    ev_ebitda: float | None = None
    ev_ebitda_reported: float | None = None
    ev_revenue: float | None = None

    if raw_debt is not None and raw_cash is not None:
        ev = calculate_ev(market_cap, total_debt, total_cash)
        ev_ebitda = ev / ebitda_operating if (ebitda_operating and ebitda_operating > 0) else None
        ev_ebitda_reported = (
            ev / ebitda_reported if (ebitda_reported and ebitda_reported > 0) else None
        )
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

    # 52w high/low from the canonical (windowed to trailing 52 weeks, intraday
    # high/low when present, close fallback otherwise).
    high_52w = price.fifty_two_week_high()
    low_52w = price.fifty_two_week_low()

    current_price = price.current_price or fin.current_price
    if not current_price or current_price <= 0:
        raise ValueError(
            f"Could not determine current_price for {ticker}. "
            "Ensure the price provider is configured and returning data."
        )

    # --- shares_outstanding: refuse silent fallback to 1 ---
    shares = fin.shares_outstanding
    if shares is None or shares <= 0:
        shares = market_cap / current_price
        warnings.append(
            f"shares_outstanding missing or invalid from {fin.provenance.provider} "
            f"for {ticker} — derived as market_cap/price ({shares:,.0f}). "
            "Per-share metrics (EPS, P/E) may be approximate."
        )

    return FinancialData(
        ticker=ticker,
        company_name=fin.company_name or "",
        timestamp=financials_result.timestamp,
        fiscal_period_end=fin.period_end,
        income=IncomeStatement(
            revenue=revenue,
            ebitda=ebitda or 0,
            net_income=fin.net_income or 0,
            gross_margin=fin.gross_margin or 0,
            operating_margin=fin.operating_margin or 0,
            depreciation_amortization=fin.depreciation_amortization,
            rd_expense=fin.rd_expense,
            sga_expense=fin.sga_expense,
            interest_expense=fin.interest_expense,
        ),
        balance=BalanceSheet(
            total_debt=total_debt,
            total_cash=total_cash,
        ),
        market=MarketData(
            market_cap=market_cap,
            shares_outstanding=shares,
            current_price=current_price,
            pe_ratio=fin.pe_ratio,
            price_52w_high=high_52w,
            price_52w_low=low_52w,
            industry=fin.industry,
            sector=fin.sector,
            beta=fin.beta,
        ),
        valuation=ValuationMetrics(
            enterprise_value=ev,
            ebitda_operating=ebitda_operating,
            ebitda_reported=ebitda_reported,
            ev_ebitda=ev_ebitda,
            ev_ebitda_reported=ev_ebitda_reported,
            ev_revenue=ev_revenue,
        ),
        data_source=fin.provenance.provider,
        provenance=DataProvenance(
            provider=fin.provenance.provider,
            as_of=fin.period_end,
            period_basis=fin.period_basis,
            pe_ttm_lag_quarters=fin.pe_ttm_lag_quarters,
            # Combine financials degraded flags (ttm_lag, ccy_inferred) with the
            # price feed's (close_only) since the snapshot shows both 52w (price)
            # and P/E (financials) numbers.
            degraded=list(
                dict.fromkeys([*fin.provenance.degraded, *price.provenance.degraded])
            ),
        ),
        warnings=warnings,
    )


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
    reporting_currency = resolve_reporting_currency(provider_ccy, ticker, country)
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
    high_52w, low_52w = trailing_52w_high_low(history)
    return PriceHistory(
        ticker=price_result.ticker,
        period="1y",
        data_points=len(closes),
        current_price=data.get("current_price") or 0,
        high_52w=high_52w if high_52w is not None else 0.0,
        low_52w=low_52w if low_52w is not None else 0.0,
        avg_price=avg,
    )
