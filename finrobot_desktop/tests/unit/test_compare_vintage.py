"""Compare-table vintage/as_of provenance (BUG-057).

A Compare table assembles each ticker's *latest* stored DCF — which can be
today's run for one ticker and a three-week-old artifact for another. These
tests pin the disclosure: every row stamps the DCF's vintage, the Markdown
table shows it, and a wide vintage spread is warned.
"""

from __future__ import annotations

from finrobot.engine.compute.compare import (
    CompanyValuation,
    ComparisonResult,
    build_company_valuation,
    format_comparison_table,
    vintage_spread_days,
)
from finrobot.engine.models.financial import DCFInputs, DCFResult


def _dcf(implied: float = 200.0) -> DCFResult:
    return DCFResult(
        cost_of_equity=0.10,
        wacc=0.082,
        projection_years=5,
        projected_revenue=[1000],
        projected_ebitda=[300],
        projected_fcf=[200],
        terminal_value=4000,
        pv_terminal=3000,
        pv_fcf_total=2000,
        enterprise_value=5000,
        equity_value=4800,
        implied_price=implied,
        sensitivity_table=None,
        inputs=DCFInputs(
            revenue_base=1000,
            revenue_growth_rates=[0.10],
            ebitda_margin=0.30,
            capex_pct_revenue=0.04,
            nwc_pct_revenue=0.02,
            da_pct_revenue=0.04,
            tax_rate=0.21,
            risk_free_rate=0.04,
            beta=1.2,
            equity_risk_premium=0.05,
            cost_of_debt=0.05,
            debt_ratio=0.2,
            terminal_growth_rate=0.025,
            shares_outstanding=2.4e9,
            net_debt=30e9,
        ),
    )


def test_build_company_valuation_stamps_vintage() -> None:
    cv = build_company_valuation(
        ticker="AAPL",
        company_name="Apple",
        current_price=180.0,
        dcf_result=_dcf(),
        dcf_as_of="2026-05-01T00:00:00+00:00",
        dcf_artifact_id="art_AAPL_dcf",
    )
    assert cv.dcf_as_of == "2026-05-01T00:00:00+00:00"
    assert cv.dcf_artifact_id == "art_AAPL_dcf"


def test_build_company_valuation_defaults_to_live() -> None:
    # No as_of given (e.g. CLI/SDK live run) → None, rendered as "live".
    cv = build_company_valuation(
        ticker="AAPL", company_name="Apple", current_price=180.0, dcf_result=_dcf()
    )
    assert cv.dcf_as_of is None
    assert cv.dcf_artifact_id is None


def _cv(ticker: str, as_of: str | None) -> CompanyValuation:
    return CompanyValuation(
        ticker=ticker,
        implied_price=200.0,
        current_price=180.0,
        upside_pct=11.1,
        wacc=0.082,
        terminal_growth=0.025,
        dcf_as_of=as_of,
    )


def test_vintage_spread_days_measures_gap() -> None:
    result = ComparisonResult(
        companies=[
            _cv("AAPL", "2026-05-01T00:00:00+00:00"),
            _cv("MSFT", "2026-04-10T00:00:00+00:00"),
        ]
    )
    assert vintage_spread_days(result) == 21


def test_vintage_spread_none_when_under_two_dated() -> None:
    result = ComparisonResult(
        companies=[_cv("AAPL", "2026-05-01T00:00:00+00:00"), _cv("MSFT", None)]
    )
    assert vintage_spread_days(result) is None


def test_format_table_shows_vintage_and_warns_on_spread() -> None:
    result = ComparisonResult(
        companies=[
            _cv("AAPL", "2026-05-01T00:00:00+00:00"),
            _cv("MSFT", "2026-04-10T00:00:00+00:00"),
        ]
    )
    table = format_comparison_table(result)
    assert "DCF Date" in table
    assert "2026-05-01" in table
    assert "2026-04-10" in table
    # 21-day spread > 7-day threshold → an explicit apples-to-apples warning.
    assert "21 days" in table


def test_format_table_no_warning_when_vintages_close() -> None:
    result = ComparisonResult(
        companies=[
            _cv("AAPL", "2026-05-01T00:00:00+00:00"),
            _cv("MSFT", "2026-05-03T00:00:00+00:00"),
        ]
    )
    table = format_comparison_table(result)
    assert "DCF Date" in table
    assert "span" not in table


def test_format_table_live_rows_render_live() -> None:
    result = ComparisonResult(companies=[_cv("AAPL", None), _cv("MSFT", None)])
    table = format_comparison_table(result)
    assert "live" in table
    assert "span" not in table  # no dated rows → nothing to compare
