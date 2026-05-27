"""XBRL-aligned peer-company helpers.

These functions keep peer comps deterministic while letting SEC XBRL facts
override yfinance/FMP fields when the standardized fact is available.
"""

from __future__ import annotations

from typing import Any

from finrobot.engine.compute.multiples import calculate_multiples
from finrobot.engine.models.financial import CompanyFinancials, FinancialData


def _num(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def xbrl_concept_snapshot(raw_xbrl: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Return artifact-ready fact lists keyed by us-gaap concept."""
    snapshot: dict[str, list[dict[str, Any]]] = {}
    for key in (
        "ttm_revenue",
        "ttm_net_income",
    ):
        metric = raw_xbrl.get(key)
        if isinstance(metric, dict) and metric.get("concept"):
            snapshot.setdefault(str(metric["concept"]), []).append(metric)
    for key, concept in (
        ("latest_revenue", "us-gaap:Revenues"),
        ("latest_net_income", "us-gaap:NetIncomeLoss"),
        ("latest_gross_profit", "us-gaap:GrossProfit"),
        ("latest_operating_income", "us-gaap:OperatingIncomeLoss"),
        ("latest_total_assets", "us-gaap:Assets"),
        ("latest_total_liabilities", "us-gaap:Liabilities"),
        ("latest_shareholders_equity", "us-gaap:StockholdersEquity"),
    ):
        value = _num(raw_xbrl.get(key))
        if value is not None:
            snapshot.setdefault(concept, []).append({"concept": concept, "value": value})
    return snapshot


def build_xbrl_aligned_company(
    *,
    ticker: str,
    financial_data: FinancialData,
    xbrl_data: dict[str, Any] | None,
) -> CompanyFinancials:
    """Create CompanyFinancials with SEC XBRL overriding core line items."""
    xbrl_data = xbrl_data or {}
    revenue = _num(xbrl_data.get("latest_revenue")) or financial_data.income.revenue
    net_income = _num(xbrl_data.get("latest_net_income")) or financial_data.income.net_income
    ebitda = financial_data.income.ebitda
    gross_margin = financial_data.income.gross_margin
    operating_margin = financial_data.income.operating_margin

    company = CompanyFinancials(
        ticker=ticker.upper(),
        revenue=revenue,
        ebitda=ebitda,
        net_income=net_income,
        market_cap=financial_data.market.market_cap,
        total_debt=financial_data.balance.total_debt,
        total_cash=financial_data.balance.total_cash,
        gross_margin=gross_margin,
        operating_margin=operating_margin,
    )
    return calculate_multiples(company)


def override_company_with_xbrl(
    company: CompanyFinancials,
    xbrl_data: dict[str, Any] | None,
) -> CompanyFinancials:
    """Return CompanyFinancials with SEC XBRL revenue/net income when present."""
    xbrl_data = xbrl_data or {}
    updates: dict[str, float] = {}
    revenue = _num(xbrl_data.get("latest_revenue"))
    net_income = _num(xbrl_data.get("latest_net_income"))
    if revenue is not None:
        updates["revenue"] = revenue
    if net_income is not None:
        updates["net_income"] = net_income
    if updates:
        company = company.model_copy(update=updates)
    return calculate_multiples(company)
