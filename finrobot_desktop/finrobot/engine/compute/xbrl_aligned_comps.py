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
    """Return artifact-ready fact lists keyed by us-gaap concept.

    NetIncomeLoss is split into disambiguated keys to avoid two records
    colliding under the same concept:
      - ``us-gaap:NetIncomeLoss:ttm``    ← rolling 4-quarter TTM value+periods
      - ``us-gaap:NetIncomeLoss:annual`` ← latest annual point (float only)
    Revenue is not yet ambiguous (no TTM alt concept clash) so it keeps the
    plain key.  If that changes, apply the same :ttm/:annual suffix pattern.
    """
    snapshot: dict[str, list[dict[str, Any]]] = {}

    # TTM revenue — concept is typically a non-NetIncomeLoss variant, so no
    # collision risk; keep plain concept key.
    ttm_revenue = raw_xbrl.get("ttm_revenue")
    if isinstance(ttm_revenue, dict) and ttm_revenue.get("concept"):
        snapshot.setdefault(str(ttm_revenue["concept"]), []).append(ttm_revenue)

    # TTM net income — use disambiguated key to avoid collision with annual.
    ttm_net_income = raw_xbrl.get("ttm_net_income")
    if isinstance(ttm_net_income, dict) and ttm_net_income.get("concept"):
        ttm_entry = dict(ttm_net_income)
        ttm_entry["concept"] = "us-gaap:NetIncomeLoss:ttm"
        snapshot.setdefault("us-gaap:NetIncomeLoss:ttm", []).append(ttm_entry)

    # Annual (latest period) point values.
    for key, concept in (
        ("latest_revenue", "us-gaap:Revenues"),
        ("latest_gross_profit", "us-gaap:GrossProfit"),
        ("latest_operating_income", "us-gaap:OperatingIncomeLoss"),
        ("latest_total_assets", "us-gaap:Assets"),
        ("latest_total_liabilities", "us-gaap:Liabilities"),
        ("latest_shareholders_equity", "us-gaap:StockholdersEquity"),
    ):
        value = _num(raw_xbrl.get(key))
        if value is not None:
            snapshot.setdefault(concept, []).append({"concept": concept, "value": value})

    # Annual net income — disambiguated key matches the TTM sibling above.
    annual_net_income = _num(raw_xbrl.get("latest_net_income"))
    if annual_net_income is not None:
        snapshot.setdefault("us-gaap:NetIncomeLoss:annual", []).append(
            {"concept": "us-gaap:NetIncomeLoss:annual", "value": annual_net_income}
        )

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
