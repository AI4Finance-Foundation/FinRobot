"""P/E currency-caliber guard for the FMP provider.

market_cap is quote-currency, net_income is reporting-currency. For ADRs these
differ (SAP: USD/EUR, TSM: USD/TWD, TM: USD/JPY) and FMP's profile.pe is
currently None, so the naive ``mkt_cap / net_income`` fallback fabricated a
dimensionally-mixed P/E that shipped into the report snapshot
(SAP 29.4x, TSM 1.11x, TM 0.06x — live probe 2026-06-06). The provider is
synchronous and has no FX rate, so it must NOT fabricate a mixed-currency P/E.
"""

from __future__ import annotations

from finrobot.engine.data.providers.fmp_provider import _derive_pe


class TestDerivePe:
    def test_mixed_currency_returns_none(self):
        # SAP-shape: USD market_cap over EUR net_income — not a valid P/E here.
        assert _derive_pe(215.3e9, 7.313e9, fin_ccy="EUR", quote_ccy="USD") is None

    def test_same_currency_computes_ratio(self):
        assert _derive_pe(100.0, 5.0, fin_ccy="USD", quote_ccy="USD") == 20.0

    def test_local_listing_same_foreign_currency_computes_ratio(self):
        # 2330.TW: both tags TWD — same currency, ratio is valid.
        assert _derive_pe(1000.0, 50.0, fin_ccy="TWD", quote_ccy="TWD") == 20.0

    def test_negative_net_income_returns_none(self):
        assert _derive_pe(100.0, -5.0, fin_ccy="USD", quote_ccy="USD") is None

    def test_zero_net_income_returns_none(self):
        assert _derive_pe(100.0, 0.0, fin_ccy="USD", quote_ccy="USD") is None

    def test_missing_market_cap_returns_none(self):
        assert _derive_pe(None, 5.0, fin_ccy="USD", quote_ccy="USD") is None
