from finagent.engine.data.interface import DataResult
from finagent.engine.models.financial import FinancialData, PriceHistory, CompanyFinancials
from finagent.engine.compute.multiples import calculate_ev


def extract_financial_data(
    financials_result: DataResult,
    price_result: DataResult,
) -> FinancialData:
    """Extract structured FinancialData from raw yfinance DataResults."""
    data = financials_result.data
    ticker = financials_result.ticker

    revenue = data.get("revenue")
    ebitda = data.get("ebitda")
    market_cap = data.get("market_cap")

    if not revenue:
        raise ValueError(f"Missing or zero revenue for {ticker}")
    if not market_cap:
        raise ValueError(f"Missing or zero market_cap for {ticker}")

    total_debt = data.get("total_debt") or 0
    total_cash = data.get("total_cash") or 0
    ev = calculate_ev(market_cap, total_debt, total_cash)

    ev_ebitda = ev / ebitda if (ebitda and ebitda > 0) else None
    ev_revenue = ev / revenue if revenue > 0 else None

    price_data = price_result.data
    price_history = price_data.get("price_history", [])
    closes = [p["close"] for p in price_history if "close" in p]
    high_52w = max(closes) if closes else None
    low_52w = min(closes) if closes else None

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
        current_price=price_data.get("current_price") or data.get("current_price") or 0,
        pe_ratio=data.get("pe_ratio"),
        enterprise_value=ev,
        ev_ebitda=ev_ebitda,
        ev_revenue=ev_revenue,
        price_52w_high=high_52w,
        price_52w_low=low_52w,
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
