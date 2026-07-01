"""ADR-0006 验收 #3: canonical contract traceability across providers.

Same ticker, two provider shapes (yfinance vs FMP) → after ``normalize_*`` the
canonical object must converge on field name / unit / currency / period口径,
and provenance must not lie. These assertions drive only the pure normalize
functions with raw fixtures — no server, no live API — so they're fast and
deterministic. Real cross-provider fetches live in tests/integration.
"""

from __future__ import annotations

from datetime import datetime, timezone

from finrobot.engine.data.interface import DataResult
from finrobot.engine.data.normalize import (
    NormalizedFinancials,
    normalize_financials,
    normalize_price,
)
from finrobot.engine.data.normalize.contracts import (
    DEGRADED_CLOSE_ONLY,
)

UTC = timezone.utc
FETCHED_AT = datetime(2026, 5, 30, 12, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Raw fixtures — modeled on real field-name differences between providers
# ---------------------------------------------------------------------------


def _yf_financials() -> DataResult:
    return DataResult(
        data={
            "revenue": 391_000_000_000,
            "ebitda": 134_000_000_000,
            "net_income": 94_000_000_000,
            "market_cap": 3_400_000_000_000,
            "financial_currency": "USD",
            "quote_currency": "USD",
            "country": "United States",
            "fiscal_year": "2025-09-27",
            "period_basis": "ttm",
        },
        provider="yfinance",
        ticker="AAPL",
        data_type="financials",
        timestamp=FETCHED_AT,
    )


def _fmp_financials() -> DataResult:
    # FMP reports annual with a slightly different revenue print; absolute units,
    # same currency. ~2% off → inside cross_validate's 15% tolerance.
    return DataResult(
        data={
            "revenue": 400_000_000_000,
            "ebitda": 137_000_000_000,
            "net_income": 97_000_000_000,
            "market_cap": 3_420_000_000_000,
            "financial_currency": "USD",
            "quote_currency": "USD",
            "country": "US",
            "date": "2025-09-27",
            "period_basis": "annual",
        },
        provider="fmp",
        ticker="AAPL",
        data_type="financials",
        timestamp=FETCHED_AT,
    )


def _cross_border_financials() -> DataResult:
    # ADR case: a Japanese issuer's IS/BS in JPY, quote in USD. The provider tag
    # is authoritative (2026-06-10 21-ticker probe: yfinance financialCurrency
    # 21/21 correct) — the old country-based USD rewrite corrupted 7/9 genuine
    # USD-reporting foreign issuers and is gone.
    return DataResult(
        data={
            "revenue": 45_000_000_000_000,  # JPY absolute
            "financial_currency": "JPY",
            "quote_currency": "USD",  # ADR trades in USD
            "country": "Japan",
            "fiscal_year": "2025-03-31",
            "period_basis": "annual",
        },
        provider="yfinance",
        ticker="TM",
        data_type="financials",
        timestamp=FETCHED_AT,
    )


def _yf_price() -> DataResult:
    return DataResult(
        data={
            "current_price": 175.0,
            "quote_currency": "USD",
            "price_history": [
                # Ancient bar (>52w before the latest) — must be trimmed out.
                {"date": "2024-01-02", "open": 100, "high": 101, "low": 99, "close": 100},
                {"date": "2026-05-20", "open": 170, "high": 171, "low": 169, "close": 170},
                {"date": "2026-05-21", "open": 171, "high": 176, "low": 169, "close": 175},
            ],
        },
        provider="yfinance",
        ticker="AAPL",
        data_type="price",
        timestamp=FETCHED_AT,
    )


def _fmp_price_close_only() -> DataResult:
    # Legacy FMP serietype=line: close only, no intraday OHLC.
    return DataResult(
        data={
            "current_price": 175.0,
            "quote_currency": "USD",
            "price_history": [
                {"date": "2026-05-20", "close": 170},
                {"date": "2026-05-21", "close": 175},
            ],
        },
        provider="fmp",
        ticker="AAPL",
        data_type="price",
        timestamp=FETCHED_AT,
    )


# ---------------------------------------------------------------------------
# 1. Field-name convergence
# ---------------------------------------------------------------------------


def test_field_names_converge_across_providers() -> None:
    yf = normalize_financials(_yf_financials())
    fmp = normalize_financials(_fmp_financials())
    assert set(type(yf).model_fields) == set(type(fmp).model_fields)
    # Key fields populated on both paths (no provider-specific gaps).
    for obj in (yf, fmp):
        assert obj.revenue > 0
        assert obj.reporting_currency
        assert obj.period_basis in ("ttm", "annual", "quarterly")


# ---------------------------------------------------------------------------
# 2. Unit consistency (absolute, same currency, within cross-source tolerance)
# ---------------------------------------------------------------------------


def test_revenue_units_consistent_within_tolerance() -> None:
    yf = normalize_financials(_yf_financials()).revenue
    fmp = normalize_financials(_fmp_financials()).revenue
    # Both absolute (no millions scaling) → relative gap well under 15%.
    assert abs(yf - fmp) / max(yf, fmp) < 0.15


# ---------------------------------------------------------------------------
# 3. Currency traceable (+ cross-border inference degraded marker)
# ---------------------------------------------------------------------------


def test_currency_traceable_on_both_paths() -> None:
    for raw in (_yf_financials(), _fmp_financials()):
        out = normalize_financials(raw)
        assert out.reporting_currency.isupper() and len(out.reporting_currency) == 3
        assert out.quote_currency.isupper() and len(out.quote_currency) == 3


def test_cross_border_currency_tags_pass_through() -> None:
    out = normalize_financials(_cross_border_financials())
    assert out.reporting_currency == "JPY"  # provider tag, taken at face value
    assert out.quote_currency == "USD"  # ADR still quoted in USD
    assert "ccy_inferred" not in out.provenance.degraded


def test_usd_reporting_foreign_issuer_not_rewritten() -> None:
    # The LULU/SHEL class: foreign country, genuinely-USD filings. The retired
    # country heuristic rewrote these to CAD/GBP and FX-"normalized" correct
    # numbers into wrong ones (LULU ×~0.73). Tags must survive untouched; the
    # family-1 verifier (audit_foreign_issuer_usd_tags) owns the review banner.
    raw = _cross_border_financials()
    raw.data["financial_currency"] = "USD"
    raw.data["country"] = "Canada"
    out = normalize_financials(raw)
    assert out.reporting_currency == "USD"
    assert out.quote_currency == "USD"
    assert "ccy_inferred" not in out.provenance.degraded


# ---------------------------------------------------------------------------
# 4. Period口径 traceable
# ---------------------------------------------------------------------------


def test_period_basis_and_end_traceable() -> None:
    yf = normalize_financials(_yf_financials())
    fmp = normalize_financials(_fmp_financials())
    assert yf.period_basis == "ttm"
    assert fmp.period_basis == "annual"  # FMP annual tag preserved
    assert str(yf.period_end) == "2025-09-27"
    assert str(fmp.period_end) == "2025-09-27"


# ---------------------------------------------------------------------------
# 5. Provenance doesn't lie
# ---------------------------------------------------------------------------


def test_provenance_provider_and_as_of_are_honest() -> None:
    yf = normalize_financials(_yf_financials())
    assert yf.provenance.provider == "yfinance"  # not hardcoded
    # Financials as_of == period end, NOT the wall-clock fetch time.
    assert yf.provenance.as_of.date().isoformat() == "2025-09-27"
    assert yf.provenance.as_of != yf.provenance.fetched_at
    assert yf.provenance.fetched_at == FETCHED_AT


def test_price_provenance_as_of_is_latest_bar() -> None:
    px = normalize_price(_yf_price())
    assert px.provenance.provider == "yfinance"
    assert px.provenance.as_of.date().isoformat() == "2026-05-21"  # latest in-window bar
    assert px.provenance.as_of != px.provenance.fetched_at


# ---------------------------------------------------------------------------
# 6. Price window + OHLC completeness
# ---------------------------------------------------------------------------


def test_price_window_trimmed_and_ohlc_flagged() -> None:
    yf = normalize_price(_yf_price())
    # Ancient 2024 bar trimmed; only the two in-window bars survive.
    assert len(yf.bars) == 2
    assert all(b.date.year == 2026 for b in yf.bars)
    assert yf.is_ohlc_complete is True
    assert DEGRADED_CLOSE_ONLY not in yf.provenance.degraded

    fmp = normalize_price(_fmp_price_close_only())
    assert fmp.is_ohlc_complete is False
    assert DEGRADED_CLOSE_ONLY in fmp.provenance.degraded
    # 52w high/low fall back to close when OHLC absent.
    assert fmp.fifty_two_week_high() == 175.0


# ---------------------------------------------------------------------------
# Guard: NormalizedFinancials stays a single shared contract
# ---------------------------------------------------------------------------


def test_model_is_single_contract() -> None:
    # Both providers' output is the SAME class — no provider-specific subclass.
    assert type(normalize_financials(_yf_financials())) is NormalizedFinancials
    assert type(normalize_financials(_fmp_financials())) is NormalizedFinancials
