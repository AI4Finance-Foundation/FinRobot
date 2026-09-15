"""Multiples reference test using Apple + 3 peers (MSFT/GOOG/META) public data.

Sources (all TTM as of ~Sep 2024, from Yahoo Finance / FactSet):
- AAPL: Revenue $391B, EBITDA $135B, Net Income $94B, Market Cap $3.45T,
        Debt $97B, Cash $30B
- MSFT: Revenue $245B, EBITDA $125B, Net Income $88B, Market Cap $3.10T,
        Debt $47B, Cash $18B
- GOOG: Revenue $340B, EBITDA $110B, Net Income $84B, Market Cap $2.10T,
        Debt $14B, Cash $101B
- META: Revenue $156B, EBITDA $70B, Net Income $48B, Market Cap $1.40T,
        Debt $18B, Cash $41B

Excel verification:
  EV_AAPL = 3450 + 97 - 30 = 3517B  → EV/EBITDA = 3517/135 = 26.05x
  EV_MSFT = 3100 + 47 - 18 = 3129B  → EV/EBITDA = 3129/125 = 25.03x
  EV_GOOG = 2100 + 14 - 101 = 2013B → EV/EBITDA = 2013/110 = 18.30x
  EV_META = 1400 + 18 - 41  = 1377B → EV/EBITDA = 1377/70  = 19.67x

  P/E_MSFT = 3100/88 = 35.23x
  P/E_GOOG = 2100/84 = 25.00x
  P/E_META = 1400/48 = 29.17x

  Median EV/EBITDA (peers only, sorted): 18.30, 19.67, 25.03 → median = 19.67
  Median P/E (peers only, sorted): 25.00, 29.17, 35.23 → median = 29.17
"""

from finrobot.engine.models.financial import CompanyFinancials, PeerComps
from finrobot.engine.compute.operators.multiples import (
    calculate_multiples,
    calculate_peer_statistics,
)


def _make(ticker, rev, ebitda, ni, mcap, debt, cash):
    c = CompanyFinancials(
        ticker=ticker,
        revenue=rev,
        ebitda=ebitda,
        net_income=ni,
        market_cap=mcap,
        total_debt=debt,
        total_cash=cash,
        gross_margin=0.5,
        operating_margin=0.3,
    )
    return calculate_multiples(c)


def test_multiples_big_tech_fy2024():
    aapl = _make("AAPL", 391e9, 135e9, 94e9, 3450e9, 97e9, 30e9)
    msft = _make("MSFT", 245e9, 125e9, 88e9, 3100e9, 47e9, 18e9)
    goog = _make("GOOG", 340e9, 110e9, 84e9, 2100e9, 14e9, 101e9)
    meta = _make("META", 156e9, 70e9, 48e9, 1400e9, 18e9, 41e9)

    # Verify EV calculations
    assert abs(aapl.enterprise_value - 3517e9) < 1e9
    assert abs(msft.enterprise_value - 3129e9) < 1e9
    assert abs(goog.enterprise_value - 2013e9) < 1e9
    assert abs(meta.enterprise_value - 1377e9) < 1e9

    # Verify individual EV/EBITDA
    assert abs(aapl.ev_ebitda - 26.05) < 0.1
    assert abs(goog.ev_ebitda - 18.30) < 0.1

    # Peer statistics (peers = MSFT, GOOG, META; target = AAPL)
    comps = PeerComps(target=aapl, peers=[msft, goog, meta])
    comps = calculate_peer_statistics(comps)

    # Median EV/EBITDA of peers: sorted [18.30, 19.67, 25.03] → median 19.67
    assert abs(comps.median_ev_ebitda - 19.67) < 0.5

    # Median P/E of peers: sorted [25.00, 29.17, 35.23] → median 29.17
    assert abs(comps.median_pe - 29.17) < 0.5
