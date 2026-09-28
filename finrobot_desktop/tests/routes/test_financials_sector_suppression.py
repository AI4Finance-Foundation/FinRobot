"""`extract_financial_data` must null the EV-based metrics for balance-sheet financials
(banks / insurers) at the canonical source, so NO consumer surface — the /financials
snapshot tile, the historical-bands current override, coverage rows, the report — can
leak a meaningless "EV/EBITDA 3.3×" for a bank. P/E, P/B and market cap (the
bank-applicable metrics) must survive. This is the structural gate for the recurring
"a new surface forgot to suppress bank EV/EBITDA" family — enforcing the invariant at
the producer means a future surface that reads FinancialData.valuation cannot reintroduce
the leak. audit.sector_sign (which flags enterprise_value + ev_ebitda for these issuers)
becomes a pure backstop. (2026-06-26)
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from finrobot.engine.compute.coordinators.extractor import extract_financial_data
from finrobot.engine.data.interface import DataResult
from finrobot.engine.data.normalize.financials import normalize_financials
from finrobot.engine.data.normalize.price import normalize_price


def _extracted(industry: str, sector: str = "Financial Services"):
    fin = normalize_financials(
        DataResult(
            data=dict(
                revenue=100e9,
                ebitda=80e9,
                net_income=50e9,
                gross_margin=0.6,
                operating_margin=0.4,
                pe_ratio=15.0,
                market_cap=8e11,
                shares_outstanding=2.5e9,
                current_price=320.0,
                total_debt=1e12,
                total_cash=1.5e12,
                book_value_per_share=128.0,
                industry=industry,
                sector=sector,
            ),
            provider="yfinance",
            ticker="T",
            data_type="financials",
            timestamp=datetime.now(tz=timezone.utc),
        )
    )
    price = normalize_price(
        DataResult(
            data={
                "current_price": 320.0,
                "price_history": [{"date": "2026-06-01", "close": 320.0}],
            },
            provider="yfinance",
            ticker="T",
            data_type="price",
            timestamp=datetime.now(tz=timezone.utc),
        )
    )
    return extract_financial_data(fin, price)


@pytest.mark.parametrize(
    "industry", ["Banks - Diversified", "Banks - Regional", "Insurance - Life"]
)
def test_balance_sheet_financial_ev_nulled_at_source(industry: str) -> None:
    fd = _extracted(industry)
    assert fd.valuation.enterprise_value is None
    assert fd.valuation.ev_ebitda is None
    assert fd.valuation.ev_ebitda_reported is None
    assert fd.valuation.ev_revenue is None
    # The bank-applicable metrics survive — only EV-based multiples are category errors.
    assert fd.market.pe_ratio is not None
    assert fd.valuation.book_value_per_share == 128.0
    assert fd.market.market_cap is not None


@pytest.mark.parametrize(
    "industry,sector",
    [
        ("Consumer Electronics", "Technology"),
        ("Insurance Brokers", "Financial Services"),  # asset-light fee biz — EV is meaningful
        ("Asset Management", "Financial Services"),  # BLK et al — not balance-sheet-funded
    ],
)
def test_non_balance_sheet_financial_keeps_ev(industry: str, sector: str) -> None:
    fd = _extracted(industry, sector)
    assert fd.valuation.enterprise_value is not None
    assert fd.valuation.ev_ebitda is not None
    assert fd.valuation.ev_revenue is not None
