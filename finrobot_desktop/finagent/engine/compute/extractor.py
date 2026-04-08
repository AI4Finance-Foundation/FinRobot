from finagent.engine.data.interface import DataResult
from finagent.engine.data.keys import REQUIRED_KEYS  # noqa: F401 — documents expected keys
from finagent.engine.models.financial import FinancialData, PriceHistory, CompanyFinancials
from finagent.engine.compute.multiples import calculate_ev


def extract_financial_data(
    financials_result: DataResult,
    price_result: DataResult,
) -> FinancialData:
    """Extract structured FinancialData from raw DataResults.

    Raises ValueError for missing critical fields (revenue, market_cap, current_price).
    Non-critical missing fields (debt, cash, D&A) are defaulted and recorded in
    FinancialData.warnings so the caller can surface them to the user.
    """
    data = financials_result.data
    ticker = financials_result.ticker

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
    if raw_debt is None:
        warnings.append(
            "total_debt not available from provider — defaulted to 0; "
            "EV-based multiples (EV/EBITDA, EV/Revenue) may be understated"
        )
    if raw_cash is None:
        warnings.append("total_cash not available from provider — defaulted to 0")

    da = data.get("depreciation_amortization")
    if da is None:
        warnings.append(
            "D&A unavailable — DCF will use simplified FCF formula; "
            "implied price may be overstated 10-20% for capital-intensive companies. "
            "Configure FMP or Finnhub API key to get D&A data."
        )

    ev = calculate_ev(market_cap, total_debt, total_cash)
    ev_ebitda = ev / ebitda if (ebitda and ebitda > 0) else None
    ev_revenue = ev / revenue if revenue > 0 else None

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

    return FinancialData(
        ticker=ticker,
        timestamp=financials_result.timestamp,
        revenue=revenue,
        ebitda=ebitda or 0,
        net_income=data.get("net_income") or 0,
        total_debt=total_debt,
        total_cash=total_cash,
        gross_margin=data.get("gross_margin") or 0,
        operating_margin=data.get("operating_margin") or 0,
        market_cap=market_cap,
        shares_outstanding=data.get("shares_outstanding") or 1,
        current_price=current_price,
        pe_ratio=data.get("pe_ratio"),
        enterprise_value=ev,
        ev_ebitda=ev_ebitda,
        ev_revenue=ev_revenue,
        price_52w_high=high_52w,
        price_52w_low=low_52w,
        depreciation_amortization=da,
        rd_expense=data.get("rd_expense"),
        sga_expense=data.get("sga_expense"),
        interest_expense=data.get("interest_expense"),
        data_source=financials_result.provider,
        warnings=warnings,
    )


def extract_company_financials(financials_result: DataResult) -> CompanyFinancials:
    """Extract CompanyFinancials for use in peer comparisons."""
    data = financials_result.data
    ticker = financials_result.ticker
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
